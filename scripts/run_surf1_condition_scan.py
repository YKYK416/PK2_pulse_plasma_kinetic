"""Run the first-stage Surf1 surface-assisted CSTR one-factor scan."""
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
CASE_DIR = PROJECT_ROOT / "configs" / "surface_assisted" / "cstr"
BASE_CASE_NAME = "surf1_T400K_N2-0p5_H2-0p5_P1atm_tau1ms_scan.yaml"


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


def build_case_specs(base_site_density_cm3: float) -> list[tuple[str, str, float | None, dict[str, Any]]]:
    """Return one baseline plus six one-factor sweeps around it."""
    specs: list[tuple[str, str, float | None, dict[str, Any]]] = [("baseline", "baseline", None, {})]

    for value in (20.0, 35.0, 75.0, 100.0):
        specs.append((f"EN{value:g}Td", "EN_on_Td", value, {"EN_on_Td": value}))
    for value in (3.0e7, 1.0e8, 3.0e8, 1.0e9):
        specs.append(
            (
                f"ne{value:.3e}",
                "electron_density_cm3",
                value,
                {"initial_state": {"electron_density_cm3": value}, "feed": {"electron_density_cm3": value}},
            )
        )
    for value in (0.1, 0.3, 3.0, 10.0):
        specs.append((f"tau{value:g}ms", "residence_time_ms", value, {"reactor": {"residence_time_s": value * 1.0e-3}}))
    for value in (300.0, 350.0, 500.0, 600.0):
        specs.append(
            (
                f"T{value:g}K",
                "gas_temperature_K",
                value,
                {"initial_state": {"gas_temperature_K": value}, "feed": {"gas_temperature_K": value}},
            )
        )
    for value in (0.2, 0.35, 0.65, 0.8):
        specs.append(
            (
                f"xH2{value:g}",
                "x_H2",
                value,
                {
                    "initial_state": {"mole_fractions": {"N2": 1.0 - value, "H2": value}},
                    "feed": {"mole_fractions": {"N2": 1.0 - value, "H2": value}},
                },
            )
        )
    for value in (0.1, 0.3, 3.0, 10.0):
        specs.append(
            (
                f"site{value:g}x",
                "site_density_factor",
                value,
                {"surface": {"site_density_cm3": base_site_density_cm3 * value}},
            )
        )
    return specs


def _write_case_config(
    label: str,
    overrides: dict[str, Any],
    *,
    case_suffix: str,
) -> tuple[str, Path]:
    case_id = f"surf1-cstr0d-screen-{_slug(label)}{case_suffix}"
    config_path = CASE_DIR / f"{case_id}.yaml"
    data: dict[str, Any] = {
        "schema_version": 1,
        "id": case_id,
        "includes": [BASE_CASE_NAME],
        "run": {
            "horizons_ms": [1000.0],
            "output_every_cycles": 100,
            "timeout_s": 86400.0,
            "solver_time_mode": "phase_local",
            "species_tolerance_mode": "positive_radical_floor_unbounded",
        },
    }
    data = _deep_merge(data, overrides)
    data["notes"] = "Surf1 first-stage one-factor screening at a 1000 ms horizon."
    config_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    return case_id, config_path


def _run_case(
    case_id: str,
    factor: str,
    value: float | None,
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
        "factor": factor,
        "value": value,
        "config": str(config_path),
        "output_root": str(case_root),
        "launcher_return_code": completed.returncode,
    }
    if not result_manifest.is_file():
        summary["failure"] = "1000ms result manifest missing"
        return summary

    result = json.loads(result_manifest.read_text(encoding="utf-8"))
    validation = result.get("validation", {})
    surface_validation = result.get("surface_validation", {})
    dvode = result.get("dvode_audit", {})
    summary.update(
        {
            "return_code": result.get("return_code"),
            "final_time_s": validation.get("final_time_s"),
            "NH3_final_cm3": validation.get("NH3_final_cm3"),
            "Surf_final_coverage": _final_surface_coverage(case_root / "results" / "1000ms" / "surface_endpoints.csv", "Surf"),
            "HSurf_final_coverage": _final_surface_coverage(case_root / "results" / "1000ms" / "surface_endpoints.csv", "HSurf"),
            "validation_accepted": validation.get("accepted"),
            "species_validation_accepted": result.get("species_validation", {}).get("accepted"),
            "surface_validation_accepted": surface_validation.get("accepted"),
            "reaction_rate_validation_accepted": result.get("reaction_rate_validation", {}).get("accepted"),
            "dvode_warning_count": dvode.get("warning_count"),
            "solver_error_count": dvode.get("solver_error_count"),
            "dvode_accepted": dvode.get("accepted"),
        }
    )
    return summary


def _final_surface_coverage(path: Path, species: str) -> float | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("species") == species]
    if not rows:
        return None
    final = max(rows, key=lambda row: (int(row["cycle"]), int(row["phase"])))
    return float(final["coverage"])


def _summary_passes(summary: dict[str, Any]) -> bool:
    return (
        summary.get("launcher_return_code") == 0
        and not summary.get("failure")
        and summary.get("return_code") == 0
        and summary.get("validation_accepted") is True
        and summary.get("species_validation_accepted") is True
        and summary.get("surface_validation_accepted") is True
        and summary.get("reaction_rate_validation_accepted") is True
        and summary.get("dvode_accepted") is True
        and summary.get("dvode_warning_count") == 0
        and summary.get("solver_error_count") == 0
    )


def _write_summary(output_root: Path, summaries: list[dict[str, Any]]) -> None:
    summaries = sorted(summaries, key=lambda item: (item["factor"], item["case_id"]))
    (output_root / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = [
        "case_id",
        "factor",
        "value",
        "NH3_final_cm3",
        "Surf_final_coverage",
        "HSurf_final_coverage",
        "final_time_s",
        "dvode_warning_count",
        "solver_error_count",
        "launcher_return_code",
        "return_code",
        "validation_accepted",
        "species_validation_accepted",
        "surface_validation_accepted",
        "reaction_rate_validation_accepted",
        "dvode_accepted",
        "config",
        "output_root",
        "failure",
    ]
    with (output_root / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summaries)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--case-suffix", default="")
    parser.add_argument("--only", nargs="*", help="Restrict cases by labels, e.g. EN20Td tau0-1ms site0-1x")
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args()
    if args.max_workers < 1:
        parser.error("--max-workers must be at least one")

    base_path = CASE_DIR / BASE_CASE_NAME
    base = yaml.safe_load(base_path.read_text(encoding="utf-8"))
    base_site_density_cm3 = float(base["surface"]["site_density_cm3"])
    specs = build_case_specs(base_site_density_cm3)
    if args.only:
        requested = {_slug(value) for value in args.only}
        specs = [item for item in specs if _slug(item[0]) in requested]
        if not specs:
            parser.error("--only did not match any case labels")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = (args.output_root or PROJECT_ROOT / "run_data" / "diagnostics" / f"surf1_condition_scan_{timestamp}").resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    cases = [
        (*_write_case_config(label, overrides, case_suffix=args.case_suffix), factor, value)
        for label, factor, value, overrides in specs
    ]
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_case": str(base_path),
        "horizon_ms": 1000.0,
        "max_workers": args.max_workers,
        "case_count": len(cases),
        "screening_factors": ["EN_on_Td", "electron_density_cm3", "residence_time_ms", "gas_temperature_K", "x_H2", "site_density_factor"],
        "cases": [{"case_id": case_id, "config": str(config_path), "factor": factor, "value": value} for case_id, config_path, factor, value in cases],
    }
    (output_root / "scan_plan.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summaries: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(args.max_workers, len(cases))) as executor:
        futures = {
            executor.submit(_run_case, case_id, factor, value, config_path, output_root): case_id
            for case_id, config_path, factor, value in cases
        }
        for future in as_completed(futures):
            result = future.result()
            summaries.append(result)
            print(
                json.dumps(
                    {
                        "completed": result["case_id"],
                        "factor": result["factor"],
                        "value": result["value"],
                        "NH3_final_cm3": result.get("NH3_final_cm3"),
                        "passed": _summary_passes(result),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    _write_summary(output_root, summaries)
    failed = [item for item in summaries if not _summary_passes(item)]
    print(json.dumps({"output_root": str(output_root), "case_count": len(summaries), "failed_count": len(failed)}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
