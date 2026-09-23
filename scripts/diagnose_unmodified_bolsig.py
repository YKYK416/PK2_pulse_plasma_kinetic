"""Test an unmodified LXCat source copied verbatim as ``bolsigdb.dat``.

This diagnostic intentionally bypasses the normal BOLSIG acceptance gate only
to observe vendor preprocessor/compiler/BOLSIG behaviour.  It is never a
scientific Gas1 result: the manifest records the failed audit and the exact
source/staged SHA-256 values.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pk2_pulse.bolsig import audit_database, generate_detailed_balance_database, sha256  # noqa: E402
from pk2_pulse.build import CaseBuild, preprocess_and_compile  # noqa: E402
from pk2_pulse.config import load_pulse_case  # noqa: E402
from pk2_pulse.driver import render_closed_0d_pulse_driver  # noqa: E402
from pk2_pulse.mechanism import gas_species_names, stage_gas_phase_mechanism  # noqa: E402
from pk2_pulse.runtime import discover_runtime, stage_runtime  # noqa: E402


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        type=Path,
        default=PROJECT_ROOT / "configs" / "gas_phase" / "closed_0d" / "gas1_T400K_N2-0p5_H2-0p5_P1atm.yaml",
    )
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--cross-sections", type=Path)
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument(
        "--append-detailed-balance-inverses",
        action="store_true",
        help="Append explicit inverse superelastic blocks; retain every source forward record verbatim.",
    )
    args = parser.parse_args()
    if args.timeout_s <= 0:
        parser.error("--timeout-s must be positive")

    case = load_pulse_case(args.case)
    runtime = discover_runtime(PROJECT_ROOT, args.runtime_dir, args.cross_sections or case.cross_section_source)
    mechanism = PROJECT_ROOT / "mechanisms" / case.mechanism / "kinet.inp"
    audit = audit_database(mechanism, runtime.cross_section_database)
    run_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = (args.output_root or PROJECT_ROOT / "run_data" / "diagnostics" / f"gas1_unmodified_bolsig_{run_stamp}").resolve()
    if root.exists():
        raise FileExistsError(f"Refusing to overwrite diagnostic output: {root}")
    build_dir = root / "build"
    result_dir = root / "results" / "1ms"
    root.mkdir(parents=True)
    build_dir.mkdir()
    diagnostic: dict[str, object] = {
        "scientific_status": "diagnostic_only_not_a_gas1_result",
        "purpose": (
            "test vendor behaviour with explicit detailed-balance inverse blocks appended to an unchanged forward source"
            if args.append_detailed_balance_inverses
            else "test vendor behaviour with an unmodified source copied verbatim as bolsigdb.dat"
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "case": str(case.config_path),
        "case_id": case.id,
        "mechanism": str(mechanism),
        "mechanism_sha256": sha256(mechanism),
        "cross_section_source": str(runtime.cross_section_database),
        "cross_section_source_sha256": sha256(runtime.cross_section_database),
        "bolsig_audit_before_test": audit.as_dict(),
        "forward_excitation_records_modified": False,
    }
    try:
        stage_runtime(runtime, build_dir)
        diagnostic_species = gas_species_names(mechanism)
        diagnostic["mechanism_transform"] = stage_gas_phase_mechanism(
            mechanism, build_dir, disable_wall_relaxation=case.wall_relaxation == "disabled"
        )
        staged_database = build_dir / "bolsigdb.dat"
        if args.append_detailed_balance_inverses:
            diagnostic["database_transform"] = generate_detailed_balance_database(
                runtime.cross_section_database, staged_database, upper_to_lower_weight_ratio=1.0
            )
            diagnostic["bolsig_audit_after_transform"] = audit_database(mechanism, staged_database).as_dict()
            if not diagnostic["bolsig_audit_after_transform"]["accepted"]:
                raise RuntimeError("Derived database still fails the BOLSIG audit")
        else:
            shutil.copy2(runtime.cross_section_database, staged_database)
            if sha256(staged_database) != sha256(runtime.cross_section_database):
                raise RuntimeError("Verbatim bolsigdb.dat copy hash mismatch")
        driver_path = build_dir / "gas1_closed_0d_pulse.F90"
        driver_path.write_text(render_closed_0d_pulse_driver(case, diagnostic_species), encoding="utf-8", newline="\n")
        diagnostic.update({
            "staged_database": str(staged_database),
            "staged_database_sha256": sha256(staged_database),
            "driver": str(driver_path),
            "driver_sha256": sha256(driver_path),
        })
        build = CaseBuild(root=root, build_dir=build_dir, results_dir=root / "results")
        executable = preprocess_and_compile(build, runtime)
        diagnostic["preprocess_compile"] = {"accepted": True, "executable": str(executable)}
    except Exception as exc:
        diagnostic["preprocess_compile"] = {"accepted": False, "error": str(exc)}
        write_json(root / "diagnostic_manifest.json", diagnostic)
        print(json.dumps({"root": str(root), "preprocess_compile": diagnostic["preprocess_compile"]}, ensure_ascii=False))
        return 2

    result_dir.mkdir(parents=True)
    # BOLSIG reads its database from the worker current directory.  This copy
    # remains byte-identical to the source and is isolated from other workers.
    shutil.copy2(build_dir / "bolsigdb.dat", result_dir / "bolsigdb.dat")
    for source in build_dir.glob("*.DAT"):
        shutil.copy2(source, result_dir / source.name)
    csv_path = result_dir / "pulse_summary.csv"
    try:
        process = subprocess.run(
            [str(executable), str(case.cycles_for_horizon(1.0)), csv_path.name],
            cwd=result_dir,
            text=True,
            capture_output=True,
            timeout=args.timeout_s,
        )
        return_code = process.returncode
        stdout, stderr = process.stdout or "", process.stderr or ""
    except subprocess.TimeoutExpired as exc:
        return_code = 124
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = (exc.stderr if isinstance(exc.stderr, str) else "") + f"\nTimeout after {args.timeout_s:g} s"
    (result_dir / "console.log").write_text(stdout, encoding="utf-8", errors="replace")
    (result_dir / "stderr.log").write_text(stderr, encoding="utf-8", errors="replace")
    diagnostic["solver_smoke_test"] = {
        "horizon_ms": 1.0,
        "cycles": case.cycles_for_horizon(1.0),
        "return_code": return_code,
        "phase_csv_created": csv_path.is_file(),
        "result_dir": str(result_dir),
    }
    write_json(root / "diagnostic_manifest.json", diagnostic)
    print(json.dumps({"root": str(root), "solver_smoke_test": diagnostic["solver_smoke_test"]}, ensure_ascii=False))
    return 0 if return_code == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
