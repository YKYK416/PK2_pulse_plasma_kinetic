"""Validate a pulse case, local ZDPlasKin runtime, and BOLSIG cross sections."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pk2_pulse.bolsig import audit_database, sha256  # noqa: E402
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
    args = parser.parse_args()

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
    payload = {
        "accepted": audit.accepted,
        "case": {
            "id": case.id,
            "pressure_Pa": case.pressure_pa,
            "gas_temperature_K": case.gas_temperature_k,
            "mole_fractions": {"N2": case.x_n2, "H2": case.x_h2},
            "electron_density_cm3": case.electron_density_cm3,
            "electron_density_mode": case.electron_density_mode,
            "charge_compensation": case.charge_compensation,
            "thermodynamic_boundary": case.thermodynamic_boundary,
            "gas_heating": case.gas_heating,
            "wall_relaxation": case.wall_relaxation,
            "MXSTEP": case.mxstep,
            "pulse": {
                "EN_on_Td": case.en_on_td,
                "EN_off_Td": case.en_off_td,
                "frequency_Hz": case.frequency_hz,
                "duty_cycle": case.duty_cycle,
                "t_on_s": case.t_on_s,
                "t_off_s": case.t_off_s,
            },
            "total_density_cm3": case.total_density_cm3,
            "horizons_ms": list(case.horizons_ms),
            "cycles": [case.cycles_for_horizon(value) for value in case.horizons_ms],
        },
        "runtime": {
            "runtime_dir": str(runtime.runtime_dir),
            "compiler": str(runtime.compiler),
            "cross_section_database": str(runtime.cross_section_database),
            "cross_section_database_sha256": sha256(runtime.cross_section_database),
        },
        "bolsig_audit": audit.as_dict(),
        "surface_auxiliary_files": {
            "required": list(case.surface_auxiliary_files),
            "missing": missing_surface_auxiliary,
            "accepted": not missing_surface_auxiliary,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if audit.accepted and not missing_surface_auxiliary else 2


if __name__ == "__main__":
    raise SystemExit(main())
