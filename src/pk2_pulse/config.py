"""Load and validate versioned pulse-plasma case configurations."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import yaml


KB_J_PER_K = 1.380649e-23
SURFACE_SPECIES = ("Surf", "HSurf", "NSurf", "NHSurf", "NH2Surf")
SURFACE_AUXILIARY_FILES = (
    "REACTION_E_IN.DAT",
    "REACTION_E_BASIS.DAT",
    "ENTROPY_PARA_IN.DAT",
    "ENTROPY_INFO_BASIS.DAT",
)
DEFAULT_SURFACE_SITE_DENSITY_CM3 = 1.0e15 / (0.5 * 48.6 / (3370.0 * 2.1))


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml(path: Path, stack: tuple[Path, ...] = ()) -> dict[str, Any]:
    path = path.resolve()
    if path in stack:
        chain = " -> ".join(str(item) for item in (*stack, path))
        raise ValueError(f"Configuration include cycle: {chain}")
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Configuration root must be a mapping: {path}")
    includes = data.pop("includes", [])
    if not isinstance(includes, list):
        raise ValueError(f"includes must be a list: {path}")
    resolved: dict[str, Any] = {}
    for include in includes:
        if not isinstance(include, str):
            raise ValueError(f"include entries must be paths: {path}")
        resolved = _merge(resolved, _load_yaml(path.parent / include, (*stack, path)))
    return _merge(resolved, data)


@dataclass(frozen=True)
class PulseCase:
    """Fully resolved gas-phase pulse inputs for closed 0D or CSTR operation."""

    config_path: Path
    id: str
    mechanism: str
    cross_section_source: Path
    surface_reactions: str
    surface_site_initialization: str
    surface_site_density_cm3: float
    surface_initial_densities: tuple[tuple[str, float], ...]
    surface_auxiliary_files: tuple[str, ...]
    pressure_pa: float
    gas_temperature_k: float
    x_n2: float
    x_h2: float
    electron_density_cm3: float
    reactor_id: str
    flow_enabled: bool
    residence_time_s: float
    feed_pressure_pa: float
    feed_gas_temperature_k: float
    feed_x_n2: float
    feed_x_h2: float
    feed_electron_density_cm3: float
    flow_species: str
    excluded_from_flow: tuple[str, ...]
    en_on_td: float
    en_off_td: float
    frequency_hz: float
    duty_cycle: float
    horizons_ms: tuple[float, ...]
    output_every_cycles: int
    timeout_s: float
    solver_time_mode: str
    species_tolerance_mode: str
    atol_cm3: float
    rtol: float
    mxstep: int
    n_sub_on: int
    n_sub_off: int
    wall_relaxation: str
    thermodynamic_boundary: str
    gas_heating: str
    electron_density_mode: str
    charge_compensation: str

    @property
    def period_s(self) -> float:
        return 1.0 / self.frequency_hz

    @property
    def t_on_s(self) -> float:
        return self.duty_cycle * self.period_s

    @property
    def t_off_s(self) -> float:
        return self.period_s - self.t_on_s

    @property
    def total_density_cm3(self) -> float:
        return self.pressure_pa / (KB_J_PER_K * self.gas_temperature_k) * 1.0e-6

    @property
    def feed_density_cm3(self) -> float:
        return self.feed_pressure_pa / (KB_J_PER_K * self.feed_gas_temperature_k) * 1.0e-6

    @property
    def is_cstr(self) -> bool:
        return self.reactor_id == "cstr_0d" and self.flow_enabled

    @property
    def has_surface_reactions(self) -> bool:
        return self.mechanism == "surface_assisted" and self.surface_reactions == "enabled"

    @property
    def surface_initial_density_map(self) -> dict[str, float]:
        return dict(self.surface_initial_densities)

    def cycles_for_horizon(self, horizon_ms: float) -> int:
        cycles = horizon_ms * 1.0e-3 * self.frequency_hz
        rounded = round(cycles)
        if not math.isclose(cycles, rounded, rel_tol=0.0, abs_tol=1.0e-10):
            raise ValueError(f"{horizon_ms:g} ms is not an integer number of pulse periods")
        return int(rounded)


def load_pulse_case(path: Path) -> PulseCase:
    """Resolve a gas or surface-assisted closed-0D/CSTR YAML case."""
    data = _load_yaml(path)
    reactor = data.get("reactor", {})
    initial = data.get("initial_state", {})
    run = data.get("run", {})
    plasma_model = data.get("plasma_model", {})
    cross_sections = data.get("cross_sections", {})
    fractions = initial.get("mole_fractions", {})
    mechanism = str(data.get("mechanism", ""))
    if mechanism not in {"gas_phase", "surface_assisted"}:
        raise ValueError("mechanism must be gas_phase or surface_assisted")
    reactor_id = str(reactor.get("id", ""))
    flow_enabled = reactor.get("flow") == "enabled"
    if (reactor_id, flow_enabled) not in {("closed_0d", False), ("cstr_0d", True)}:
        raise ValueError("The shared pulse runner supports closed_0d/disabled or cstr_0d/enabled")
    surface_reactions = str(reactor.get("surface_reactions", "disabled"))
    if surface_reactions not in {"enabled", "disabled"}:
        raise ValueError("surface_reactions must be enabled or disabled")
    if mechanism == "gas_phase" and surface_reactions != "disabled":
        raise ValueError("gas_phase cases require surface_reactions: disabled")
    if mechanism == "surface_assisted" and surface_reactions != "enabled":
        raise ValueError("surface_assisted cases require surface_reactions: enabled")
    if reactor.get("wall_relaxation", "enabled") not in {"enabled", "disabled"}:
        raise ValueError("wall_relaxation must be enabled or disabled")
    if reactor.get("thermodynamic_boundary", "constant_volume") != "constant_volume":
        raise ValueError("The current runner requires thermodynamic_boundary: constant_volume")
    if reactor.get("gas_heating", "disabled") != "disabled":
        raise ValueError("The current runner requires gas_heating: disabled")
    if plasma_model.get("electron_density_mode", "prescribed_constant") != "prescribed_constant":
        raise ValueError("The current runner requires electron_density_mode: prescribed_constant")
    if plasma_model.get("charge_compensation", "implicit_stationary_background") != "implicit_stationary_background":
        raise ValueError("The current runner requires charge_compensation: implicit_stationary_background")
    raw_horizons = run.get("horizons_ms")
    if raw_horizons is None and "horizon_ms" in run:
        raw_horizons = [run["horizon_ms"]]
    horizons = tuple(float(value) for value in (raw_horizons or ()))
    if not horizons:
        raise ValueError("run.horizons_ms or run.horizon_ms must contain at least one horizon")
    feed = data.get("feed", {}) if reactor_id == "cstr_0d" else {}
    feed_fractions = feed.get("mole_fractions", fractions)
    residence_time_s = float(reactor.get("residence_time_s", 0.0))
    surface = data.get("surface", {})
    surface_site_density_cm3 = float(
        surface.get("site_density_cm3", DEFAULT_SURFACE_SITE_DENSITY_CM3)
    )
    initial_surface_densities = surface.get(
        "initial_densities_cm3",
        {"Surf": surface_site_density_cm3, "HSurf": 0.0, "NSurf": 0.0, "NHSurf": 0.0, "NH2Surf": 0.0},
    )
    if not isinstance(initial_surface_densities, dict):
        raise ValueError("surface.initial_densities_cm3 must be a mapping")
    surface_initial_densities_tuple = tuple(
        (name, float(initial_surface_densities.get(name, 0.0))) for name in SURFACE_SPECIES
    )
    surface_auxiliary_files = tuple(
        str(value) for value in data.get("surface_auxiliary_files", SURFACE_AUXILIARY_FILES)
    )
    initial_pressure_pa = float(initial.get("pressure_Pa", feed.get("pressure_Pa", 101325.0)))
    initial_temperature_k = float(initial.get("gas_temperature_K", feed.get("gas_temperature_K", 300.0)))
    initial_electron_density_cm3 = float(initial.get("electron_density_cm3", feed.get("electron_density_cm3", 1.17e8)))
    case = PulseCase(
        config_path=path.resolve(),
        id=str(data["id"]),
        mechanism=mechanism,
        cross_section_source=(path.resolve().parent / str(cross_sections.get("source", "../../../../bolsigplus072024-win/SigloDataBase-LXCat-04Jun2013.txt"))).resolve(),
        surface_reactions=surface_reactions,
        surface_site_initialization=str(reactor.get("surface_site_initialization", "required" if mechanism == "surface_assisted" else "not_applicable")),
        surface_site_density_cm3=surface_site_density_cm3,
        surface_initial_densities=surface_initial_densities_tuple,
        surface_auxiliary_files=surface_auxiliary_files,
        pressure_pa=initial_pressure_pa,
        gas_temperature_k=initial_temperature_k,
        x_n2=float(fractions.get("N2", feed_fractions.get("N2", 0.5))),
        x_h2=float(fractions.get("H2", feed_fractions.get("H2", 0.5))),
        electron_density_cm3=initial_electron_density_cm3,
        reactor_id=reactor_id,
        flow_enabled=flow_enabled,
        residence_time_s=residence_time_s,
        feed_pressure_pa=float(feed.get("pressure_Pa", initial_pressure_pa)),
        feed_gas_temperature_k=float(feed.get("gas_temperature_K", initial_temperature_k)),
        feed_x_n2=float(feed_fractions["N2"]),
        feed_x_h2=float(feed_fractions["H2"]),
        feed_electron_density_cm3=float(feed.get("electron_density_cm3", initial_electron_density_cm3)),
        flow_species=str(reactor.get("flow_species", "gas_heavy_species")),
        excluded_from_flow=tuple(str(value) for value in reactor.get("excluded_from_flow", ())),
        en_on_td=float(data["EN_on_Td"]),
        en_off_td=float(data["EN_off_Td"]),
        frequency_hz=float(data["frequency_Hz"]),
        duty_cycle=float(data["duty_cycle"]),
        horizons_ms=horizons,
        output_every_cycles=int(run.get("output_every_cycles", 1)),
        timeout_s=float(run.get("timeout_s", 21600.0)),
        solver_time_mode=str(run.get("solver_time_mode", "global")),
        species_tolerance_mode=str(run.get("species_tolerance_mode", "scalar")),
        atol_cm3=float(data["ATOL_cm3"]),
        rtol=float(data["RTOL"]),
        mxstep=int(data["MXSTEP"]),
        n_sub_on=int(data["n_sub_on"]),
        n_sub_off=int(data["n_sub_off"]),
        wall_relaxation=str(reactor.get("wall_relaxation", "enabled")),
        thermodynamic_boundary=str(reactor.get("thermodynamic_boundary", "constant_volume")),
        gas_heating=str(reactor.get("gas_heating", "disabled")),
        electron_density_mode=str(plasma_model.get("electron_density_mode", "prescribed_constant")),
        charge_compensation=str(plasma_model.get("charge_compensation", "implicit_stationary_background")),
    )
    if not math.isclose(case.x_n2 + case.x_h2, 1.0, rel_tol=0.0, abs_tol=1.0e-12):
        raise ValueError("N2 and H2 mole fractions must sum to one")
    if not math.isclose(case.feed_x_n2 + case.feed_x_h2, 1.0, rel_tol=0.0, abs_tol=1.0e-12):
        raise ValueError("CSTR feed N2 and H2 mole fractions must sum to one")
    if case.pressure_pa <= 0 or case.gas_temperature_k <= 0 or case.frequency_hz <= 0:
        raise ValueError("Pressure, temperature, and frequency must be positive")
    if not 0 < case.duty_cycle < 1:
        raise ValueError("duty_cycle must be strictly between zero and one")
    if case.en_on_td <= 0 or case.en_off_td < 0:
        raise ValueError("Reduced fields must be non-negative and E/N on must be positive")
    if case.n_sub_on < 2 or case.n_sub_off < 2:
        raise ValueError("At least two integration substeps are required for each pulse phase")
    if case.mxstep < 1:
        raise ValueError("MXSTEP must be positive")
    if case.output_every_cycles < 1:
        raise ValueError("run.output_every_cycles must be positive")
    if case.timeout_s <= 0:
        raise ValueError("run.timeout_s must be positive")
    if case.solver_time_mode not in {"global", "phase_local"}:
        raise ValueError("run.solver_time_mode must be global or phase_local")
    if case.species_tolerance_mode not in {
        "scalar",
        "radical_floor",
        "radical_floor_signed",
        "radical_floor_signed_tiny",
        "radical_floor_unbounded",
        "scalar_unbounded",
        "scalar_signed_tiny",
        "positive_unbounded",
        "positive_radical_floor_unbounded",
    }:
        raise ValueError(
            "run.species_tolerance_mode must be scalar, radical_floor, radical_floor_signed, radical_floor_signed_tiny, radical_floor_unbounded, scalar_unbounded, scalar_signed_tiny, positive_unbounded, or positive_radical_floor_unbounded"
        )
    if case.feed_pressure_pa <= 0 or case.feed_gas_temperature_k <= 0:
        raise ValueError("CSTR feed pressure and temperature must be positive")
    if case.has_surface_reactions:
        if case.surface_site_initialization != "required":
            raise ValueError("surface_assisted cases require surface_site_initialization: required")
        if case.surface_site_density_cm3 <= 0:
            raise ValueError("surface.site_density_cm3 must be positive")
        if any(value < 0.0 for _, value in case.surface_initial_densities):
            raise ValueError("surface.initial_densities_cm3 must be non-negative")
        if case.surface_initial_density_map["Surf"] <= 0.0:
            raise ValueError("surface.initial_densities_cm3.Surf must be positive")
    if case.is_cstr:
        if case.residence_time_s <= 0:
            raise ValueError("CSTR residence_time_s must be positive")
        if case.flow_species != "gas_heavy_species":
            raise ValueError("The current CSTR implementation supports flow_species: gas_heavy_species")
        required_exclusions = {"electrons", "surface_states"}
        if not required_exclusions.issubset(set(case.excluded_from_flow)):
            raise ValueError("CSTR excluded_from_flow must include electrons and surface_states")
    elif case.residence_time_s != 0.0:
        raise ValueError("closed_0d cases must not define a nonzero residence_time_s")
    for horizon in case.horizons_ms:
        if horizon <= 0:
            raise ValueError("All horizons must be positive")
        case.cycles_for_horizon(horizon)
    return case
