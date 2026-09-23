"""Run the second-stage Surf1 targeted multifactor CSTR scan."""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

import yaml

from run_surf1_condition_scan import (
    BASE_CASE_NAME,
    CASE_DIR,
    PROJECT_ROOT,
    _deep_merge,
    _run_case,
    _slug,
    _summary_passes,
)


def _build_specs(base_site_density_cm3: float) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Build the targeted 48-point combination grid around the first-stage winners."""
    del base_site_density_cm3  # Keep the second-stage grid at the baseline site density.
    specs: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for en_td in (75.0, 100.0):
        for tau_ms in (3.0, 10.0):
            for ne_cm3 in (3.0e8, 1.0e9):
                for temperature_k in (450.0, 500.0, 550.0):
                    for x_h2 in (0.65, 0.80):
                        label = (
                            f"EN{en_td:g}Td_tau{tau_ms:g}ms_ne{ne_cm3:.3e}_"
                            f"T{temperature_k:g}K_xH2{x_h2:g}"
                        )
                        parameters = {
                            "EN_on_Td": en_td,
                            "residence_time_ms": tau_ms,
                            "electron_density_cm3": ne_cm3,
                            "gas_temperature_K": temperature_k,
                            "x_H2": x_h2,
                            "site_density_factor": 1.0,
                        }
                        overrides = {
                            "EN_on_Td": en_td,
                            "reactor": {"residence_time_s": tau_ms * 1.0e-3},
                            "initial_state": {
                                "electron_density_cm3": ne_cm3,
                                "gas_temperature_K": temperature_k,
                                "mole_fractions": {"N2": 1.0 - x_h2, "H2": x_h2},
                            },
                            "feed": {
                                "electron_density_cm3": ne_cm3,
                                "gas_temperature_K": temperature_k,
                                "mole_fractions": {"N2": 1.0 - x_h2, "H2": x_h2},
                            },
                            "n_sub_on": 240,
                            "n_sub_off": 160,
                        }
                        specs.append((label, parameters, overrides))
    return specs


def _write_case_config(label: str, overrides: dict[str, Any]) -> tuple[str, Path]:
    case_id = f"surf1-cstr0d-grid-{_slug(label)}"
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
        "notes": "Surf1 second-stage targeted multifactor screening at a 1000 ms horizon.",
    }
    data = _deep_merge(data, overrides)
    config_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    return case_id, config_path


def _write_summary(output_root: Path, summaries: list[dict[str, Any]]) -> None:
    summaries = sorted(summaries, key=lambda item: item["case_id"])
    (output_root / "summary.json").write_text(json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = [
        "case_id",
        "EN_on_Td",
        "residence_time_ms",
        "electron_density_cm3",
        "gas_temperature_K",
        "x_H2",
        "site_density_factor",
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

    base_path = CASE_DIR / BASE_CASE_NAME
    base = yaml.safe_load(base_path.read_text(encoding="utf-8"))
    specs = _build_specs(float(base["surface"]["site_density_cm3"]))
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    cases = [(*_write_case_config(label, overrides), parameters) for label, parameters, overrides in specs]
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "base_case": str(base_path),
        "horizon_ms": 1000.0,
        "max_workers": args.max_workers,
        "case_count": len(cases),
        "site_density_factor": 1.0,
        "cases": [
            {"case_id": case_id, "config": str(config_path), "parameters": parameters}
            for case_id, config_path, parameters in cases
        ],
    }
    (output_root / "scan_plan.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summaries: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(args.max_workers, len(cases))) as executor:
        futures = {
            executor.submit(_run_case, case_id, "multifactor", None, config_path, output_root): (case_id, parameters)
            for case_id, config_path, parameters in cases
        }
        for future in as_completed(futures):
            case_id, parameters = futures[future]
            result = future.result()
            result.update(parameters)
            summaries.append(result)
            print(
                json.dumps(
                    {
                        "completed": case_id,
                        **parameters,
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
