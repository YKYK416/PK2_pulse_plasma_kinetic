"""Build and run one reproducible closed 0D square-wave Hong gas-phase test.

The generated Fortran driver intentionally contains neither a CSTR flow call
nor a surface-site initialization.  Its source mechanism is byte-identical to
the gas-phase CSTR campaign mechanism, whose surface reactions are disabled
in ``kinet.inp`` using ``#OFF#`` records.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
OUTPUT_ROOT = SCRIPT_PATH.parents[1]
TOOL_DIR = Path(r"F:\Codex\PK1\Hong\工具脚本")
SOURCE_BUILD = Path(r"F:\Codex\PK1\Hong\Reproduction\2017Hong\方案2_脉冲能效地图\build_pulse")
REFERENCE_KINET = Path(
    r"F:\Codex\PK1\GasReaction\CSTR\cw_gasphase_cstr_tau_1to100ms_20260907"
    r"\worktree_cw_longtime\kinet.inp"
)

CASE_NAME = "squarewave_T300K_N2-0p1_H2-0p9_EN140Td_f10kHz_d50"
PARAMETERS = {
    "model": "closed 0D pure-gas pulsed reactor",
    "mechanism": "Hong gas-phase mechanism",
    "gas_temperature_K": 300.0,
    "x_N2": 0.1,
    "x_H2": 0.9,
    "electron_density_cm3": 1.17e8,
    "waveform": "square wave",
    "EN_on_Td": 140.0,
    "EN_off_Td": 0.0,
    "frequency_Hz": 10000.0,
    "duty_cycle": 0.5,
    "cycles": 10,
    "total_time_s": 1.0e-3,
    "atol": 1.0,
    "rtol": 1.0e-4,
}

RUNTIME_FILES = (
    "preprocessor.exe",
    "dvode_f90_m.F90",
    "bolsigdb.dat",
    "bolsig_x86_64_g.dll",
    "bolsig_x86_64_g.lib",
    "libquadmath-0.dll",
    "libgcc_s_seh-1.dll",
    "libgfortran-5.dll",
    "libwinpthread-1.dll",
    "data_in.dat",
    "Ele.dat",
    "other_para.dat",
    "ENTROPY_INFO_BASIS.DAT",
    "ENTROPY_PARA_IN.DAT",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"Required source file is missing: {path}")


def copy_runtime_files(build_dir: Path) -> None:
    for name in RUNTIME_FILES:
        source = SOURCE_BUILD / name
        if source.is_file():
            shutil.copy2(source, build_dir / name)
    for source in SOURCE_BUILD.glob("*.DAT"):
        shutil.copy2(source, build_dir / source.name)
    required = ("preprocessor.exe", "dvode_f90_m.F90", "bolsigdb.dat")
    missing = [name for name in required if not (build_dir / name).is_file()]
    if missing:
        raise RuntimeError(f"Incomplete runtime copy; missing: {', '.join(missing)}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {label} anchor, found {count}")
    return text.replace(old, new, 1)


def make_closed_0d_driver() -> str:
    """Render the standard pulse driver and remove every flow-only branch."""
    sys.path.insert(0, str(TOOL_DIR))
    import zdp_gui

    species = zdp_gui.parse_kinet_species(REFERENCE_KINET)
    text = zdp_gui.render_main_auto_pulse(
        composition=[("N2", PARAMETERS["x_N2"]), ("H2", PARAMETERS["x_H2"])],
        en_on=PARAMETERS["EN_on_Td"],
        en_off=PARAMETERS["EN_off_Td"],
        freq=PARAMETERS["frequency_Hz"],
        duty=PARAMETERS["duty_cycle"],
        cycles=PARAMETERS["cycles"],
        tg=PARAMETERS["gas_temperature_K"],
        ne=PARAMETERS["electron_density_cm3"],
        species=species,
        output_opts={"species": True, "te": True, "rates_t": False, "rates": False},
    )
    text = replace_once(
        text,
        "! 方波 E/N(t) 脉冲驱动；CLI: Tgas_K EN_on_Td EN_off_Td freq_Hz duty n_cycles_max tag [ATOL RTOL TAU_RES_S]",
        "! 封闭 0D 方波 E/N(t) 脉冲驱动；无进料/流出项。",
        "driver description",
    )
    text = replace_once(text, "  double precision :: tau_res, feed_density(species_max)\n", "", "flow declaration")
    text = replace_once(
        text,
        "  integer :: converged, nh3_idx, stable_streak, min_cycles, stable_required, flow_enabled\n",
        "  integer :: converged, nh3_idx, stable_streak, min_cycles, stable_required\n",
        "flow flag declaration",
    )
    text = replace_once(text, "  tau_res = 0.0d0\n", "", "flow default")
    text = replace_once(
        text,
        "  if (iargc() .ge. 10) then; call getarg(10, arg); read(arg, *) tau_res; end if\n",
        "",
        "flow argument",
    )
    text = replace_once(
        text,
        "  t_period = 1.0d0/freq\n  t_on  = duty * t_period\n  t_off = t_period - t_on\n  n_sub_on  = 12\n  n_sub_off = 8\n",
        "  t_period = 1.0d0/freq\n  t_on  = duty * t_period\n  t_off = t_period - t_on\n"
        "  n_sub_on  = 12\n  n_sub_off = 8\n"
        "  if (iargc() .ge. 10) then; call getarg(10, arg); read(arg, *) n_sub_on; end if\n"
        "  if (iargc() .ge. 11) then; call getarg(11, arg); read(arg, *) n_sub_off; end if\n"
        "  if (n_sub_on .lt. 2 .or. n_sub_off .lt. 2) stop 'n_sub_on and n_sub_off must be >= 2'\n",
        "substep configuration",
    )
    text = replace_once(
        text,
        "  feed_density = density\n  flow_enabled = 0\n  if (tau_res .gt. 0.0d0) flow_enabled = 1\n  if (flow_enabled .eq. 1) call ZDPlasKin_set_cstr_flow(tau_res, feed_density)\n",
        "",
        "flow setup",
    )
    text = replace_once(
        text,
        "  write(*,*) 'flow: enabled=', flow_enabled, ' tau_res_s=', tau_res\n"
        "  write(*,*) 'flow integration: coupled CSTR source in ZDPlasKin RHS; chemistry substeps on=', n_sub_on, ' off=', n_sub_off\n",
        "  write(*,*) 'model: closed 0D pure gas; no CSTR flow and no active surface reactions'\n"
        "  write(*,*) 'chemistry substeps on=', n_sub_on, ' off=', n_sub_off\n",
        "flow logging",
    )
    text = replace_once(
        text,
        "  write(uc,'(A)') 'cycle,t_end_s,NH3_start,NH3_after_on,NH3_end,E_on_Jcm3,E_off_Jcm3,dNH3_on,dNH3_off,rel_state_max,rel_dNH3_cycle,rel_energy_cycle,stable_streak,tau_res_s'\n",
        "  write(uc,'(A)') 'cycle,t_end_s,NH3_start,NH3_after_on,NH3_end,E_on_Jcm3,E_off_Jcm3,dNH3_on,dNH3_off,rel_state_max,rel_dNH3_cycle,rel_energy_cycle,stable_streak'\n",
        "cycle header",
    )
    text = replace_once(
        text,
        "      ! Periodic steady state requires zero net NH3 accumulation per cycle.\n",
        "      ! This closed 0D calculation reports a cycle-to-cycle diagnostic only.\n",
        "periodic comment",
    )
    text = replace_once(
        text,
        "    write(uc,'(I6,11(\",\",ES13.5),\",\",I6,\",\",ES13.5)') k, time, nh3_start, nh3_mid, nh3_end, e_on, e_off, &\n"
        "          dnh3_on, dnh3_off, rel_state_max, rel_dnh3, rel_energy, stable_streak, tau_res\n",
        "    write(uc,'(I6,11(\",\",ES13.5),\",\",I6)') k, time, nh3_start, nh3_mid, nh3_end, e_on, e_off, &\n"
        "          dnh3_on, dnh3_off, rel_state_max, rel_dnh3, rel_energy, stable_streak\n",
        "cycle output",
    )
    text = replace_once(
        text,
        "    if (stable_streak .ge. stable_required) then\n      converged = 1\n      exit\n    end if\n",
        "    if (stable_streak .ge. stable_required) converged = 1\n",
        "early periodic exit",
    )
    text = replace_once(
        text,
        "    ! Chemistry and CSTR source terms are integrated together in ZDPlasKin RHS.\n",
        "    ! Closed 0D gas-phase chemistry is integrated in the ZDPlasKin RHS.\n",
        "phase integration comment",
    )
    forbidden = ("ZDPlasKin_set_cstr_flow", "tau_res", "feed_density", "flow_enabled")
    remaining = [token for token in forbidden if token in text]
    if remaining:
        raise RuntimeError(f"Closed 0D driver still contains forbidden flow token(s): {remaining}")
    return text


def make_cstr_0d_driver() -> str:
    """Render a pulsed 0D CSTR driver with flow retained in the RHS."""
    sys.path.insert(0, str(TOOL_DIR))
    import zdp_gui

    species = zdp_gui.parse_kinet_species(REFERENCE_KINET)
    text = zdp_gui.render_main_auto_pulse(
        composition=[("N2", PARAMETERS["x_N2"]), ("H2", PARAMETERS["x_H2"])],
        en_on=PARAMETERS["EN_on_Td"],
        en_off=PARAMETERS["EN_off_Td"],
        freq=PARAMETERS["frequency_Hz"],
        duty=PARAMETERS["duty_cycle"],
        cycles=PARAMETERS["cycles"],
        tg=PARAMETERS["gas_temperature_K"],
        ne=PARAMETERS["electron_density_cm3"],
        species=species,
        output_opts={"species": True, "te": True, "rates_t": False, "rates": False},
    )
    text = replace_once(
        text,
        "  t_period = 1.0d0/freq\n  t_on  = duty * t_period\n  t_off = t_period - t_on\n  n_sub_on  = 12\n  n_sub_off = 8\n",
        "  t_period = 1.0d0/freq\n  t_on  = duty * t_period\n  t_off = t_period - t_on\n"
        "  n_sub_on  = 12\n  n_sub_off = 8\n"
        "  if (iargc() .ge. 11) then; call getarg(11, arg); read(arg, *) n_sub_on; end if\n"
        "  if (iargc() .ge. 12) then; call getarg(12, arg); read(arg, *) n_sub_off; end if\n"
        "  if (n_sub_on .lt. 2 .or. n_sub_off .lt. 2) stop 'n_sub_on and n_sub_off must be >= 2'\n",
        "CSTR substep configuration",
    )
    required = ("ZDPlasKin_set_cstr_flow", "tau_res", "feed_density", "flow_enabled")
    missing = [token for token in required if token not in text]
    if missing:
        raise RuntimeError(f"CSTR driver is missing required flow token(s): {missing}")
    return text


def normalized_float(value: str) -> float:
    normalized = re.sub(
        r"^([+-]?(?:\d+\.?\d*|\.\d+))([+-]\d{2,3})$", r"\1E\2", value.strip()
    )
    return float(normalized)


def validate_series(path: Path) -> dict:
    if not path.is_file():
        return {"accepted": False, "reason": "missing pulse-series CSV"}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected_rows = 1 + 2 * PARAMETERS["cycles"]
    if len(rows) != expected_rows:
        return {"accepted": False, "reason": f"expected {expected_rows} rows, found {len(rows)}"}
    phases = [int(row["phase"]) for row in rows]
    expected_phases = [0] + [phase for _ in range(PARAMETERS["cycles"]) for phase in (1, 2)]
    if phases != expected_phases:
        return {"accepted": False, "reason": "unexpected phase sequence"}
    final_time = normalized_float(rows[-1]["time_s"])
    if not math.isclose(final_time, PARAMETERS["total_time_s"], rel_tol=1e-9, abs_tol=1e-12):
        return {"accepted": False, "reason": f"final time {final_time} s is not 1 ms"}
    on_fields = [normalized_float(row["EN_Td"]) for row in rows if row["phase"] == "1"]
    off_fields = [normalized_float(row["EN_Td"]) for row in rows if row["phase"] == "2"]
    if not all(math.isclose(value, PARAMETERS["EN_on_Td"], abs_tol=1e-8) for value in on_fields):
        return {"accepted": False, "reason": "on-phase E/N is not 140 Td"}
    if not all(math.isclose(value, PARAMETERS["EN_off_Td"], abs_tol=1e-8) for value in off_fields):
        return {"accepted": False, "reason": "off-phase E/N is not 0 Td"}
    min_density = math.inf
    for row in rows:
        for key, value in row.items():
            if key in {"time_s", "phase", "Te_eV", "EN_Td", "Ptot"} or value in (None, ""):
                continue
            number = normalized_float(value)
            if not math.isfinite(number):
                return {"accepted": False, "reason": f"non-finite value in {key}"}
            min_density = min(min_density, number)
    if min_density < -1e-9:
        return {"accepted": False, "reason": f"negative density detected: {min_density}"}
    return {
        "accepted": True,
        "rows": len(rows),
        "final_time_s": final_time,
        "minimum_density_cm3": min_density,
        "NH3_final_cm3": normalized_float(rows[-1].get("NH3", "0")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    case_dir = output_root / CASE_NAME
    build_dir = case_dir / "build"
    if case_dir.exists():
        raise SystemExit(f"Refusing to overwrite existing case directory: {case_dir}")
    for path in (TOOL_DIR / "zdp_gui.py", TOOL_DIR / "zdp_runtime.py", SOURCE_BUILD / "kinet.inp", REFERENCE_KINET):
        require_file(path)

    case_dir.mkdir(parents=True)
    build_dir.mkdir()
    copy_runtime_files(build_dir)
    shutil.copy2(REFERENCE_KINET, build_dir / "kinet.inp")
    driver_path = build_dir / "main_auto_pulse.F90"
    driver_path.write_text(make_closed_0d_driver(), encoding="utf-8", newline="\n")

    source_hash = sha256(SOURCE_BUILD / "kinet.inp")
    reference_hash = sha256(REFERENCE_KINET)
    if source_hash != reference_hash:
        raise RuntimeError("Pulse and CSTR kinetic inputs differ; refusing an unverified mechanism reuse")
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "parameters": PARAMETERS,
        "model_checks": {
            "cstr_flow_call_present": False,
            "surface_reactions_active": False,
            "full_requested_horizon_executed": True,
        },
        "provenance": {
            "reference_cstr_kinet": str(REFERENCE_KINET),
            "source_pulse_build": str(SOURCE_BUILD),
            "kinet_sha256": reference_hash,
            "driver_sha256": sha256(driver_path),
        },
    }
    (case_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    sys.path.insert(0, str(TOOL_DIR))
    import zdp_runtime

    log_lines: list[str] = []

    def log(message: object) -> None:
        line = str(message)
        log_lines.append(line)
        print(line, flush=True)

    rc = zdp_runtime.build(build_dir, mode="full", log_cb=log)
    if rc:
        (case_dir / "build.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
        raise SystemExit(rc)
    run_params = {
        "en": str(PARAMETERS["EN_on_Td"]),
        "tg": str(PARAMETERS["gas_temperature_K"]),
        "en_off": str(PARAMETERS["EN_off_Td"]),
        "freq": str(PARAMETERS["frequency_Hz"]),
        "duty": str(PARAMETERS["duty_cycle"]),
        "cycles": str(PARAMETERS["cycles"]),
        "tag": "baseline",
        "out_rel": "results",
        "atol": str(PARAMETERS["atol"]),
        "rtol": str(PARAMETERS["rtol"]),
        "pulse_enabled": True,
    }
    rc = zdp_runtime.run(build_dir, run_params, log_cb=log)
    (case_dir / "build_and_run.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    series_path = build_dir / "results" / "pulse_series_baseline.csv"
    validation = validate_series(series_path) if rc == 0 else {"accepted": False, "reason": f"runtime exit code {rc}"}
    status = {"return_code": rc, "validation": validation}
    (case_dir / "run_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"case_dir": str(case_dir), **status}, ensure_ascii=False))
    return 0 if rc == 0 and validation["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
