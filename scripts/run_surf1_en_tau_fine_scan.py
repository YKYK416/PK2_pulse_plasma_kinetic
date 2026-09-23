"""Run a fine Surf1 E/N versus residence-time scan at 1000 ms."""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import yaml

from run_surf1_condition_scan import (
    BASE_CASE_NAME,
    CASE_DIR,
    _run_case,
    _slug,
    _summary_passes,
)


def _specs() -> list[tuple[str, dict[str, Any]]]:
    specs: list[tuple[str, dict[str, Any]]] = []
    for en_td in (70.0, 75.0, 80.0, 85.0, 90.0, 95.0, 100.0):
        for tau_ms in (2.0, 3.0, 4.0, 5.0, 7.0, 10.0):
            specs.append(
                (
                    f"EN{en_td:g}Td_tau{tau_ms:g}ms",
                    {"EN_on_Td": en_td, "residence_time_ms": tau_ms},
                )
            )
    return specs


def _write_case_config(label: str, en_td: float, tau_ms: float) -> tuple[str, Path]:
    case_id = f"surf1-cstr0d-fine-{_slug(label)}"
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
        "EN_on_Td": en_td,
        "reactor": {"residence_time_s": tau_ms * 1.0e-3},
        "n_sub_on": 240,
        "n_sub_off": 160,
        "notes": "Surf1 fine E/N-residence-time scan at a 1000 ms horizon.",
    }
    config_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    return case_id, config_path


def _write_summary(output_root: Path, summaries: list[dict[str, Any]]) -> None:
    summaries = sorted(summaries, key=lambda item: (item["EN_on_Td"], item["residence_time_ms"]))
    (output_root / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = [
        "case_id",
        "EN_on_Td",
        "residence_time_ms",
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
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    if args.max_workers < 1:
        parser.error("--max-workers must be at least one")

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    specs = _specs()
    cases = [(*_write_case_config(label, params["EN_on_Td"], params["residence_time_ms"]), params) for label, params in specs]
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_case": str(CASE_DIR / BASE_CASE_NAME),
        "horizon_ms": 1000.0,
        "max_workers": args.max_workers,
        "case_count": len(cases),
        "n_sub_on": 240,
        "n_sub_off": 160,
        "fixed_conditions": {
            "electron_density_cm3": 1.17e8,
            "gas_temperature_K": 400.0,
            "x_H2": 0.5,
            "site_density_factor": 1.0,
        },
        "cases": [
            {"case_id": case_id, "config": str(config_path), **params}
            for case_id, config_path, params in cases
        ],
    }
    (output_root / "scan_plan.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summaries: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(args.max_workers, len(cases))) as executor:
        futures = {
            executor.submit(_run_case, case_id, "EN_tau_fine", params["residence_time_ms"], config_path, output_root): (case_id, params)
            for case_id, config_path, params in cases
        }
        for future in as_completed(futures):
            case_id, params = futures[future]
            result = future.result()
            result.update({"EN_on_Td": params["EN_on_Td"], "residence_time_ms": params["residence_time_ms"]})
            summaries.append(result)
            print(
                json.dumps(
                    {
                        "completed": case_id,
                        **params,
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
