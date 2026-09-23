"""Audit and consolidate recoveries for previously failed Gas1 cases."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _passes_gas(summary: dict[str, Any]) -> bool:
    return (
        summary.get("launcher_return_code") == 0
        and summary.get("return_code") == 0
        and summary.get("validation_accepted") is True
        and summary.get("species_validation_accepted") is True
        and summary.get("reaction_rate_validation_accepted") is True
        and summary.get("dvode_accepted") is True
        and summary.get("dvode_warning_count") == 0
        and summary.get("solver_error_count") == 0
    )


def _passes_surface_manifest(manifest: dict[str, Any]) -> bool:
    return (
        manifest.get("return_code") == 0
        and manifest.get("validation", {}).get("accepted") is True
        and manifest.get("species_validation", {}).get("accepted") is True
        and manifest.get("surface_validation", {}).get("accepted") is True
        and manifest.get("reaction_rate_validation", {}).get("accepted") is True
        and manifest.get("dvode_audit", {}).get("accepted") is True
        and manifest.get("dvode_audit", {}).get("warning_count") == 0
        and manifest.get("dvode_audit", {}).get("solver_error_count") == 0
    )


def _relative_difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    scale = max(abs(left), abs(right), 1.0e-300)
    return abs(left - right) / scale


def _recover_certification_failures(certification_root: Path) -> list[dict[str, Any]]:
    summaries = _load_json(certification_root / "summary.json")
    passed = [item for item in summaries if _passes_gas(item)]
    failures = [item for item in summaries if not _passes_gas(item)]
    recovered: list[dict[str, Any]] = []
    for failed in failures:
        candidates = [
            item
            for item in passed
            if item.get("anchor") == failed.get("anchor")
            and item.get("n_sub_on") == failed.get("n_sub_on")
            and item.get("n_sub_off") == failed.get("n_sub_off")
            and item.get("species_tolerance_mode")
            in {"positive_radical_floor_unbounded", "positive_unbounded"}
        ]
        candidates.sort(
            key=lambda item: (
                0 if item.get("species_tolerance_mode") == "positive_radical_floor_unbounded" else 1,
                item.get("n_sub_on", 0),
            )
        )
        if not candidates:
            candidates = [
                item
                for item in passed
                if item.get("anchor") == failed.get("anchor")
                and item.get("species_tolerance_mode") == "positive_radical_floor_unbounded"
            ]
            candidates.sort(key=lambda item: (item.get("n_sub_on", 0), item.get("n_sub_off", 0)))

        recovery = candidates[0] if candidates else None
        recovered.append(
            {
                "failure_family": "gas1_numerical_certification",
                "failed_case_id": failed.get("case_id"),
                "failed_anchor": failed.get("anchor"),
                "failed_mode": failed.get("species_tolerance_mode"),
                "failed_n_sub_on": failed.get("n_sub_on"),
                "failed_n_sub_off": failed.get("n_sub_off"),
                "failed_NH3_final_cm3": failed.get("NH3_final_cm3"),
                "failed_dvode_warning_count": failed.get("dvode_warning_count"),
                "failed_solver_error_count": failed.get("solver_error_count"),
                "recovery_status": "recovered_by_existing_passed_case" if recovery else "unresolved",
                "recovery_case_id": recovery.get("case_id") if recovery else None,
                "recovery_mode": recovery.get("species_tolerance_mode") if recovery else None,
                "recovery_n_sub_on": recovery.get("n_sub_on") if recovery else None,
                "recovery_n_sub_off": recovery.get("n_sub_off") if recovery else None,
                "recovery_NH3_final_cm3": recovery.get("NH3_final_cm3") if recovery else None,
                "recovery_output_root": recovery.get("output_root") if recovery else None,
                "failed_to_recovery_relative_difference": _relative_difference(
                    failed.get("NH3_final_cm3"), recovery.get("NH3_final_cm3") if recovery else None
                ),
                "bounded_mode_fixed": False,
                "stable_diagnostic_recovered": bool(recovery),
            }
        )
    return recovered


def _recover_surface_failures(surface_root: Path, surface_recovery_root: Path) -> list[dict[str, Any]]:
    summaries = _load_json(surface_root / "summary.json")
    failures = [item for item in summaries if not _passes_gas(item)]
    manifest_path = surface_recovery_root / "results" / "1000ms" / "manifest.json"
    manifest = _load_json(manifest_path) if manifest_path.is_file() else None
    recovered: list[dict[str, Any]] = []
    for failed in failures:
        passed = bool(manifest and _passes_surface_manifest(manifest))
        recovered.append(
            {
                "failure_family": "surf1_surface_chemistry",
                "failed_case_id": failed.get("case_id"),
                "failed_factor": failed.get("factor"),
                "failed_value": failed.get("value"),
                "failed_NH3_final_cm3": failed.get("NH3_final_cm3"),
                "failed_solver_error_count": failed.get("solver_error_count"),
                "recovery_status": "recovered_by_dedicated_high_stiffness_case" if passed else "unresolved",
                "recovery_case_id": manifest_path.parent.parent.parent.name if passed else None,
                "recovery_mode": "positive_radical_floor_unbounded" if passed else None,
                "recovery_n_sub_on": 240 if passed else None,
                "recovery_n_sub_off": 160 if passed else None,
                "recovery_MXSTEP": 2_000_000 if passed else None,
                "recovery_NH3_final_cm3": manifest.get("validation", {}).get("NH3_final_cm3") if passed else None,
                "recovery_output_root": str(surface_recovery_root) if passed else None,
                "bounded_mode_fixed": False,
                "stable_diagnostic_recovered": passed,
            }
        )
    return recovered


def _write_outputs(output_root: Path, records: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    records = sorted(records, key=lambda item: (item["failure_family"], item["failed_case_id"] or ""))
    (output_root / "recovery.json").write_text(
        json.dumps({"metadata": metadata, "records": records}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    fields = sorted({key for record in records for key in record})
    with (output_root / "recovery.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    lines = [
        "# Gas1 失败案例恢复记录",
        "",
        f"生成时间：{metadata['created_at']}",
        f"初始失败数：{metadata['initial_failure_count']}",
        f"已恢复数：{metadata['recovered_count']}",
        f"未解决数：{metadata['unresolved_count']}",
        "",
        "## 判定",
        "",
        "恢复表示在不改动反应机理和前向激发记录的前提下，找到通过全部质量门的稳定数值路径；不表示 bounded scalar 与 PRF 的绝对浓度已经一致。",
        "",
        "| failure family | failed case | recovery mode | substeps | status |",
        "|---|---|---|---:|---|",
    ]
    for record in records:
        substeps = (
            f"{record.get('recovery_n_sub_on')}/{record.get('recovery_n_sub_off')}"
            if record.get("recovery_n_sub_on")
            else "-"
        )
        lines.append(
            f"| {record.get('failure_family')} | {record.get('failed_case_id')} | "
            f"{record.get('recovery_mode') or '-'} | {substeps} | {record.get('recovery_status')} |"
        )
    (output_root / "recovery.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--certification-root", type=Path, required=True)
    parser.add_argument("--surface-root", type=Path, required=True)
    parser.add_argument("--surface-recovery-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=False)
    records = _recover_certification_failures(args.certification_root.resolve())
    records.extend(_recover_surface_failures(args.surface_root.resolve(), args.surface_recovery_root.resolve()))
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "certification_root": str(args.certification_root.resolve()),
        "surface_root": str(args.surface_root.resolve()),
        "surface_recovery_root": str(args.surface_recovery_root.resolve()),
        "initial_failure_count": len(records),
        "recovered_count": sum(item["stable_diagnostic_recovered"] for item in records),
        "unresolved_count": sum(not item["stable_diagnostic_recovered"] for item in records),
        "bounded_mode_fixed_count": sum(item["bounded_mode_fixed"] for item in records),
    }
    _write_outputs(output_root, records, metadata)
    print(json.dumps({"output_root": str(output_root), **metadata}, ensure_ascii=False))
    return 0 if metadata["unresolved_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
