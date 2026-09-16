"""Build and run an isolated 200 ms, tau=50 ms pulsed 0D Hong CSTR case."""
from __future__ import annotations

import csv
import json
import math
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import run_square_wave_0d as baseline
import run_time_scan_rescue as rescue


TAU_RES_S = 50.0e-3
CYCLES = 2000
TARGET_TIME_S = 200.0e-3
ATOL_CM3 = 1.0e8
RTOL = 1.0e-4
N_SUB_ON = 48
N_SUB_OFF = 32
TIMEOUT_S = 21600
CASE_DIR = baseline.OUTPUT_ROOT / "squarewave_cstr_tau50ms_T300K_N2-0p1_H2-0p9_EN140Td_f10kHz_d50"
ATTEMPT_ROOT = CASE_DIR / "time_scan" / "200ms" / "attempt_02"


def normalized_float(value: str) -> float:
    return baseline.normalized_float(value)


def validate_series(path: Path) -> dict:
    if not path.is_file():
        return {"accepted": False, "reason": "missing pulse-series CSV"}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected_rows = 1 + 2 * CYCLES
    if len(rows) != expected_rows:
        return {"accepted": False, "reason": f"expected {expected_rows} rows, found {len(rows)}"}
    expected_phases = [0] + [phase for _ in range(CYCLES) for phase in (1, 2)]
    if [int(row["phase"]) for row in rows] != expected_phases:
        return {"accepted": False, "reason": "unexpected phase sequence"}
    final_time = normalized_float(rows[-1]["time_s"])
    if not math.isclose(final_time, TARGET_TIME_S, rel_tol=1.0e-9, abs_tol=1.0e-12):
        return {"accepted": False, "reason": f"final time {final_time} s differs from {TARGET_TIME_S} s"}
    for row in rows:
        for name, value in row.items():
            if name in {"time_s", "phase"}:
                continue
            numeric = normalized_float(value)
            if not math.isfinite(numeric) or numeric < 0.0:
                return {"accepted": False, "reason": f"invalid {name} at t={row['time_s']}"}
    return {
        "accepted": True,
        "rows": len(rows),
        "final_time_s": final_time,
        "NH3_final_cm3": normalized_float(rows[-1]["NH3"]),
    }


def validate_cycles(path: Path) -> dict:
    if not path.is_file():
        return {"accepted": False, "reason": "missing pulse-cycles CSV"}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != CYCLES:
        return {"accepted": False, "reason": f"expected {CYCLES} cycle rows, found {len(rows)}"}
    tau_values = [normalized_float(row["tau_res_s"]) for row in rows]
    if any(not math.isclose(value, TAU_RES_S, rel_tol=1.0e-12, abs_tol=1.0e-15) for value in tau_values):
        return {"accepted": False, "reason": "tau_res_s output does not equal 50 ms"}
    return {"accepted": True, "rows": len(rows), "tau_res_s": tau_values[-1]}


def run_case(build_dir: Path, result_dir: Path, tag: str, runtime: object) -> tuple[int, str, str]:
    gfortran_dir = runtime.resolve_gfortran_dir()
    env = runtime._runtime_env(gfortran_dir)
    command = [
        str(build_dir / "main_auto_pulse.exe"), "300.0", "140.0", "0.0", "10000.0", "0.5",
        str(CYCLES), tag, f"{ATOL_CM3:g}", f"{RTOL:g}", f"{TAU_RES_S:g}",
        str(N_SUB_ON), str(N_SUB_OFF),
    ]
    try:
        proc = subprocess.run(command, cwd=result_dir, env=env, capture_output=True, timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or b"").decode("utf-8", errors="replace")
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace")
        return 124, stdout, stderr + f"\nTimeout after {TIMEOUT_S} s"
    return (
        proc.returncode,
        (proc.stdout or b"").decode("utf-8", errors="replace"),
        (proc.stderr or b"").decode("utf-8", errors="replace"),
    )


def main() -> int:
    if ATTEMPT_ROOT.exists():
        raise SystemExit(f"Refusing to overwrite existing CSTR result directory: {ATTEMPT_ROOT}")

    sys.path.insert(0, str(baseline.TOOL_DIR))
    import zdp_runtime

    build_dir = ATTEMPT_ROOT / "build"
    result_dir = ATTEMPT_ROOT / "results"
    ATTEMPT_ROOT.mkdir(parents=True)
    build_dir.mkdir()
    result_dir.mkdir()
    baseline.copy_runtime_files(build_dir)
    shutil.copy2(baseline.REFERENCE_KINET, build_dir / "kinet.inp")
    driver_path = build_dir / "main_auto_pulse.F90"
    driver_path.write_text(baseline.make_cstr_0d_driver(), encoding="utf-8", newline="\n")

    build_log: list[str] = []
    def record(message: object) -> None:
        line = str(message)
        build_log.append(line)
        print(line, flush=True)

    rc = zdp_runtime.build(build_dir, mode="full", log_cb=record)
    if rc:
        return rc
    module_path = build_dir / "zdplaskin_m.F90"
    rescue.patch_mxstep_interface(module_path)
    rescue.patch_driver_config(driver_path)
    rescue.compile_patched_build(build_dir, zdp_runtime)

    driver_text = driver_path.read_text(encoding="utf-8")
    module_text = module_path.read_text(encoding="utf-8")
    required_driver = ("ZDPlasKin_set_cstr_flow", "tau_res", "feed_density", "flow_enabled")
    if any(token not in driver_text for token in required_driver):
        raise RuntimeError("CSTR flow call was not retained in the generated driver")
    if "ZDP_CSTR_FLOW_PATCH_V1" not in module_text:
        raise RuntimeError("CSTR RHS patch was not applied to the generated module")

    tag = "cstr_tau50ms_t200ms"
    started_at = datetime.now().isoformat(timespec="seconds")
    rc, stdout, stderr = run_case(build_dir, result_dir, tag, zdp_runtime)
    (ATTEMPT_ROOT / "build.log").write_text("\n".join(build_log) + "\n", encoding="utf-8")
    (result_dir / "console.log").write_text(stdout, encoding="utf-8", errors="replace")
    (result_dir / "stderr.log").write_text(stderr, encoding="utf-8", errors="replace")
    series = result_dir / f"pulse_series_{tag}.csv"
    cycles = result_dir / f"pulse_cycles_{tag}.csv"
    series_validation = validate_series(series) if rc == 0 else {"accepted": False, "reason": f"run returned {rc}"}
    cycles_validation = validate_cycles(cycles) if rc == 0 else {"accepted": False, "reason": f"run returned {rc}"}
    manifest = {
        "created_at": started_at,
        "parameters": {
            **baseline.PARAMETERS,
            "model": "0D pure-gas pulsed CSTR; gas heavy-species inlet/outlet; surface reactions disabled",
            "tau_res_s": TAU_RES_S,
            "cycles": CYCLES,
            "total_time_s": TARGET_TIME_S,
            "duty_cycle": 0.5,
            "pulse_period_s": 1.0e-4,
            "t_on_s": 5.0e-5,
            "t_off_s": 5.0e-5,
        },
        "solver": {"ATOL_cm3": ATOL_CM3, "RTOL": RTOL, "MXSTEP": rescue.MXSTEP,
                   "n_sub_on": N_SUB_ON, "n_sub_off": N_SUB_OFF},
        "model_boundary": "CSTR source is coupled in the gas heavy-species RHS; fixed electrons and surface states are excluded from flow",
        "provenance": {
            "kinet_sha256": baseline.sha256(build_dir / "kinet.inp"),
            "driver_sha256": baseline.sha256(driver_path),
            "cstr_rhs_patch": "ZDP_CSTR_FLOW_PATCH_V1",
        },
        "return_code": rc,
        "series_validation": series_validation,
        "cycles_validation": cycles_validation,
    }
    (ATTEMPT_ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0 if rc == 0 and series_validation["accepted"] and cycles_validation["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
