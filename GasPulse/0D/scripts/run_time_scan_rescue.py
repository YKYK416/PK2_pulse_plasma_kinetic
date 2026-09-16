"""Numerically robust closed-0D square-wave rerun for one requested horizon.

This tool creates a fresh build and result directory for each horizon.  It
does not alter the baseline build or the interrupted ``time_scan`` outputs.
The chemistry, waveform, gas composition, and electron-density setting remain
identical to the accepted 1 ms baseline; only solver controls are changed.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


CASE_DIR = Path(
    r"F:\Codex\PK2_pulse\GasPulse\0D"
    r"\squarewave_T300K_N2-0p1_H2-0p9_EN140Td_f10kHz_d50"
)
SCRIPT_DIR = Path(__file__).resolve().parent
BASELINE_SCRIPT = SCRIPT_DIR / "run_square_wave_0d.py"
TOOL_DIR = Path(r"F:\Codex\PK1\Hong\工具脚本")
RESCUE_ROOT = CASE_DIR / "time_scan_rescue_20260912"

ATOL_CM3 = 1.0e8
RTOL = 1.0e-4
MXSTEP = 500000
N_SUB_ON = 48
N_SUB_OFF = 32
TIMEOUT_S = 21600


def load_baseline_module():
    spec = importlib.util.spec_from_file_location("square_wave_0d", BASELINE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load baseline driver generator: {BASELINE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected exactly one {label} anchor, found {count}")
    return text.replace(old, new, 1)


def patch_mxstep_interface(module_path: Path) -> None:
    """Expose MXSTEP in the generated ZDPlasKin configuration wrapper only."""
    text = module_path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "subroutine ZDPlasKin_set_config(ATOL,RTOL,SILENCE_MODE,STAT_ACCUM,QTPLASKIN_SAVE,BOLSIG_EE_FRAC,BOLSIG_IGNORE_GAS_TEMPERATURE)",
        "subroutine ZDPlasKin_set_config(ATOL,RTOL,SILENCE_MODE,STAT_ACCUM,QTPLASKIN_SAVE,BOLSIG_EE_FRAC,BOLSIG_IGNORE_GAS_TEMPERATURE,MXSTEP)",
        "ZDPlasKin configuration interface",
    )
    text = replace_once(
        text,
        "  double precision, optional, intent(in) :: ATOL, RTOL, BOLSIG_EE_FRAC\n",
        "  double precision, optional, intent(in) :: ATOL, RTOL, BOLSIG_EE_FRAC\n"
        "  integer, optional, intent(in) :: MXSTEP\n",
        "MXSTEP declaration",
    )
    text = replace_once(
        text,
        "                                          dense_j=.true.,user_supplied_jacobian=.true., &\n"
        "                                          constrained=bounded_components(:),clower=dens_loc(:,0),cupper=dens_loc(:,1))",
        "                                          dense_j=.true.,user_supplied_jacobian=.true.,mxstep=MXSTEP, &\n"
        "                                          constrained=bounded_components(:),clower=dens_loc(:,0),cupper=dens_loc(:,1))",
        "DVODE MXSTEP option",
    )
    module_path.write_text(text, encoding="utf-8", newline="\n")


def patch_driver_config(driver_path: Path) -> None:
    text = driver_path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "  call ZDPlasKin_set_config(ATOL=atol_in, RTOL=rtol_in)\n",
        f"  call ZDPlasKin_set_config(ATOL=atol_in, RTOL=rtol_in, MXSTEP={MXSTEP})\n",
        "solver configuration call",
    )
    driver_path.write_text(text, encoding="utf-8", newline="\n")


def compile_patched_build(build_dir: Path, runtime) -> None:
    """Recompile only the patched module and driver after a clean full build."""
    gfortran_dir = runtime.resolve_gfortran_dir()
    if not gfortran_dir:
        raise RuntimeError("Cannot locate gfortran")
    gfortran = gfortran_dir / "gfortran.exe"
    env = runtime._runtime_env(gfortran_dir)
    module_name = "zdplaskin_m.F90"
    driver_name = "main_auto_pulse.F90"
    compile_cmd = [str(gfortran), *runtime.FFLAGS, "-c", module_name, driver_name]
    link_cmd = [
        str(gfortran), "-O2", "-o", "main_auto_pulse.exe", "main_auto_pulse.o",
        "zdplaskin_m.o", "dvode_f90_m.o", "-L.", runtime._link_library_arg(build_dir),
        "-static-libgfortran", "-static-libgcc",
    ]
    for command in (compile_cmd, link_cmd):
        proc = subprocess.run(command, cwd=build_dir, env=env, text=True, capture_output=True)
        if proc.returncode:
            raise RuntimeError(
                f"Patched compilation failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
            )


def parse_float(value: str) -> float:
    normalized = re.sub(
        r"^([+-]?(?:\d+\.?\d*|\.\d+))([+-]\d{2,3})$", r"\1E\2", value.strip()
    )
    return float(normalized)


def validate_series(path: Path, cycles: int, target_time_s: float) -> dict:
    if not path.is_file():
        return {"accepted": False, "reason": "missing pulse-series CSV"}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected_rows = 1 + 2 * cycles
    if len(rows) != expected_rows:
        return {"accepted": False, "reason": f"expected {expected_rows} rows, found {len(rows)}"}
    phases = [int(row["phase"]) for row in rows]
    if phases != [0] + [value for _ in range(cycles) for value in (1, 2)]:
        return {"accepted": False, "reason": "unexpected on/off phase sequence"}
    final_time_s = parse_float(rows[-1]["time_s"])
    if not math.isclose(final_time_s, target_time_s, rel_tol=1e-9, abs_tol=1e-12):
        return {"accepted": False, "reason": f"final time {final_time_s} s differs from target"}
    for row in rows:
        if row["phase"] == "1" and not math.isclose(parse_float(row["EN_Td"]), 140.0, abs_tol=1e-9):
            return {"accepted": False, "reason": "incorrect on-phase E/N"}
        if row["phase"] == "2" and not math.isclose(parse_float(row["EN_Td"]), 0.0, abs_tol=1e-9):
            return {"accepted": False, "reason": "incorrect off-phase E/N"}
        for key, value in row.items():
            if key in {"time_s", "phase", "Te_eV", "EN_Td", "Ptot"} or value in (None, ""):
                continue
            numeric = parse_float(value)
            if not math.isfinite(numeric) or numeric < -1e-9:
                return {"accepted": False, "reason": f"invalid density in {key}"}
    return {
        "accepted": True,
        "rows": len(rows),
        "final_time_s": final_time_s,
        "NH3_final_cm3": parse_float(rows[-1]["NH3"]),
    }


def run_case(build_dir: Path, result_dir: Path, cycles: int, tag: str, runtime) -> tuple[int, str, str]:
    result_dir.mkdir(parents=True)
    for source in build_dir.glob("*.DAT"):
        shutil.copy2(source, result_dir / source.name)
    shutil.copy2(build_dir / "bolsigdb.dat", result_dir / "bolsigdb.dat")
    gfortran_dir = runtime.resolve_gfortran_dir()
    env = runtime._runtime_env(gfortran_dir)
    command = [
        str(build_dir / "main_auto_pulse.exe"), "300.0", "140.0", "0.0", "10000.0", "0.5",
        str(cycles), tag, f"{ATOL_CM3:g}", f"{RTOL:g}", str(N_SUB_ON), str(N_SUB_OFF),
    ]
    try:
        proc = subprocess.run(command, cwd=result_dir, env=env, text=True, capture_output=True, timeout=TIMEOUT_S)
        # Windows may report no captured text for a successfully completed child.
        # Normalize that case so result logging and manifest generation complete.
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return 124, stdout, stderr + f"\nTimeout after {TIMEOUT_S} s"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horizon-ms", type=float, required=True, choices=(10.0, 50.0, 100.0, 200.0))
    args = parser.parse_args()
    cycles = int(round(args.horizon_ms * 10.0))
    target_time_s = args.horizon_ms * 1.0e-3
    horizon_name = f"{args.horizon_ms:g}ms"
    root = RESCUE_ROOT / horizon_name / "attempt_02"
    build_dir = root / "build"
    result_dir = root / "results"
    if root.exists():
        raise SystemExit(f"Refusing to overwrite existing rescue directory: {root}")

    baseline = load_baseline_module()
    sys.path.insert(0, str(TOOL_DIR))
    import zdp_runtime

    root.mkdir(parents=True)
    build_dir.mkdir()
    baseline.copy_runtime_files(build_dir)
    shutil.copy2(baseline.REFERENCE_KINET, build_dir / "kinet.inp")
    driver_path = build_dir / "main_auto_pulse.F90"
    driver_path.write_text(baseline.make_closed_0d_driver(), encoding="utf-8", newline="\n")

    log: list[str] = []
    def build_log(message: object) -> None:
        line = str(message)
        log.append(line)
        print(line, flush=True)

    rc = zdp_runtime.build(build_dir, mode="full", log_cb=build_log)
    if rc:
        raise SystemExit(rc)
    module_path = build_dir / "zdplaskin_m.F90"
    patch_mxstep_interface(module_path)
    patch_driver_config(driver_path)
    compile_patched_build(build_dir, zdp_runtime)

    tag = f"rescue_t{args.horizon_ms:g}ms"
    started_at = datetime.now().isoformat(timespec="seconds")
    rc, stdout, stderr = run_case(build_dir, result_dir, cycles, tag, zdp_runtime)
    (root / "build.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    (result_dir / "console.log").write_text(stdout, encoding="utf-8", errors="replace")
    (result_dir / "stderr.log").write_text(stderr, encoding="utf-8", errors="replace")
    series = result_dir / f"pulse_series_{tag}.csv"
    validation = validate_series(series, cycles, target_time_s) if rc == 0 else {
        "accepted": False, "reason": f"run returned {rc}"
    }
    manifest = {
        "created_at": started_at,
        "parameters": {
            **baseline.PARAMETERS,
            "cycles": cycles,
            "total_time_s": target_time_s,
        },
        "solver_rescue": {
            "ATOL_cm3": ATOL_CM3,
            "RTOL": RTOL,
            "MXSTEP": MXSTEP,
            "n_sub_on": N_SUB_ON,
            "n_sub_off": N_SUB_OFF,
        },
        "model_boundary": "closed 0D pure gas; no CSTR flow; all surface reactions remain disabled",
        "provenance": {
            "kinet_sha256": sha256(build_dir / "kinet.inp"),
            "driver_sha256": sha256(driver_path),
            "module_sha256": sha256(module_path),
        },
        "return_code": rc,
        "validation": validation,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"rescue_root": str(root), "return_code": rc, "validation": validation}, ensure_ascii=False))
    return 0 if rc == 0 and validation["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
