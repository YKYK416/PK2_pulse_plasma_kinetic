"""Run the first-stage Gas1 CSTR one-factor operating-condition scan."""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = PROJECT_ROOT / "configs" / "gas_phase" / "cstr"
BASE_CASE_NAME = "gas1_T400K_N2-0p5_H2-0p5_P1atm_tau1ms_positive_unbounded_scan.yaml"


def _slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _case_overrides(label: str, overrides: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    return label, overrides


def build_case_specs() -> list[tuple[str, dict[str, Any]]]:
    """Return the baseline plus one-factor cases around the confirmed point."""
    specs: list[tuple[str, dict[str, Any]]] = [("baseline", {})]
    specs.extend(
        _case_overrides(f"EN{value:g}Td", {"EN_on_Td": float(value)})
        for value in (25.0, 75.0, 100.0)
    )
    specs.extend(
        _case_overrides(f"tau{value:g}ms", {"reactor": {"residence_time_s": value * 1.0e-3}})
        for value in (0.1, 0.3, 3.0, 10.0)
    )
    specs.extend(
        _case_overrides(
            f"P{value:g}atm",
            {
                "initial_state": {"pressure_Pa": value * 101325.0},
                "feed": {"pressure_Pa": value * 101325.0},
            },
        )
        for value in (0.5, 2.0)
    )
    specs.extend(
        _case_overrides(
            f"T{value:g}K",
            {
                "initial_state": {"gas_temperature_K": value},
                "feed": {"gas_temperature_K": value},
            },
        )
        for value in (300.0, 500.0)
    )
    specs.extend(
        _case_overrides(
            f"xH2{value:g}",
            {
                "initial_state": {"mole_fractions": {"N2": 1.0 - value, "H2": value}},
                "feed": {"mole_fractions": {"N2": 1.0 - value, "H2": value}},
            },
        )
        for value in (0.25, 0.75)
    )
    specs.extend(
        _case_overrides(
            f"ne{value:.3e}",
            {
                "initial_state": {"electron_density_cm3": value},
                "feed": {"electron_density_cm3": value},
            },
        )
        for value in (1.0e7, 1.0e9)
    )
    specs.extend(
        _case_overrides(f"f{value:g}kHz", {"frequency_Hz": value * 1.0e3})
        for value in (1.0, 100.0)
    )
    specs.extend(
        _case_overrides(f"duty{value:g}pct", {"duty_cycle": value})
        for value in (0.1, 0.5)
    )
    return specs


def build_adaptive_case_specs() -> list[tuple[str, dict[str, Any]]]:
    """Return an adaptive one-factor refinement around the confirmed point."""
    specs: list[tuple[str, dict[str, Any]]] = [("baseline", {})]
    specs.extend(
        _case_overrides(f"EN{value:g}Td", {"EN_on_Td": float(value)})
        for value in (25.0, 30.0, 35.0, 40.0, 45.0, 60.0, 70.0, 75.0, 80.0, 85.0, 100.0)
    )
    specs.extend(
        _case_overrides(f"tau{value:g}ms", {"reactor": {"residence_time_s": value * 1.0e-3}})
        for value in (0.1, 0.15, 0.2, 0.3, 0.5, 0.75, 1.5, 2.0, 3.0, 5.0, 10.0)
    )
    specs.extend(
        _case_overrides(
            f"P{value:g}atm",
            {
                "initial_state": {"pressure_Pa": value * 101325.0},
                "feed": {"pressure_Pa": value * 101325.0},
            },
        )
        for value in (0.5, 0.75, 1.25, 1.5, 2.0)
    )
    specs.extend(
        _case_overrides(
            f"T{value:g}K",
            {
                "initial_state": {"gas_temperature_K": value},
                "feed": {"gas_temperature_K": value},
            },
        )
        for value in (300.0, 325.0, 350.0, 375.0, 425.0, 450.0, 500.0)
    )
    specs.extend(
        _case_overrides(
            f"xH2{value:g}",
            {
                "initial_state": {"mole_fractions": {"N2": 1.0 - value, "H2": value}},
                "feed": {"mole_fractions": {"N2": 1.0 - value, "H2": value}},
            },
        )
        for value in (0.25, 0.35, 0.4, 0.45, 0.55, 0.65, 0.75)
    )
    specs.extend(
        _case_overrides(
            f"ne{value:.3e}",
            {
                "initial_state": {"electron_density_cm3": value},
                "feed": {"electron_density_cm3": value},
            },
        )
        for value in (1.0e7, 3.0e7, 1.0e8, 2.0e8, 3.0e8, 5.0e8, 1.0e9)
    )
    specs.extend(
        _case_overrides(f"f{value:g}kHz", {"frequency_Hz": value * 1.0e3})
        for value in (1.0, 2.0, 5.0, 50.0, 100.0)
    )
    specs.extend(
        _case_overrides(f"duty{value:g}pct", {"duty_cycle": value})
        for value in (0.1, 0.15, 0.25, 0.3, 0.4, 0.5)
    )
    return specs


def build_detailed_case_specs() -> list[tuple[str, dict[str, Any]]]:
    """Return a local one-factor refinement around the most sensitive ranges."""
    specs: list[tuple[str, dict[str, Any]]] = [("baseline", {})]
    specs.extend(
        _case_overrides(f"EN{value:g}Td", {"EN_on_Td": float(value)})
        for value in (45.0, 47.0, 49.0, 51.0, 53.0, 55.0, 57.0, 59.0, 61.0, 63.0, 65.0)
    )
    specs.extend(
        _case_overrides(f"tau{value:g}ms", {"reactor": {"residence_time_s": value * 1.0e-3}})
        for value in (0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0)
    )
    specs.extend(
        _case_overrides(
            f"P{value:g}atm",
            {
                "initial_state": {"pressure_Pa": value * 101325.0},
                "feed": {"pressure_Pa": value * 101325.0},
            },
        )
        for value in (0.75, 0.875, 1.0, 1.125, 1.25, 1.375, 1.5)
    )
    specs.extend(
        _case_overrides(
            f"T{value:g}K",
            {
                "initial_state": {"gas_temperature_K": value},
                "feed": {"gas_temperature_K": value},
            },
        )
        for value in (350.0, 375.0, 400.0, 425.0, 450.0, 475.0, 500.0)
    )
    specs.extend(
        _case_overrides(
            f"xH2{value:g}",
            {
                "initial_state": {"mole_fractions": {"N2": 1.0 - value, "H2": value}},
                "feed": {"mole_fractions": {"N2": 1.0 - value, "H2": value}},
            },
        )
        for value in (0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80)
    )
    specs.extend(
        _case_overrides(
            f"ne{value:.3e}",
            {
                "initial_state": {"electron_density_cm3": value},
                "feed": {"electron_density_cm3": value},
            },
        )
        for value in (1.0e7, 1.5e7, 2.0e7, 3.0e7, 5.0e7, 7.5e7, 1.0e8, 1.17e8, 1.5e8, 2.0e8, 3.0e8, 5.0e8, 7.5e8, 1.0e9)
    )
    specs.extend(
        _case_overrides(f"f{value:g}kHz", {"frequency_Hz": value * 1.0e3})
        for value in (2.0, 5.0, 10.0, 20.0, 50.0, 100.0)
    )
    specs.extend(
        _case_overrides(f"duty{value:g}pct", {"duty_cycle": value})
        for value in (0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5)
    )
    return specs


def build_interaction_case_specs() -> list[tuple[str, dict[str, Any]]]:
    """Return a 5x5 E/N-residence-time interaction grid."""
    specs: list[tuple[str, dict[str, Any]]] = []
    for en_value in (45.0, 50.0, 55.0, 60.0, 65.0):
        for tau_value in (0.3, 0.5, 1.0, 1.5, 2.0):
            specs.append(
                _case_overrides(
                    f"EN{en_value:g}Td_tau{tau_value:g}ms",
                    {
                        "EN_on_Td": en_value,
                        "reactor": {"residence_time_s": tau_value * 1.0e-3},
                    },
                )
            )
    return specs


def build_surface3d_case_specs() -> list[tuple[str, dict[str, Any]]]:
    """Return a compact E/N-residence-time-electron-density response surface."""
    specs: list[tuple[str, dict[str, Any]]] = []
    for en_value in (49.0, 53.0, 57.0):
        for tau_value in (0.5, 1.0, 1.5):
            for ne_value in (1.0e8, 1.17e8, 2.0e8):
                specs.append(
                    _case_overrides(
                        f"EN{en_value:g}Td_tau{tau_value:g}ms_ne{ne_value:.3e}",
                        {
                            "EN_on_Td": en_value,
                            "reactor": {"residence_time_s": tau_value * 1.0e-3},
                            "initial_state": {"electron_density_cm3": ne_value},
                            "feed": {"electron_density_cm3": ne_value},
                        },
                    )
                )
    return specs


def _write_case_config(
    label: str,
    overrides: dict[str, Any],
    *,
    species_tolerance_mode: str,
    n_sub_on: int | None,
    n_sub_off: int | None,
    case_suffix: str,
) -> tuple[str, Path]:
    base_path = CASE_DIR / BASE_CASE_NAME
    case_id = f"gas1-cstr0d-condition-{_slug(label)}{case_suffix}"
    config_path = CASE_DIR / f"{case_id}.yaml"
    data = {
        "schema_version": 1,
        "id": case_id,
        "includes": [BASE_CASE_NAME],
        "run": {
            "horizons_ms": [1000.0],
            "output_every_cycles": 100,
            "timeout_s": 86400.0,
            "solver_time_mode": "phase_local",
            "species_tolerance_mode": species_tolerance_mode,
        },
    }
    if n_sub_on is not None:
        data["n_sub_on"] = n_sub_on
    if n_sub_off is not None:
        data["n_sub_off"] = n_sub_off
    data = _deep_merge(data, overrides)
    data["notes"] = (
        "Gas1 CSTR condition scan/recovery run. "
        f"Diagnostic {species_tolerance_mode} numerical mode; compare with bounded baseline."
    )
    config_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    if not base_path.is_file():
        raise FileNotFoundError(base_path)
    return case_id, config_path


def _run_case(
    case_id: str,
    config_path: Path,
    output_root: Path,
) -> dict[str, Any]:
    case_root = output_root / "cases" / case_id
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "run_pulse_case.py"),
        "--case",
        str(config_path),
        "--append-detailed-balance-inverses",
        "--output-root",
        str(case_root),
        "--max-workers",
        "1",
    ]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    case_root.mkdir(parents=True, exist_ok=True)
    (case_root / "launcher.stdout.log").write_text(completed.stdout or "", encoding="utf-8")
    (case_root / "launcher.stderr.log").write_text(completed.stderr or "", encoding="utf-8")
    result_manifest = case_root / "results" / "1000ms" / "manifest.json"
    summary: dict[str, Any] = {
        "case_id": case_id,
        "config": str(config_path),
        "output_root": str(case_root),
        "launcher_return_code": completed.returncode,
    }
    if result_manifest.is_file():
        result = json.loads(result_manifest.read_text(encoding="utf-8"))
        summary.update(
            {
                "return_code": result.get("return_code"),
                "NH3_final_cm3": result.get("validation", {}).get("NH3_final_cm3"),
                "dvode_warning_count": result.get("dvode_audit", {}).get("warning_count"),
                "solver_error_count": result.get("dvode_audit", {}).get("solver_error_count"),
                "validation_accepted": result.get("validation", {}).get("accepted"),
                "species_validation_accepted": result.get("species_validation", {}).get("accepted"),
                "reaction_rate_validation_accepted": result.get("reaction_rate_validation", {}).get("accepted"),
                "dvode_accepted": result.get("dvode_audit", {}).get("accepted"),
            }
        )
    else:
        summary["failure"] = "1000ms result manifest missing"
    return summary


def _summary_passes(summary: dict[str, Any]) -> bool:
    """Return whether a case is complete and passes every quality gate."""
    return (
        summary.get("launcher_return_code") == 0
        and not summary.get("failure")
        and summary.get("return_code") == 0
        and summary.get("validation_accepted") is True
        and summary.get("species_validation_accepted") is True
        and summary.get("reaction_rate_validation_accepted") is True
        and summary.get("dvode_accepted") is True
        and summary.get("dvode_warning_count") == 0
        and summary.get("solver_error_count") == 0
    )


def _run_batch(
    cases: list[tuple[str, Path]],
    output_root: Path,
    max_workers: int,
    *,
    phase: str,
) -> list[dict[str, Any]]:
    """Run a batch and emit one compact completion record per case."""
    summaries: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(cases))) as executor:
        futures = {
            executor.submit(_run_case, case_id, config_path, output_root): case_id
            for case_id, config_path in cases
        }
        for future in as_completed(futures):
            case_id = futures[future]
            result = future.result()
            result["phase"] = phase
            summaries.append(result)
            print(
                json.dumps(
                    {
                        "phase": phase,
                        "completed": case_id,
                        "NH3_final_cm3": result.get("NH3_final_cm3"),
                        "dvode_warning_count": result.get("dvode_warning_count"),
                        "solver_error_count": result.get("solver_error_count"),
                        "launcher_return_code": result.get("launcher_return_code"),
                        "passed": _summary_passes(result),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    return summaries


def _write_summaries(output_root: Path, summaries: list[dict[str, Any]], stem: str = "summary") -> None:
    """Write JSON and CSV summaries with a stable schema."""
    summaries = sorted(summaries, key=lambda item: item["case_id"])
    (output_root / f"{stem}.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fields = [
        "case_id",
        "config",
        "NH3_final_cm3",
        "dvode_warning_count",
        "solver_error_count",
        "launcher_return_code",
        "return_code",
        "validation_accepted",
        "species_validation_accepted",
        "reaction_rate_validation_accepted",
        "dvode_accepted",
        "failure",
        "phase",
        "retry_of",
        "retry_case_id",
        "retry_output_root",
        "output_root",
    ]
    with (output_root / f"{stem}.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summaries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=("standard", "adaptive", "detailed", "interaction", "surface3d"),
        default="standard",
    )
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--species-tolerance-mode", default="positive_unbounded")
    parser.add_argument("--n-sub-on", type=int)
    parser.add_argument("--n-sub-off", type=int)
    parser.add_argument("--case-suffix", default="")
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry failed cases with the positive radical-floor diagnostic settings and merge the result.",
    )
    parser.add_argument("--retry-max-workers", type=int, default=1)
    parser.add_argument("--retry-species-tolerance-mode", default="positive_radical_floor_unbounded")
    parser.add_argument("--retry-n-sub-on", type=int, default=240)
    parser.add_argument("--retry-n-sub-off", type=int, default=160)
    parser.add_argument("--retry-case-suffix", default="-retry")
    parser.add_argument("--only", nargs="*", help="Restrict the scan to normalized case labels, e.g. en25td tau0-1ms")
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    if args.max_workers < 1:
        parser.error("--max-workers must be at least one")
    if args.retry_max_workers < 1:
        parser.error("--retry-max-workers must be at least one")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = (args.output_root or PROJECT_ROOT / "run_data" / "diagnostics" / f"gas1_condition_scan_{timestamp}").resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    if args.profile == "standard":
        specs = build_case_specs()
    elif args.profile == "adaptive":
        specs = build_adaptive_case_specs()
    elif args.profile == "detailed":
        specs = build_detailed_case_specs()
    elif args.profile == "interaction":
        specs = build_interaction_case_specs()
    else:
        specs = build_surface3d_case_specs()
    if args.only:
        requested = {_slug(value) for value in args.only}
        specs = [(label, overrides) for label, overrides in specs if _slug(label) in requested]
        if not specs:
            parser.error("--only did not match any case labels")
    if args.n_sub_on is not None and args.n_sub_on < 2:
        parser.error("--n-sub-on must be at least two")
    if args.n_sub_off is not None and args.n_sub_off < 2:
        parser.error("--n-sub-off must be at least two")
    if args.retry_n_sub_on < 2:
        parser.error("--retry-n-sub-on must be at least two")
    if args.retry_n_sub_off < 2:
        parser.error("--retry-n-sub-off must be at least two")
    if args.retry_failed and not args.retry_case_suffix:
        parser.error("--retry-case-suffix must be non-empty when --retry-failed is used")
    cases = [
        _write_case_config(
            label,
            overrides,
            species_tolerance_mode=args.species_tolerance_mode,
            n_sub_on=args.n_sub_on,
            n_sub_off=args.n_sub_off,
            case_suffix=args.case_suffix,
        )
        for label, overrides in specs
    ]
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_case": str(CASE_DIR / BASE_CASE_NAME),
        "horizon_ms": 1000.0,
        "max_workers": args.max_workers,
        "species_tolerance_mode": args.species_tolerance_mode,
        "n_sub_on": args.n_sub_on,
        "n_sub_off": args.n_sub_off,
        "case_suffix": args.case_suffix,
        "profile": args.profile,
        "retry_failed": args.retry_failed,
        "retry_max_workers": args.retry_max_workers,
        "retry_species_tolerance_mode": args.retry_species_tolerance_mode,
        "retry_n_sub_on": args.retry_n_sub_on,
        "retry_n_sub_off": args.retry_n_sub_off,
        "retry_case_suffix": args.retry_case_suffix,
        "case_count": len(cases),
        "cases": [{"case_id": case_id, "config": str(config_path)} for case_id, config_path in cases],
    }
    (output_root / "scan_plan.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    initial_summaries = _run_batch(cases, output_root, args.max_workers, phase="initial")
    _write_summaries(output_root, initial_summaries, stem="summary_initial")

    summaries = list(initial_summaries)
    retry_summaries: list[dict[str, Any]] = []
    failed_initial = [item for item in initial_summaries if not _summary_passes(item)]
    if args.retry_failed and failed_initial:
        spec_by_initial_id = {case_id: (label, overrides) for (label, overrides), (case_id, _) in zip(specs, cases)}
        retry_cases: list[tuple[str, Path]] = []
        retry_for: dict[str, str] = {}
        for failed in failed_initial:
            label, overrides = spec_by_initial_id[failed["case_id"]]
            retry_case_id, retry_config_path = _write_case_config(
                label,
                overrides,
                species_tolerance_mode=args.retry_species_tolerance_mode,
                n_sub_on=args.retry_n_sub_on,
                n_sub_off=args.retry_n_sub_off,
                case_suffix=f"{args.case_suffix}{args.retry_case_suffix}",
            )
            retry_cases.append((retry_case_id, retry_config_path))
            retry_for[retry_case_id] = failed["case_id"]
        retry_summaries = _run_batch(retry_cases, output_root, args.retry_max_workers, phase="retry")
        _write_summaries(output_root, retry_summaries, stem="summary_retry")

        retry_by_initial_id: dict[str, dict[str, Any]] = {}
        for retry in retry_summaries:
            initial_id = retry_for[retry["case_id"]]
            retry["retry_case_id"] = retry["case_id"]
            retry["retry_of"] = initial_id
            retry["retry_output_root"] = retry.get("output_root")
            retry["case_id"] = initial_id
            retry_by_initial_id[initial_id] = retry
        summaries = [retry_by_initial_id.get(item["case_id"], item) for item in initial_summaries]

    _write_summaries(output_root, summaries, stem="summary")
    failed = [item for item in summaries if not _summary_passes(item)]
    print(
        json.dumps(
            {
                "output_root": str(output_root),
                "case_count": len(summaries),
                "initial_failed_count": len(failed_initial),
                "retry_count": len(retry_summaries),
                "retry_failed_count": sum(not _summary_passes(item) for item in retry_summaries),
                "failed_count": len(failed),
            },
            ensure_ascii=False,
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
