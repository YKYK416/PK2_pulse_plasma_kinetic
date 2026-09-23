"""Build and run an audited Gas1 pulse time scan without PK1 helper paths."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pk2_pulse.bolsig import audit_database  # noqa: E402
from pk2_pulse.build import plan_case_build, preprocess_and_compile, run_time_scan, stage_case_build  # noqa: E402
from pk2_pulse.config import load_pulse_case  # noqa: E402
from pk2_pulse.runtime import discover_runtime  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        type=Path,
        default=PROJECT_ROOT / "configs" / "gas_phase" / "closed_0d" / "gas1_T400K_N2-0p5_H2-0p5_P1atm.yaml",
    )
    parser.add_argument("--runtime-dir", type=Path)
    parser.add_argument("--cross-sections", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--max-workers", type=int, default=min(3, os.cpu_count() or 1))
    parser.add_argument("--dry-run", action="store_true", help="Print the audited build plan without creating files.")
    parser.add_argument(
        "--append-detailed-balance-inverses",
        action="store_true",
        help=(
            "Append auditable inverse superelastic and exact-label compatibility records to a case-local "
            "bolsigdb.dat. This is diagnostic only, not an approved Gas1 scientific result."
        ),
    )
    args = parser.parse_args()
    if args.max_workers < 1:
        parser.error("--max-workers must be at least one")

    case = load_pulse_case(args.case)
    runtime = discover_runtime(PROJECT_ROOT, args.runtime_dir, args.cross_sections or case.cross_section_source)
    mechanism = PROJECT_ROOT / "mechanisms" / case.mechanism / (
        "kinet_source.txt" if case.has_surface_reactions else "kinet.inp"
    )
    audit = audit_database(mechanism, runtime.cross_section_database)
    missing_surface_auxiliary = [
        str(mechanism.parent / name)
        for name in case.surface_auxiliary_files
        if not (mechanism.parent / name).is_file()
    ] if case.has_surface_reactions else []
    execution_eligible = audit.accepted or args.append_detailed_balance_inverses
    payload = {
        "accepted": audit.accepted,
        "execution_eligible": execution_eligible,
        "append_detailed_balance_inverses": args.append_detailed_balance_inverses,
        "case": case.id,
        "surface_auxiliary_files": {
            "required": list(case.surface_auxiliary_files),
            "missing": missing_surface_auxiliary,
            "accepted": not missing_surface_auxiliary,
        },
        "plan": plan_case_build(PROJECT_ROOT, case, args.output_root),
        "bolsig_audit": audit.as_dict(),
    }
    if args.dry_run or not execution_eligible or missing_surface_auxiliary:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if execution_eligible and not missing_surface_auxiliary else 2

    build = stage_case_build(
        PROJECT_ROOT,
        case,
        runtime,
        audit,
        args.output_root,
        append_detailed_balance_inverses=args.append_detailed_balance_inverses,
    )
    executable = preprocess_and_compile(build, runtime)
    results = run_time_scan(build, case, args.max_workers)
    payload.update({"build": str(build.build_dir), "executable": str(executable), "results": results})
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if all(
        item["validation"].get("accepted", False)
        and item["species_validation"].get("accepted", False)
        and item["surface_validation"].get("accepted", False)
        and item["reaction_rate_validation"].get("accepted", False)
        and item["dvode_audit"].get("accepted", False)
        for item in results
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
