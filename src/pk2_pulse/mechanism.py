"""Stage case-local gas or surface mechanisms without editing provenance input."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil


SURFACE_SPECIES = ("Surf", "HSurf", "NSurf", "NHSurf", "NH2Surf")
SURFACE_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])(?:" + "|".join(SURFACE_SPECIES) + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
SURFACE_RATE_BLOCK_START = "# Metal surface column is selected."
WALL_RELAXATION_BLOCK_START = "# Wall relaxation"
H_MINUS_RECOMBINATION_BLOCK_START = "# recombination of H^- ions"


def gas_species_names(source: Path) -> tuple[str, ...]:
    """Return active gas species in the mechanism's ``SPECIES`` section."""
    in_species = False
    names: list[str] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        code = line.strip().upper()
        if code == "SPECIES":
            in_species = True
            continue
        if in_species and code == "END":
            break
        if not in_species or not line.strip() or line.lstrip().startswith(("#", "!")):
            continue
        for name in line.split():
            if name not in SURFACE_SPECIES and name not in names:
                names.append(name)
    if not names:
        raise ValueError(f"No species found in mechanism: {source}")
    return tuple(names)


def all_species_names(source: Path) -> tuple[str, ...]:
    """Return every active species in the mechanism, including surface states."""
    in_species = False
    names: list[str] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        code = line.strip().upper()
        if code == "SPECIES":
            in_species = True
            continue
        if in_species and code == "END":
            break
        if not in_species or not line.strip() or line.lstrip().startswith(("#", "!")):
            continue
        for name in line.split():
            if name not in names:
                names.append(name)
    if not names:
        raise ValueError(f"No species found in mechanism: {source}")
    return tuple(names)


def surface_species_names(source: Path) -> tuple[str, ...]:
    """Return the configured surface states present in a mechanism."""
    names = set(all_species_names(source))
    return tuple(name for name in SURFACE_SPECIES if name in names)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_active_surface_reaction(line: str, in_reactions: bool) -> bool:
    stripped = line.lstrip()
    return in_reactions and "=>" in line and not stripped.startswith(("#", "!")) and SURFACE_TOKEN.search(line) is not None


def transform_gas_phase(
    source_text: str, disable_wall_relaxation: bool,
) -> tuple[str, list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    """Disable selected non-gas mechanisms in a build-local mechanism copy."""
    output: list[str] = []
    disabled_reactions: list[dict[str, object]] = []
    disabled_rate_statements: list[dict[str, object]] = []
    disabled_wall_relaxation: list[dict[str, object]] = []
    in_reactions = False
    in_surface_rate_block = False
    in_wall_relaxation_block = False
    for line_number, line in enumerate(source_text.splitlines(keepends=True), start=1):
        code = line.strip().upper()
        if code == "REACTIONS":
            in_reactions = True
        elif in_reactions and code == "END":
            in_reactions = False
            in_surface_rate_block = False
        elif in_reactions and line.strip().startswith(SURFACE_RATE_BLOCK_START):
            in_surface_rate_block = True
        elif in_reactions and line.strip().startswith(WALL_RELAXATION_BLOCK_START):
            in_wall_relaxation_block = disable_wall_relaxation
        elif in_wall_relaxation_block and line.strip().startswith(H_MINUS_RECOMBINATION_BLOCK_START):
            in_wall_relaxation_block = False

        disable_rate = in_surface_rate_block and line.lstrip().startswith("$")
        disable_wall_item = in_wall_relaxation_block and (
            line.lstrip().startswith("$") or ("=>" in line and not line.lstrip().startswith(("#", "!")))
        )
        if _is_active_surface_reaction(line, in_reactions) or disable_rate or disable_wall_item:
            ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            record = line.rstrip("\r\n")
            output.append(f"#OFF# {record}{ending}")
            target = disabled_wall_relaxation if disable_wall_item else (
                disabled_rate_statements if disable_rate else disabled_reactions
            )
            target.append({"line": line_number, "record": record})
        else:
            output.append(line)
    if in_reactions:
        raise ValueError("Input mechanism has an unterminated REACTIONS block")
    return "".join(output), disabled_reactions, disabled_rate_statements, disabled_wall_relaxation


def stage_gas_phase_mechanism(
    source: Path, build_dir: Path, disable_wall_relaxation: bool = False,
) -> dict[str, object]:
    """Write a build-local gas-only ``kinet.inp`` plus its transform manifest."""
    source_bytes = source.read_bytes()
    transformed, disabled_reactions, disabled_rate_statements, disabled_wall_relaxation = transform_gas_phase(
        source_bytes.decode("utf-8"), disable_wall_relaxation
    )
    if not disabled_reactions:
        raise ValueError("No active surface reactions found; refusing a gas-only transform with no effect")
    if disable_wall_relaxation and not disabled_wall_relaxation:
        raise ValueError("No active wall-relaxation records found; refusing an ineffective wall-relaxation transform")
    output = build_dir / "kinet.inp"
    manifest_path = build_dir / "mechanism_transform_manifest.json"
    if output.exists() or manifest_path.exists():
        raise FileExistsError(f"Refusing to overwrite staged mechanism output: {build_dir}")
    output_bytes = transformed.encode("utf-8")
    output.write_bytes(output_bytes)
    manifest = {
        "transform": "disable_active_surface_reactions_v1",
        "source": str(source.resolve()),
        "source_sha256": _sha256_bytes(source_bytes),
        "output": str(output),
        "output_sha256": _sha256_bytes(output_bytes),
        "surface_reactions_disabled": len(disabled_reactions),
        "surface_rate_statements_disabled": len(disabled_rate_statements),
        "wall_relaxation_disabled": len(disabled_wall_relaxation),
        "wall_relaxation_disabled_records": disabled_wall_relaxation,
        "disabled_reactions": disabled_reactions,
        "disabled_rate_statements": disabled_rate_statements,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def stage_surface_assisted_mechanism(
    source: Path,
    build_dir: Path,
    auxiliary_files: tuple[str, ...],
) -> dict[str, object]:
    """Stage the active surface mechanism and its runtime parameter files."""
    source_bytes = source.read_bytes()
    output = build_dir / "kinet.inp"
    manifest_path = build_dir / "mechanism_transform_manifest.json"
    if output.exists() or manifest_path.exists():
        raise FileExistsError(f"Refusing to overwrite staged mechanism output: {build_dir}")
    missing = [name for name in auxiliary_files if not (source.parent / name).is_file()]
    if missing:
        raise FileNotFoundError(
            "Surface mechanism requires missing auxiliary file(s):\n  - "
            + "\n  - ".join(str(source.parent / name) for name in missing)
        )
    output.write_bytes(source_bytes)
    staged_auxiliary: list[str] = []
    for name in auxiliary_files:
        source_auxiliary = source.parent / name
        target = build_dir / name
        shutil.copy2(source_auxiliary, target)
        staged_auxiliary.append(str(target))
    manifest = {
        "transform": "stage_active_surface_mechanism_v1",
        "source": str(source.resolve()),
        "source_sha256": _sha256_bytes(source_bytes),
        "output": str(output),
        "output_sha256": _sha256_bytes(source_bytes),
        "surface_reactions_disabled": 0,
        "surface_auxiliary_files": list(auxiliary_files),
        "staged_surface_auxiliary_files": staged_auxiliary,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
