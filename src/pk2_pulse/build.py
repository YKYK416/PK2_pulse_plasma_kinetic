"""Stage, preprocess, compile, and execute an audited Gas1 pulse case."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from .bolsig import BolsigAudit, audit_database, generate_detailed_balance_database, sha256, stage_database
from .config import PulseCase
from .driver import render_closed_0d_pulse_driver
from .mechanism import (
    all_species_names,
    gas_species_names,
    stage_gas_phase_mechanism,
    stage_surface_assisted_mechanism,
)
from .runtime import ZDPlasKinRuntime, stage_runtime


@dataclass(frozen=True)
class CaseBuild:
    """Filesystem locations for an isolated, never-overwritten case build."""

    root: Path
    build_dir: Path
    results_dir: Path
    diagnostic_species: tuple[str, ...] = ()


def plan_case_build(project_root: Path, case: PulseCase, output_root: Path | None = None) -> dict[str, object]:
    """Describe the build without creating files or invoking native tools."""
    root = (output_root or project_root / "run_data" / case.id).resolve()
    return {
        "case_id": case.id,
        "output_root": str(root),
        "build_dir": str(root / "build"),
        "results_dir": str(root / "results"),
        "required_order": ["BOLSIG audit", "stage", "preprocess", "compile", "link", "parallel horizons"],
        "horizons_ms": list(case.horizons_ms),
        "cycles": [case.cycles_for_horizon(value) for value in case.horizons_ms],
        "output_every_cycles": case.output_every_cycles,
        "timeout_s": case.timeout_s,
        "solver_time_mode": case.solver_time_mode,
        "species_tolerance_mode": case.species_tolerance_mode,
        "driver_contract": "gas1_closed_0d_pulse.exe n_cycles output_csv",
    }


def stage_case_build(
    project_root: Path,
    case: PulseCase,
    runtime: ZDPlasKinRuntime,
    audit: BolsigAudit,
    output_root: Path | None = None,
    append_detailed_balance_inverses: bool = False,
) -> CaseBuild:
    """Create a case-local build from an accepted or explicit diagnostic database."""
    if not audit.accepted and not append_detailed_balance_inverses:
        raise ValueError("BOLSIG audit is not accepted; refusing to create a build directory")
    plan = plan_case_build(project_root, case, output_root)
    root = Path(str(plan["output_root"]))
    if root.exists():
        raise FileExistsError(f"Refusing to overwrite existing case output: {root}")
    build_dir = root / "build"
    results_dir = root / "results"
    build_dir.mkdir(parents=True)
    try:
        stage_runtime(runtime, build_dir)
        mechanism_dir = project_root / "mechanisms" / case.mechanism
        mechanism = mechanism_dir / ("kinet_source.txt" if case.has_surface_reactions else "kinet.inp")
        if case.has_surface_reactions:
            diagnostic_species = all_species_names(mechanism)
            mechanism_transform = stage_surface_assisted_mechanism(
                mechanism, build_dir, case.surface_auxiliary_files
            )
        else:
            diagnostic_species = gas_species_names(mechanism)
            mechanism_transform = stage_gas_phase_mechanism(
                mechanism, build_dir, disable_wall_relaxation=case.wall_relaxation == "disabled"
            )
        if append_detailed_balance_inverses:
            database_manifest = generate_detailed_balance_database(
                runtime.cross_section_database, build_dir / "bolsigdb.dat", upper_to_lower_weight_ratio=1.0
            )
            derived_audit = audit_database(mechanism, build_dir / "bolsigdb.dat")
            if not derived_audit.accepted:
                raise RuntimeError("Derived detailed-balance database still fails the BOLSIG audit")
            database_manifest["derived_audit"] = derived_audit.as_dict()
            database_manifest["scientific_status"] = "diagnostic_only_not_a_gas1_result"
        else:
            database_manifest = stage_database(runtime.cross_section_database, build_dir, audit)
        driver_path = build_dir / "gas1_closed_0d_pulse.F90"
        driver_path.write_text(
            render_closed_0d_pulse_driver(case, diagnostic_species), encoding="utf-8", newline="\n"
        )
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "case_config": str(case.config_path),
            "mechanism": str(mechanism),
            "mechanism_sha256": sha256(mechanism),
            "mechanism_transform": mechanism_transform,
            "diagnostic_species": list(diagnostic_species),
            "database": database_manifest,
            "model_assumptions": {
                "thermodynamic_boundary": case.thermodynamic_boundary,
                "gas_heating": case.gas_heating,
                "wall_relaxation": case.wall_relaxation,
                "electron_density_mode": case.electron_density_mode,
                "charge_compensation": case.charge_compensation,
                "MXSTEP": case.mxstep,
                "output_every_cycles": case.output_every_cycles,
                "timeout_s": case.timeout_s,
                "solver_time_mode": case.solver_time_mode,
                "species_tolerance_mode": case.species_tolerance_mode,
                "surface_reactions": case.surface_reactions,
                "surface_site_initialization": case.surface_site_initialization,
                "surface_site_density_cm3": case.surface_site_density_cm3,
                "surface_initial_densities_cm3": case.surface_initial_density_map,
                "surface_auxiliary_files": list(case.surface_auxiliary_files),
            },
            "reactor": {
                "id": case.reactor_id,
                "flow_enabled": case.flow_enabled,
                "residence_time_s": case.residence_time_s,
                "flow_species": case.flow_species,
                "excluded_from_flow": list(case.excluded_from_flow),
                "feed_pressure_pa": case.feed_pressure_pa,
                "feed_gas_temperature_k": case.feed_gas_temperature_k,
                "feed_x_n2": case.feed_x_n2,
                "feed_x_h2": case.feed_x_h2,
                "surface_states_excluded_from_flow": case.has_surface_reactions,
            },
            "runtime_dir": str(runtime.runtime_dir),
            "compiler": str(runtime.compiler),
            "driver": str(driver_path),
            "driver_sha256": sha256(driver_path),
            "plan": plan,
        }
        (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        # A partial native build should never be mistaken for a completed run.
        raise
    return CaseBuild(root=root, build_dir=build_dir, results_dir=results_dir, diagnostic_species=diagnostic_species)


def _run_checked(command: list[str], cwd: Path, log_name: str) -> None:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    (cwd / log_name).write_text((result.stdout or "") + (result.stderr or ""), encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}")


def _write_preprocessor_quality(build_dir: Path) -> None:
    """Record known vendor-preprocessor warnings instead of silently discarding them."""
    log = (build_dir / "preprocessor.log").read_text(encoding="utf-8", errors="replace")
    report = {
        "duplicate_reaction_warnings": log.count("duplicate reaction found"),
        "fortran_record_length_warnings": log.count("line exceeds 130 symbols")
        + log.count("record length exceeded 130 symbols"),
        "unused_species_warning": "following species are not used" in log,
        "compiler_line_length_policy": "gfortran -ffree-line-length-none",
        "mxstep_interface": "injected_into_case_local_generated_module",
        "status": "review_required_not_silently_ignored",
    }
    (build_dir / "preprocessor_quality.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {label} anchor, found {count}")
    return text.replace(old, new, 1)


def _patch_mxstep_interface(module_path: Path, species_tolerance_mode: str = "scalar") -> None:
    """Expose DVODE ``MXSTEP`` and optional per-species absolute tolerances."""
    text = module_path.read_text(encoding="utf-8")
    text = _replace_once(
        text,
        "subroutine ZDPlasKin_set_config(ATOL,RTOL,SILENCE_MODE,STAT_ACCUM,QTPLASKIN_SAVE,BOLSIG_EE_FRAC,BOLSIG_IGNORE_GAS_TEMPERATURE)",
        "subroutine ZDPlasKin_set_config(ATOL,RTOL,SILENCE_MODE,STAT_ACCUM,QTPLASKIN_SAVE,BOLSIG_EE_FRAC,BOLSIG_IGNORE_GAS_TEMPERATURE,MXSTEP)",
        "ZDPlasKin configuration interface",
    )
    text = _replace_once(
        text,
        "  double precision, optional, intent(in) :: ATOL, RTOL, BOLSIG_EE_FRAC\n",
        "  double precision, optional, intent(in) :: ATOL, RTOL, BOLSIG_EE_FRAC\n"
        "  integer, optional, intent(in) :: MXSTEP\n",
        "MXSTEP declaration",
    )
    text = _replace_once(
        text,
        "                                          dense_j=.true.,user_supplied_jacobian=.true., &\n"
        "                                          constrained=bounded_components(:),clower=dens_loc(:,0),cupper=dens_loc(:,1))",
        "                                          dense_j=.true.,user_supplied_jacobian=.true.,mxstep=MXSTEP, &\n"
        "                                          constrained=bounded_components(:),clower=dens_loc(:,0),cupper=dens_loc(:,1))",
        "DVODE MXSTEP option",
    )
    if species_tolerance_mode in {"scalar_unbounded", "scalar_signed_tiny", "positive_unbounded"}:
        scalar_bound = (
            ""
            if species_tolerance_mode in {"scalar_unbounded", "positive_unbounded"}
            else ", &\n                                          constrained=bounded_components(:),clower=dens_loc(:,0)-1.0d-6*atol_save,cupper=dens_loc(:,1)"
        )
        text = _replace_once(
            text,
            "    vode_options  = set_intermediate_opts(abserr=atol_save,relerr=rtol_save, &\n"
            "                                          dense_j=.true.,user_supplied_jacobian=.true.,mxstep=MXSTEP, &\n"
            "                                          constrained=bounded_components(:),clower=dens_loc(:,0),cupper=dens_loc(:,1))\n",
            "    vode_options  = set_intermediate_opts(abserr=atol_save,relerr=rtol_save, &\n"
            "                                          dense_j=.true.,user_supplied_jacobian=.true.,mxstep=MXSTEP"
            + scalar_bound
            + ")\n",
            "scalar unbounded DVODE option",
        )
    elif species_tolerance_mode in {
        "radical_floor",
        "radical_floor_signed",
        "radical_floor_signed_tiny",
        "radical_floor_unbounded",
        "positive_radical_floor_unbounded",
    }:
        text = _replace_once(
            text,
            "  integer, save :: bounded_components(vode_neq)\n",
            "  integer, save :: bounded_components(vode_neq)\n"
            "  double precision, save :: atol_vector(vode_neq)\n",
            "species tolerance vector declaration",
        )
        if species_tolerance_mode == "radical_floor":
            constrained_option = (
                "                                          constrained=bounded_components(:),clower=dens_loc(:,0),cupper=dens_loc(:,1))\n"
            )
        elif species_tolerance_mode == "radical_floor_signed":
            constrained_option = (
                "                                          constrained=bounded_components(:),clower=-atol_vector(:),cupper=dens_loc(:,1))\n"
            )
        elif species_tolerance_mode == "radical_floor_signed_tiny":
            constrained_option = (
                "                                          constrained=bounded_components(:),clower=-1.0d-6*atol_vector(:),cupper=dens_loc(:,1))\n"
            )
        elif species_tolerance_mode in {"radical_floor_unbounded", "positive_radical_floor_unbounded"}:
            constrained_option = "                                          )\n"
        else:
            raise ValueError(f"Unsupported radical-floor species tolerance mode: {species_tolerance_mode}")
        text = _replace_once(
            text,
            "    vode_options  = set_intermediate_opts(abserr=atol_save,relerr=rtol_save, &\n"
            "                                          dense_j=.true.,user_supplied_jacobian=.true.,mxstep=MXSTEP, &\n"
            "                                          constrained=bounded_components(:),clower=dens_loc(:,0),cupper=dens_loc(:,1))\n",
            "    atol_vector(:) = atol_save\n"
            "    ! Relax only low-density excited, radical, ionic, and surface states.\n"
            "    ! N2, H2, NH3, the prescribed electron, and gas temperature retain scalar ATOL.\n"
            "    atol_vector(2:20)  = max(atol_save, 100.0d0*atol_save)\n"
            "    atol_vector(22:36) = max(atol_save, 100.0d0*atol_save)\n"
            "    atol_vector(38:42) = max(atol_save, 100.0d0*atol_save)\n"
            "    atol_vector(44:48) = max(atol_save, 100.0d0*atol_save)\n"
            "    vode_options  = set_intermediate_opts(abserr_vector=atol_vector,relerr=rtol_save, &\n"
            + (
                "                                          dense_j=.true.,user_supplied_jacobian=.true.,mxstep=MXSTEP, &\n"
                + constrained_option
                if species_tolerance_mode in {
                    "radical_floor",
                    "radical_floor_signed",
                    "radical_floor_signed_tiny",
                }
                else "                                          dense_j=.true.,user_supplied_jacobian=.true.,mxstep=MXSTEP)\n"
            ),
            "per-species DVODE tolerance option",
        )
    elif species_tolerance_mode != "scalar":
        raise ValueError(f"Unsupported species tolerance mode: {species_tolerance_mode}")
    module_path.write_text(text, encoding="utf-8", newline="\n")


def _patch_surface_entropy_reads(module_path: Path) -> None:
    """Repair two long entropy READ statements truncated by the vendor preprocessor.

    The Windows ZDPlasKin preprocessor emits these two 21-value READ statements
    with a hard 256-character line limit.  The resulting source ends in a
    partial ``NH3_INERTIA_`` token (or a trailing comma), so gfortran reports a
    misleading cascade of syntax errors.  Split only these generated lines;
    all mechanism expressions remain byte-for-byte as emitted by the vendor
    preprocessor.
    """
    text = module_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    repaired = 0
    parameter_names = (
        "H2_VIB_1, N2_VIB_1, NH_VIB_1, NH2_VIB_1, NH2_VIB_2, NH2_VIB_3, "
        "NH3_VIB_1, NH3_VIB_2, NH3_VIB_3, NH3_VIB_4, NH3_VIB_5, NH3_VIB_6, "
        "H2_INERTIA_1, N2_INERTIA_1, NH_INERTIA_1, NH2_INERTIA_1, "
        "NH2_INERTIA_2, NH2_INERTIA_3, NH3_INERTIA_1, NH3_INERTIA_2, NH3_INERTIA_3"
    )
    basis_names = (
        "H2_VIB_BASIS_1, N2_VIB_BASIS_1, NH_VIB_BASIS_1, NH2_VIB_BASIS_1, "
        "NH2_VIB_BASIS_2, NH2_VIB_BASIS_3, NH3_VIB_BASIS_1, NH3_VIB_BASIS_2, "
        "NH3_VIB_BASIS_3, NH3_VIB_BASIS_4, NH3_VIB_BASIS_5, NH3_VIB_BASIS_6, "
        "H2_INERTIA_BASIS_1, N2_INERTIA_BASIS_1, NH_INERTIA_BASIS_1, "
        "NH2_INERTIA_BASIS_1, NH2_INERTIA_BASIS_2, NH2_INERTIA_BASIS_3, "
        "NH3_INERTIA_BASIS_1, NH3_INERTIA_BASIS_2, NH3_INERTIA_BASIS_3"
    )
    repaired_lines: list[str] = []
    for line in lines:
        if line.startswith("  READ(42,*) H2_VIB_1,"):
            repaired_lines.extend(
                [
                    "  READ(42,*) " + parameter_names.rsplit(", ", 1)[0] + ", &",
                    "       " + parameter_names.rsplit(", ", 1)[1],
                ]
            )
            repaired += 1
        elif line.startswith("  READ(42,*) H2_VIB_BASIS_1,"):
            repaired_lines.extend(
                [
                    "  READ(42,*) " + basis_names.rsplit(", ", 1)[0] + ", &",
                    "       " + basis_names.rsplit(", ", 1)[1],
                ]
            )
            repaired += 1
        else:
            repaired_lines.append(line)
    if repaired not in {0, 2}:
        raise RuntimeError(f"Expected both long surface entropy READ statements, repaired {repaired}")
    if repaired:
        repaired_text = "\n".join(repaired_lines) + "\n"
        use_anchor = (
            "  use ZDPlasKin, only : ZDPlasKin_bolsig_rates, bolsig_rates, bolsig_pointer, ZDPlasKin_cfg, "
            "ZDPlasKin_get_density_total, &\n"
            "                        lreaction_block, rrt\n"
        )
        use_replacement = (
            "  use ZDPlasKin, only : ZDPlasKin_bolsig_rates, bolsig_rates, bolsig_pointer, ZDPlasKin_cfg, "
            "ZDPlasKin_get_density_total, density, &\n"
            "                        lreaction_block, rrt\n"
        )
        if repaired_text.count(use_anchor) != 1:
            raise RuntimeError("Expected one surface reaction-rate USE list requiring density")
        module_path.write_text(
            repaired_text.replace(use_anchor, use_replacement, 1),
            encoding="utf-8",
            newline="\n",
        )


def _patch_surface_entropy_file_cache(module_path: Path) -> None:
    """Read fixed surface parameter files once per executable.

    The upstream generated rate routine opens and parses all four parameter
    files on every RHS evaluation.  Cache only the raw file values locally to
    the rate routine, then restore the working scalars before the existing
    temperature-dependent transformations.  This preserves the original
    formulas while removing repeated filesystem I/O from every ODE call.
    """
    text = module_path.read_text(encoding="utf-8")
    if "  READ(42,*) H2_VIB_1," not in text:
        return
    declaration_anchor = "  double precision :: De\n"
    declaration_replacement = (
        declaration_anchor
        + "  logical, save :: surface_parameter_files_loaded = .false.\n"
        + "  double precision, save :: surface_entropy_para_raw(21)\n"
        + "  double precision, save :: surface_entropy_basis_raw(21)\n"
        + "  double precision, save :: surface_reaction_e_raw(4)\n"
        + "  double precision, save :: surface_reaction_e_basis_raw(4)\n"
    )
    if text.count(declaration_anchor) != 1:
        raise RuntimeError("Expected one surface rate declaration anchor")
    text = text.replace(declaration_anchor, declaration_replacement, 1)

    old_reads = (
        "  OPEN(42,FILE=REACTION_ENTROPY_PARA_IN)\n"
        "  READ(42,*) ! EXCLUDE THE HEADER\n"
        "  READ(42,*) H2_VIB_1, N2_VIB_1, NH_VIB_1, NH2_VIB_1, NH2_VIB_2, NH2_VIB_3, NH3_VIB_1, NH3_VIB_2, NH3_VIB_3, NH3_VIB_4, NH3_VIB_5, NH3_VIB_6, H2_INERTIA_1, N2_INERTIA_1, NH_INERTIA_1, NH2_INERTIA_1, NH2_INERTIA_2, NH2_INERTIA_3, NH3_INERTIA_1, NH3_INERTIA_2, &\n"
        "       NH3_INERTIA_3\n"
        "  CLOSE(42)\n"
        "  OPEN(42,FILE=REACTION_ENTROPY_INFO_BASIS)\n"
        "  READ(42,*) ! EXCLUDE THE HEADER\n"
        "  READ(42,*) H2_VIB_BASIS_1, N2_VIB_BASIS_1, NH_VIB_BASIS_1, NH2_VIB_BASIS_1, NH2_VIB_BASIS_2, NH2_VIB_BASIS_3, NH3_VIB_BASIS_1, NH3_VIB_BASIS_2, NH3_VIB_BASIS_3, NH3_VIB_BASIS_4, NH3_VIB_BASIS_5, NH3_VIB_BASIS_6, H2_INERTIA_BASIS_1, N2_INERTIA_BASIS_1, NH_INERTIA_BASIS_1, NH2_INERTIA_BASIS_1, NH2_INERTIA_BASIS_2, NH2_INERTIA_BASIS_3, NH3_INERTIA_BASIS_1, NH3_INERTIA_BASIS_2, &\n"
        "       NH3_INERTIA_BASIS_3\n"
        "  CLOSE(42)\n"
        "  OPEN(42,FILE=REACTION_E_IN)\n"
        "  READ(42,*) ! EXCLUDE THE HEADER\n"
        "  READ(42,*) H2_NHS_ACE, NS_HS_ACT_E, NHS_HS_ACT_E, NH2S_HS_ACT_E\n"
        "  CLOSE(42)\n"
        "  OPEN(47,FILE=REACTION_E_BASIS)\n"
        "  READ(47,*) ! EXCLUDE THE HEADER\n"
        "  READ(47,*) H2_NHS_ACE_BASIS, NS_HS_ACT_E_BASIS, NHS_HS_ACT_E_BASIS, NH2S_HS_ACT_E_BASIS\n"
        "  CLOSE(47)\n"
    )
    cached_reads = (
        "  if(.not. surface_parameter_files_loaded) then\n"
        "    OPEN(42,FILE=REACTION_ENTROPY_PARA_IN)\n"
        "    READ(42,*) ! EXCLUDE THE HEADER\n"
        "    READ(42,*) surface_entropy_para_raw\n"
        "    CLOSE(42)\n"
        "    OPEN(42,FILE=REACTION_ENTROPY_INFO_BASIS)\n"
        "    READ(42,*) ! EXCLUDE THE HEADER\n"
        "    READ(42,*) surface_entropy_basis_raw\n"
        "    CLOSE(42)\n"
        "    OPEN(42,FILE=REACTION_E_IN)\n"
        "    READ(42,*) ! EXCLUDE THE HEADER\n"
        "    READ(42,*) surface_reaction_e_raw\n"
        "    CLOSE(42)\n"
        "    OPEN(47,FILE=REACTION_E_BASIS)\n"
        "    READ(47,*) ! EXCLUDE THE HEADER\n"
        "    READ(47,*) surface_reaction_e_basis_raw\n"
        "    CLOSE(47)\n"
        "    surface_parameter_files_loaded = .true.\n"
        "  endif\n"
        "  H2_VIB_1 = surface_entropy_para_raw(1)\n"
        "  N2_VIB_1 = surface_entropy_para_raw(2)\n"
        "  NH_VIB_1 = surface_entropy_para_raw(3)\n"
        "  NH2_VIB_1 = surface_entropy_para_raw(4)\n"
        "  NH2_VIB_2 = surface_entropy_para_raw(5)\n"
        "  NH2_VIB_3 = surface_entropy_para_raw(6)\n"
        "  NH3_VIB_1 = surface_entropy_para_raw(7)\n"
        "  NH3_VIB_2 = surface_entropy_para_raw(8)\n"
        "  NH3_VIB_3 = surface_entropy_para_raw(9)\n"
        "  NH3_VIB_4 = surface_entropy_para_raw(10)\n"
        "  NH3_VIB_5 = surface_entropy_para_raw(11)\n"
        "  NH3_VIB_6 = surface_entropy_para_raw(12)\n"
        "  H2_INERTIA_1 = surface_entropy_para_raw(13)\n"
        "  N2_INERTIA_1 = surface_entropy_para_raw(14)\n"
        "  NH_INERTIA_1 = surface_entropy_para_raw(15)\n"
        "  NH2_INERTIA_1 = surface_entropy_para_raw(16)\n"
        "  NH2_INERTIA_2 = surface_entropy_para_raw(17)\n"
        "  NH2_INERTIA_3 = surface_entropy_para_raw(18)\n"
        "  NH3_INERTIA_1 = surface_entropy_para_raw(19)\n"
        "  NH3_INERTIA_2 = surface_entropy_para_raw(20)\n"
        "  NH3_INERTIA_3 = surface_entropy_para_raw(21)\n"
        "  H2_VIB_BASIS_1 = surface_entropy_basis_raw(1)\n"
        "  N2_VIB_BASIS_1 = surface_entropy_basis_raw(2)\n"
        "  NH_VIB_BASIS_1 = surface_entropy_basis_raw(3)\n"
        "  NH2_VIB_BASIS_1 = surface_entropy_basis_raw(4)\n"
        "  NH2_VIB_BASIS_2 = surface_entropy_basis_raw(5)\n"
        "  NH2_VIB_BASIS_3 = surface_entropy_basis_raw(6)\n"
        "  NH3_VIB_BASIS_1 = surface_entropy_basis_raw(7)\n"
        "  NH3_VIB_BASIS_2 = surface_entropy_basis_raw(8)\n"
        "  NH3_VIB_BASIS_3 = surface_entropy_basis_raw(9)\n"
        "  NH3_VIB_BASIS_4 = surface_entropy_basis_raw(10)\n"
        "  NH3_VIB_BASIS_5 = surface_entropy_basis_raw(11)\n"
        "  NH3_VIB_BASIS_6 = surface_entropy_basis_raw(12)\n"
        "  H2_INERTIA_BASIS_1 = surface_entropy_basis_raw(13)\n"
        "  N2_INERTIA_BASIS_1 = surface_entropy_basis_raw(14)\n"
        "  NH_INERTIA_BASIS_1 = surface_entropy_basis_raw(15)\n"
        "  NH2_INERTIA_BASIS_1 = surface_entropy_basis_raw(16)\n"
        "  NH2_INERTIA_BASIS_2 = surface_entropy_basis_raw(17)\n"
        "  NH2_INERTIA_BASIS_3 = surface_entropy_basis_raw(18)\n"
        "  NH3_INERTIA_BASIS_1 = surface_entropy_basis_raw(19)\n"
        "  NH3_INERTIA_BASIS_2 = surface_entropy_basis_raw(20)\n"
        "  NH3_INERTIA_BASIS_3 = surface_entropy_basis_raw(21)\n"
        "  H2_NHS_ACE = surface_reaction_e_raw(1)\n"
        "  NS_HS_ACT_E = surface_reaction_e_raw(2)\n"
        "  NHS_HS_ACT_E = surface_reaction_e_raw(3)\n"
        "  NH2S_HS_ACT_E = surface_reaction_e_raw(4)\n"
        "  H2_NHS_ACE_BASIS = surface_reaction_e_basis_raw(1)\n"
        "  NS_HS_ACT_E_BASIS = surface_reaction_e_basis_raw(2)\n"
        "  NHS_HS_ACT_E_BASIS = surface_reaction_e_basis_raw(3)\n"
        "  NH2S_HS_ACT_E_BASIS = surface_reaction_e_basis_raw(4)\n"
    )
    if text.count(old_reads) != 1:
        raise RuntimeError("Expected one surface parameter-file read block")
    module_path.write_text(text.replace(old_reads, cached_reads, 1), encoding="utf-8", newline="\n")


def _patch_positive_unbounded_rhs(module_path: Path) -> None:
    """Evaluate chemistry and flow rates on a non-negative trial state.

    This is used only by the diagnostic ``positive_unbounded`` mode.  It lets
    DVODE take a trial step below zero without activating its bound-retraction
    loop, while keeping reaction-rate evaluation physically non-negative.
    """
    text = module_path.read_text(encoding="utf-8")
    anchor = "  density(:) = y(1:species_max)\n"
    if text.count(anchor) != 2:
        raise RuntimeError(f"Expected two positive-state RHS anchors, found {text.count(anchor)}")
    text = text.replace(anchor, "  density(:) = max(y(1:species_max), 0.0d0)\n")
    state_anchor = "  density(:) = dens_loc(1:species_max,0) - dens_loc(1:species_max,1) + densav(1:species_max)\n"
    if text.count(state_anchor) != 1:
        raise RuntimeError(f"Expected one positive-state update anchor, found {text.count(state_anchor)}")
    text = text.replace(
        state_anchor,
        "  density(:) = max(dens_loc(1:species_max,0) - dens_loc(1:species_max,1) + densav(1:species_max), 0.0d0)\n",
    )
    jac_flow_anchor = "      if(cstr_flow_mask(i)) pd(i,i) = pd(i,i) - 1.0d0 / cstr_tau_res\n"
    if text.count(jac_flow_anchor) == 1:
        text = text.replace(
            jac_flow_anchor,
            "      if(cstr_flow_mask(i) .and. y(i) > 0.0d0) pd(i,i) = pd(i,i) - 1.0d0 / cstr_tau_res\n",
        )
    jac_return_anchor = "  endif\n  return\nend subroutine ZDPlasKin_jex\n"
    if text.count(jac_return_anchor) != 1:
        raise RuntimeError(f"Expected one Jacobian return anchor, found {text.count(jac_return_anchor)}")
    text = text.replace(
        jac_return_anchor,
        "  endif\n"
        "  do i = 1, species_max\n"
        "    if(y(i) <= 0.0d0) pd(:,i) = 0.0d0\n"
        "  enddo\n"
        "  return\nend subroutine ZDPlasKin_jex\n",
    )
    module_path.write_text(text, encoding="utf-8", newline="\n")


def _patch_cstr_flow_interface(module_path: Path) -> None:
    """Add the CSTR inlet/outlet source to the case-local generated module.

    ZDPlasKin 2.0a exposes no CSTR hook in the generated module used by this
    mechanism.  Keep the patch local to the case build: the source term is
    added to the gas-heavy-species RHS and its diagonal Jacobian for the
    continuous (unsplit) mode.  A separate exact exponential flow-map API is
    retained for controlled experiments, while prescribed electron and
    surface-state densities remain outside the flow mask.
    """
    text = module_path.read_text(encoding="utf-8")
    text = _replace_once(
        text,
        "                                               density_constant(species_max), lgas_heating\n",
        "                                               density_constant(species_max), lgas_heating\n"
        "  logical, private                          :: lcstr_flow = .false., cstr_flow_mask(species_max)\n"
        "  logical, private                          :: lcstr_flow_rhs = .false.\n"
        "  double precision, private                 :: cstr_tau_res = 0.0d0, cstr_feed_density(species_max)\n",
        "CSTR state declarations",
    )
    text = _replace_once(
        text,
        "! set/get density for species\n!\n!-----------------------------------------------------------------------------------------------------------------------------------\nsubroutine ZDPlasKin_set_density",
        "! CSTR inlet/outlet flow\n!\n!-----------------------------------------------------------------------------------------------------------------------------------\nsubroutine ZDPlasKin_set_cstr_flow(TAU_RES,FEED_DENSITY,SPLIT_FLOW)\n  implicit none\n  double precision, intent(in) :: TAU_RES, FEED_DENSITY(species_max)\n  logical, optional, intent(in) :: SPLIT_FLOW\n  if(TAU_RES <= 0.0d0) call ZDPlasKin_stop(\"ZDPlasKin ERROR: CSTR residence time must be positive\")\n  if(any(FEED_DENSITY < 0.0d0)) call ZDPlasKin_stop(\"ZDPlasKin ERROR: CSTR feed densities must be non-negative\")\n  cstr_tau_res = TAU_RES\n  cstr_feed_density(:) = FEED_DENSITY(:)\n  cstr_flow_mask(:) = .true.\n  cstr_flow_mask(species_electrons) = .false.\n  if(species_electrons < species_max) cstr_flow_mask(species_electrons+1:species_max) = .false.\n  lcstr_flow = .true.\n  lcstr_flow_rhs = .true.\n  if(present(SPLIT_FLOW)) lcstr_flow_rhs = .not. SPLIT_FLOW\n  return\nend subroutine ZDPlasKin_set_cstr_flow\n!-----------------------------------------------------------------------------------------------------------------------------------\n!\n! exact CSTR flow map for Strang splitting\n!\n!-----------------------------------------------------------------------------------------------------------------------------------\nsubroutine ZDPlasKin_apply_cstr_flow(DTIME)\n  implicit none\n  double precision, intent(in) :: DTIME\n  double precision :: flow_factor\n  if(.not. lcstr_flow) return\n  if(DTIME < 0.0d0) call ZDPlasKin_stop(\"ZDPlasKin ERROR: CSTR flow step must be non-negative\")\n  flow_factor = exp(-DTIME / cstr_tau_res)\n  where(cstr_flow_mask) density(:) = cstr_feed_density(:) + &\n    ( density(:) - cstr_feed_density(:) ) * flow_factor\n  return\nend subroutine ZDPlasKin_apply_cstr_flow\n!-----------------------------------------------------------------------------------------------------------------------------------\n!\n! set/get density for species\n!\n!-----------------------------------------------------------------------------------------------------------------------------------\nsubroutine ZDPlasKin_set_density",
        "CSTR flow interface",
    )
    text = _replace_once(
        text,
        "  lgas_heating        = .false.\n  bolsig_eecol_frac       = bolsig_eecol_frac_def\n",
        "  lgas_heating        = .false.\n  lcstr_flow          = .false.\n  cstr_tau_res        = 0.0d0\n  cstr_feed_density(:) = 0.0d0\n  cstr_flow_mask(:)   = .false.\n  lcstr_flow_rhs      = .false.\n  bolsig_eecol_frac       = bolsig_eecol_frac_def\n",
        "CSTR reset state",
    )
    text = _replace_once(
        text,
        "  if( ldensity_constant ) where( density_constant(:) ) ydot(1:species_max) = 0.0d0\n  ydot(49) = 0.0d0\n",
        "  if( lcstr_flow_rhs ) then\n"
        "    where(cstr_flow_mask) ydot(1:species_max) = ydot(1:species_max) + &\n"
        "      ( cstr_feed_density(:) - density(:) ) / cstr_tau_res\n"
        "  endif\n"
        "  if( ldensity_constant ) where( density_constant(:) ) ydot(1:species_max) = 0.0d0\n  ydot(49) = 0.0d0\n",
        "CSTR RHS source",
    )
    text = _replace_once(
        text,
        "end subroutine ZDPlasKin_jex\n",
        "  if( lcstr_flow_rhs ) then\n"
        "    do i = 1, species_max\n"
        "      if(cstr_flow_mask(i)) pd(i,i) = pd(i,i) - 1.0d0 / cstr_tau_res\n"
        "    enddo\n"
        "  endif\n"
        "  return\nend subroutine ZDPlasKin_jex\n",
        "CSTR Jacobian source",
    )
    module_path.write_text(text, encoding="utf-8", newline="\n")


def preprocess_and_compile(build: CaseBuild, runtime: ZDPlasKinRuntime) -> Path:
    """Run the vendor preprocessor then compile in the vendor-recommended order."""
    generated_module = build.build_dir / "zdplaskin_m.F90"
    # The Windows preprocessor is interactive when invoked without arguments.
    # Supplying both names keeps the build non-interactive and records the
    # generated module at the location used by the compiler stage.
    _run_checked(
        [str(build.build_dir / runtime.preprocessor.name), "kinet.inp", generated_module.name],
        build.build_dir,
        "preprocessor.log",
    )
    if not generated_module.is_file():
        raise FileNotFoundError(f"Preprocessor did not create {generated_module.name}")
    _patch_surface_entropy_reads(generated_module)
    _patch_surface_entropy_file_cache(generated_module)
    manifest_path = build.root.joinpath("manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    species_tolerance_mode = manifest.get("model_assumptions", {}).get("species_tolerance_mode", "scalar")
    _patch_mxstep_interface(generated_module, species_tolerance_mode)
    if build.diagnostic_species and manifest:
        if manifest.get("reactor", {}).get("flow_enabled", False):
            _patch_cstr_flow_interface(generated_module)
            manifest["reactor"]["cstr_rhs_patch"] = "PK2_CSTR_FLOW_PATCH_V2_RHS_WITH_EXACT_MAP_API"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    if species_tolerance_mode in {"positive_unbounded", "positive_radical_floor_unbounded"}:
        _patch_positive_unbounded_rhs(generated_module)
    _write_preprocessor_quality(build.build_dir)
    compiler = str(runtime.compiler)
    common_flags = ["-O2", "-ffree-line-length-none"]
    _run_checked([compiler, *common_flags, "-c", "dvode_f90_m.F90"], build.build_dir, "compile_dvode.log")
    _run_checked(
        [compiler, *common_flags, "-c", generated_module.name, "gas1_closed_0d_pulse.F90"],
        build.build_dir,
        "compile_driver.log",
    )
    executable = build.build_dir / "gas1_closed_0d_pulse.exe"
    _run_checked(
        [
            compiler,
            *common_flags,
            "-o",
            executable.name,
            "gas1_closed_0d_pulse.o",
            "zdplaskin_m.o",
            "dvode_f90_m.o",
            runtime.bolsig_library.name,
            "-static-libgfortran",
            "-static-libgcc",
        ],
        build.build_dir,
        "link.log",
    )
    return executable


def _parse_float(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "e"))


def _sampled_cycles(cycles: int, output_every_cycles: int) -> int:
    return (cycles - 1) // output_every_cycles + 1


def _validate_series(path: Path, case: PulseCase, cycles: int) -> dict[str, object]:
    if not path.is_file():
        return {"accepted": False, "reason": "missing phase-endpoint CSV"}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    sampled = _sampled_cycles(cycles, case.output_every_cycles)
    expected = 1 + 2 * sampled
    if len(rows) != expected:
        return {"accepted": False, "reason": f"expected {expected} rows, found {len(rows)}"}
    expected_phases = [0] + [phase for _ in range(sampled) for phase in (1, 2)]
    if [int(row["phase"]) for row in rows] != expected_phases:
        return {"accepted": False, "reason": "unexpected pulse phase sequence"}
    final_time = _parse_float(rows[-1]["time_s"])
    target_time = cycles * case.period_s
    if not math.isclose(final_time, target_time, rel_tol=1e-8, abs_tol=1e-12):
        return {"accepted": False, "reason": f"final time {final_time} differs from {target_time}"}
    return {"accepted": True, "rows": len(rows), "final_time_s": final_time, "NH3_final_cm3": _parse_float(rows[-1]["NH3_cm3"])}


def _validate_species_endpoints(path: Path, case: PulseCase, cycles: int, species_count: int) -> dict[str, object]:
    if not path.is_file():
        return {"accepted": False, "reason": "missing species endpoint CSV"}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected_endpoints = 1 + 2 * _sampled_cycles(cycles, case.output_every_cycles)
    if len(rows) != expected_endpoints * species_count:
        return {"accepted": False, "reason": f"expected {expected_endpoints * species_count} rows, found {len(rows)}"}
    if any(not math.isfinite(_parse_float(row["density_cm3"])) for row in rows):
        return {"accepted": False, "reason": "non-finite species density"}
    return {"accepted": True, "rows": len(rows), "species_count": species_count}


def _validate_surface_endpoints(path: Path, case: PulseCase, cycles: int) -> dict[str, object]:
    if not case.has_surface_reactions:
        return {"accepted": True, "rows": 0, "surface_species_count": 0, "not_applicable": True}
    if not path.is_file():
        return {"accepted": False, "reason": "missing surface endpoint CSV"}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected_endpoints = 1 + 2 * _sampled_cycles(cycles, case.output_every_cycles)
    expected = expected_endpoints * len(case.surface_initial_densities)
    if len(rows) != expected:
        return {"accepted": False, "reason": f"expected {expected} rows, found {len(rows)}"}
    for row in rows:
        density = _parse_float(row["density_cm3"])
        coverage = _parse_float(row["coverage"])
        if not math.isfinite(density) or not math.isfinite(coverage) or density < 0.0 or coverage < 0.0:
            return {"accepted": False, "reason": "invalid surface density or coverage"}
    return {
        "accepted": True,
        "rows": len(rows),
        "surface_species_count": len(case.surface_initial_densities),
        "site_density_cm3": case.surface_site_density_cm3,
    }


def _validate_mean_reaction_rates(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"accepted": False, "reason": "missing mean reaction-rate CSV"}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {"accepted": False, "reason": "empty mean reaction-rate CSV"}
    if any(not math.isfinite(_parse_float(row["mean_rate_cm3_s"])) for row in rows):
        return {"accepted": False, "reason": "non-finite mean reaction rate"}
    return {"accepted": True, "rows": len(rows)}


def _audit_dvode_log(console: str, stderr: str) -> dict[str, object]:
    """Treat numerical DVODE warnings as an explicit result quality signal."""
    combined = f"{console}\n{stderr}"
    warning_count = len(re.findall(r"T \+ H = T", combined))
    solver_error_count = len(re.findall(r"DVODE solver issued an error|DVODE ERROR|ISTATE\s*=\s*-", combined, re.I))
    first_warning = next((line.strip() for line in combined.splitlines() if "T + H = T" in line), None)
    return {
        "warning_count": warning_count,
        "solver_error_count": solver_error_count,
        "first_warning": first_warning,
        "accepted": warning_count == 0 and solver_error_count == 0,
        "policy": "zero_T_plus_H_warnings_and_zero_DVODE_errors_required",
    }


def _stage_result_runtime(build: CaseBuild, result_dir: Path) -> None:
    result_dir.mkdir(parents=True, exist_ok=False)
    shutil.copy2(build.build_dir / "bolsigdb.dat", result_dir / "bolsigdb.dat")
    for source in build.build_dir.glob("*.DAT"):
        shutil.copy2(source, result_dir / source.name)


def run_time_scan(build: CaseBuild, case: PulseCase, max_workers: int) -> list[dict[str, Any]]:
    """Run isolated horizon directories concurrently after one shared build."""
    executable = build.build_dir / "gas1_closed_0d_pulse.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"Missing executable: {executable}")
    build.results_dir.mkdir(exist_ok=False)

    def run_horizon(horizon_ms: float) -> dict[str, Any]:
        cycles = case.cycles_for_horizon(horizon_ms)
        result_dir = build.results_dir / f"{horizon_ms:g}ms"
        _stage_result_runtime(build, result_dir)
        csv_path = result_dir / "pulse_summary.csv"
        species_path = result_dir / "species_endpoints.csv"
        surface_path = result_dir / "surface_endpoints.csv"
        mean_rates_path = result_dir / "mean_reaction_rates.csv"
        try:
            result = subprocess.run(
                [str(executable), str(cycles), csv_path.name],
                cwd=result_dir,
                text=True,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                timeout=case.timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            (result_dir / "console.log").write_text(stdout, encoding="utf-8", errors="replace")
            (result_dir / "stderr.log").write_text(
                f"{stderr}\nTimeout after {case.timeout_s:g} s\n", encoding="utf-8", errors="replace"
            )
            item = {
                "horizon_ms": horizon_ms,
                "cycles": cycles,
                "return_code": 124,
                "validation": {"accepted": False, "reason": "solver timeout"},
                "species_validation": {"accepted": False, "reason": "solver timeout"},
                "surface_validation": {"accepted": False, "reason": "solver timeout"},
                "reaction_rate_validation": {"accepted": False, "reason": "solver timeout"},
                "dvode_audit": _audit_dvode_log(stdout, stderr),
            }
            (result_dir / "manifest.json").write_text(
                json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            return item
        (result_dir / "console.log").write_text(result.stdout or "", encoding="utf-8", errors="replace")
        (result_dir / "stderr.log").write_text(result.stderr or "", encoding="utf-8", errors="replace")
        dvode_audit = _audit_dvode_log(result.stdout or "", result.stderr or "")
        validation = _validate_series(csv_path, case, cycles) if result.returncode == 0 else {
            "accepted": False,
            "reason": f"solver returned {result.returncode}",
        }
        species_validation = _validate_species_endpoints(
            species_path, case, cycles, len(build.diagnostic_species)
        ) if result.returncode == 0 else {"accepted": False, "reason": f"solver returned {result.returncode}"}
        surface_validation = _validate_surface_endpoints(surface_path, case, cycles) if result.returncode == 0 else {
            "accepted": False,
            "reason": f"solver returned {result.returncode}",
        }
        reaction_rate_validation = _validate_mean_reaction_rates(mean_rates_path) if result.returncode == 0 else {
            "accepted": False,
            "reason": f"solver returned {result.returncode}",
        }
        item = {
            "horizon_ms": horizon_ms,
            "cycles": cycles,
            "return_code": result.returncode,
            "validation": validation,
            "species_validation": species_validation,
            "surface_validation": surface_validation,
            "reaction_rate_validation": reaction_rate_validation,
            "dvode_audit": dvode_audit,
        }
        (result_dir / "manifest.json").write_text(json.dumps(item, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return item

    completed: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(case.horizons_ms))) as executor:
        futures = {executor.submit(run_horizon, horizon): horizon for horizon in case.horizons_ms}
        for future in as_completed(futures):
            completed.append(future.result())
    return sorted(completed, key=lambda item: float(item["horizon_ms"]))
