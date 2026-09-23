"""Run the Gas1 numerical-convergence certification matrix."""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_gas1_condition_scan import (  # noqa: E402
    PROJECT_ROOT as SCAN_PROJECT_ROOT,
    _run_case,
    _summary_passes,
    _write_case_config,
)


if SCAN_PROJECT_ROOT != PROJECT_ROOT:
    raise RuntimeError("Condition-scan project root does not match certification project root")


ANCHORS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("low_EN45_tau0p3", {"EN_on_Td": 45.0, "reactor": {"residence_time_s": 0.3e-3}}),
    ("baseline_EN50_tau1", {}),
    ("transition_EN49_tau1", {"EN_on_Td": 49.0}),
    ("transition_EN53_tau1", {"EN_on_Td": 53.0}),
    ("high_EN60_tau1", {"EN_on_Td": 60.0}),
    ("high_EN65_tau2", {"EN_on_Td": 65.0, "reactor": {"residence_time_s": 2.0e-3}}),
)
MODES: tuple[str, ...] = ("scalar", "positive_unbounded", "positive_radical_floor_unbounded")
SUBSTEP_PAIRS: tuple[tuple[int, int], ...] = ((120, 80), (240, 160), (480, 320))
MODE_LABELS = {
    "scalar": "bnd",
    "positive_unbounded": "pos",
    "positive_radical_floor_unbounded": "prf",
}


def _write_certification_summary(output_root: Path, summaries: list[dict[str, Any]]) -> None:
    summaries = sorted(summaries, key=lambda item: item["case_id"])
    (output_root / "summary.json").write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    fields = [
        "case_id",
        "anchor",
        "species_tolerance_mode",
        "n_sub_on",
        "n_sub_off",
        "NH3_final_cm3",
        "dvode_warning_count",
        "solver_error_count",
        "launcher_return_code",
        "return_code",
        "validation_accepted",
        "species_validation_accepted",
        "reaction_rate_validation_accepted",
        "dvode_accepted",
        "passed",
        "config",
        "output_root",
        "failure",
    ]
    with (output_root / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summaries)


def _relative_difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    scale = max(abs(left), abs(right), 1.0e-300)
    return abs(left - right) / scale


def _make_comparisons(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {
        (item["anchor"], item["species_tolerance_mode"], item["n_sub_on"], item["n_sub_off"]): item
        for item in summaries
    }
    comparisons: list[dict[str, Any]] = []
    for anchor, _ in ANCHORS:
        scalar_mid = by_key.get((anchor, "scalar", 240, 160))
        floor_mid = by_key.get((anchor, "positive_radical_floor_unbounded", 240, 160))
        positive_mid = by_key.get((anchor, "positive_unbounded", 240, 160))
        floor_high = by_key.get((anchor, "positive_radical_floor_unbounded", 480, 320))
        floor_mid_value = floor_mid.get("NH3_final_cm3") if floor_mid else None
        scalar_mid_value = scalar_mid.get("NH3_final_cm3") if scalar_mid else None
        positive_mid_value = positive_mid.get("NH3_final_cm3") if positive_mid else None
        floor_high_value = floor_high.get("NH3_final_cm3") if floor_high else None
        comparisons.append(
            {
                "anchor": anchor,
                "bounded_vs_positive_radical_floor_240_160": _relative_difference(
                    scalar_mid_value, floor_mid_value
                ),
                "positive_vs_positive_radical_floor_240_160": _relative_difference(
                    positive_mid_value, floor_mid_value
                ),
                "positive_radical_floor_240_160_vs_480_320": _relative_difference(
                    floor_mid_value, floor_high_value
                ),
                "bounded_passed": bool(scalar_mid and _summary_passes(scalar_mid)),
                "positive_passed": bool(positive_mid and _summary_passes(positive_mid)),
                "positive_radical_floor_passed": bool(floor_mid and _summary_passes(floor_mid)),
                "positive_radical_floor_high_substeps_passed": bool(
                    floor_high and _summary_passes(floor_high)
                ),
            }
        )
    return comparisons


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--case-suffix", default="-cert")
    args = parser.parse_args()
    if args.max_workers < 1:
        parser.error("--max-workers must be at least one")
    if not args.case_suffix:
        parser.error("--case-suffix must be non-empty")

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    specs: list[dict[str, Any]] = []
    cases: list[tuple[str, Path, dict[str, Any]]] = []
    for anchor, overrides in ANCHORS:
        for mode in MODES:
            for n_sub_on, n_sub_off in SUBSTEP_PAIRS:
                # Keep the generated Windows build path short enough for the
                # native preprocessor and compiler manifest files.
                label = f"{anchor}_{MODE_LABELS[mode]}_n{n_sub_on}-{n_sub_off}"
                case_id, config_path = _write_case_config(
                    label,
                    overrides,
                    species_tolerance_mode=mode,
                    n_sub_on=n_sub_on,
                    n_sub_off=n_sub_off,
                    case_suffix=args.case_suffix,
                )
                metadata = {
                    "anchor": anchor,
                    "species_tolerance_mode": mode,
                    "n_sub_on": n_sub_on,
                    "n_sub_off": n_sub_off,
                }
                cases.append((case_id, config_path, metadata))
                specs.append({"case_id": case_id, "config": str(config_path), **metadata})

    plan = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "horizon_ms": 1000.0,
        "max_workers": args.max_workers,
        "anchor_count": len(ANCHORS),
        "mode_count": len(MODES),
        "substep_pair_count": len(SUBSTEP_PAIRS),
        "case_count": len(cases),
        "anchors": [anchor for anchor, _ in ANCHORS],
        "species_tolerance_modes": list(MODES),
        "substep_pairs": [list(pair) for pair in SUBSTEP_PAIRS],
        "cases": specs,
    }
    (output_root / "certification_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    summaries: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(args.max_workers, len(cases))) as executor:
        futures = {
            executor.submit(_run_case, case_id, config_path, output_root): (case_id, metadata)
            for case_id, config_path, metadata in cases
        }
        for future in as_completed(futures):
            case_id, metadata = futures[future]
            summary = future.result()
            summary.update(metadata)
            summary["passed"] = _summary_passes(summary)
            summaries.append(summary)
            print(
                json.dumps(
                    {
                        "completed": case_id,
                        **metadata,
                        "NH3_final_cm3": summary.get("NH3_final_cm3"),
                        "passed": summary["passed"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    _write_certification_summary(output_root, summaries)
    comparisons = _make_comparisons(summaries)
    (output_root / "comparisons.json").write_text(
        json.dumps(comparisons, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    max_mode_difference = max(
        (item["bounded_vs_positive_radical_floor_240_160"] or 0.0 for item in comparisons),
        default=0.0,
    )
    max_substep_difference = max(
        (item["positive_radical_floor_240_160_vs_480_320"] or 0.0 for item in comparisons),
        default=0.0,
    )
    failed = [item for item in summaries if not item["passed"]]
    certification = {
        "case_count": len(summaries),
        "failed_count": len(failed),
        "max_bounded_vs_positive_radical_floor_relative_difference": max_mode_difference,
        "max_positive_radical_floor_substep_relative_difference": max_substep_difference,
        "mode_difference_within_5pct": max_mode_difference <= 0.05,
        "substep_difference_within_5pct": max_substep_difference <= 0.05,
        "all_solver_quality_gates_passed": not failed,
        "comparisons": comparisons,
    }
    (output_root / "certification.json").write_text(
        json.dumps(certification, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output_root": str(output_root), **{key: value for key, value in certification.items() if key != "comparisons"}}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
