"""Audit and stage the cross-section database consumed by ZDPlasKin BOLSIG."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil


BOLSIG_RATE = re.compile(r"!\s*(?:[\d.+\-EeDd]+\s*\*\s*)?BOLSIG\s+(.+?)\s*$", re.IGNORECASE)
COLLISION_TYPES = {"ELASTIC", "EFFECTIVE", "MOMENTUM", "IONIZATION", "ATTACHMENT", "EXCITATION", "ROTATION"}

# These aliases are deliberately finite and reported in every audit manifest.
# They represent typography/case differences between the Hong mechanism and
# the bundled LXCat-formatted source, not inferred chemistry substitutions.
EXPLICIT_ALIASES = {
    "N2 -> N2(a`1)": "N2 -> N2(a'1)",
    "H2 -> H2(v1)": "H2 -> H2(V1)",
    "H2 -> H2(v2)": "H2 -> H2(V2)",
    "H2 -> H2(v3)": "H2 -> H2(V3)",
    "H2(v1) -> H2": "H2(V1) -> H2",
    "H2(v2) -> H2": "H2(V2) -> H2",
    "H2(v3) -> H2": "H2(V3) -> H2",
}

# These are the only forward records from the bundled source used to construct
# an explicit inverse block.  The source records themselves are never edited.
DETAILED_BALANCE_FORWARD_PROCESSES = (
    *(f"N2 -> N2(v{level})" for level in range(1, 9)),
    *(f"H2 -> H2(V{level})" for level in range(1, 4)),
    "H2 -> H2(B3SIG)",
    "H2 -> H2(B1SIG)",
    "H2 -> H2(C3PI)",
    "H2 -> H2(A3SIG)",
    # This state is listed as an independent BOLSIG gas in kinet.inp.  The
    # loader therefore needs its inverse scattering record even though the
    # reaction block does not contain an explicit electron de-excitation line.
    "H2 -> H2(RYDBERG_SUM)",
)

# ZDPlasKin 2.0a links a BOLSIG comment label byte-for-byte.  The mechanism's
# historic backtick spelling therefore needs an appended compatibility record;
# the original apostrophe-labelled LXCat record remains untouched.
FORWARD_PROCESS_ALIASES_TO_APPEND = {
    "N2 -> N2(a'1)": "N2 -> N2(a`1)",
    # The LXCat H2 electronic-state headers include a threshold suffix such
    # as ``(8.9eV)``.  The ZDPlasKin 2.0a linker treats that suffix as part of
    # the process name, whereas ``kinet.inp`` uses the bare state name.
    "H2 -> H2(B3SIG)": "H2 -> H2(B3SIG)",
    "H2 -> H2(B1SIG)": "H2 -> H2(B1SIG)",
    "H2 -> H2(C3PI)": "H2 -> H2(C3PI)",
    "H2 -> H2(A3SIG)": "H2 -> H2(A3SIG)",
    "H2 -> H2(RYDBERG_SUM)": "H2 -> H2(RYDBERG_SUM)",
    "H2 -> H2(V1)": "H2 -> H2(V1)",
    "H2 -> H2(V2)": "H2 -> H2(V2)",
    "H2 -> H2(V3)": "H2 -> H2(V3)",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def normalise_process(value: str) -> str:
    compact = re.sub(r"\s*->\s*", " -> ", " ".join(value.strip().split()))
    # LXCat labels often append a threshold annotation to the product, e.g.
    # ``H2 -> H2(V1)(0.516eV)``.  It is metadata, not part of the ZDPlasKin
    # BOLSIG process key.  Species-state parentheses are deliberately kept.
    return re.sub(r"\((?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?eV\)$", "", compact)


def reverse_process(value: str) -> str | None:
    parts = normalise_process(value).split(" -> ", 1)
    if len(parts) != 2:
        return None
    return f"{parts[1]} -> {parts[0]}"


def required_processes(mechanism: Path) -> list[str]:
    values: list[str] = []
    for line in mechanism.read_text(encoding="utf-8").splitlines():
        match = BOLSIG_RATE.search(line)
        if match:
            value = normalise_process(match.group(1))
            if value not in values:
                values.append(value)
    if not values:
        raise ValueError(f"No BOLSIG reactions found in {mechanism}")
    return values


def database_processes(database: Path) -> set[str]:
    """Read process labels from LXCat/BOLSIG formatted collision blocks."""
    lines = database.read_text(encoding="utf-8", errors="replace").splitlines()
    processes: set[str] = set()
    for index, line in enumerate(lines[:-1]):
        if line.strip().upper() not in COLLISION_TYPES:
            continue
        target = lines[index + 1].strip()
        if target and not target.startswith(("COMMENT", "-")):
            processes.add(normalise_process(target))
    if not processes:
        raise ValueError(f"No collision process blocks found in {database}")
    return processes


@dataclass(frozen=True)
class BolsigAudit:
    required: tuple[str, ...]
    direct_matches: tuple[str, ...]
    alias_matches: tuple[dict[str, str], ...]
    inverse_only: tuple[dict[str, str], ...]
    missing: tuple[str, ...]

    @property
    def accepted(self) -> bool:
        return not self.inverse_only and not self.missing

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "required": list(self.required),
            "direct_matches": list(self.direct_matches),
            "alias_matches": list(self.alias_matches),
            "inverse_only": list(self.inverse_only),
            "missing": list(self.missing),
            "explicit_aliases": EXPLICIT_ALIASES,
        }


def audit_database(mechanism: Path, database: Path) -> BolsigAudit:
    available = database_processes(database)
    required = required_processes(mechanism)
    direct: list[str] = []
    aliases: list[dict[str, str]] = []
    inverse_only: list[dict[str, str]] = []
    missing: list[str] = []
    for process in required:
        candidate = EXPLICIT_ALIASES.get(process, process)
        if candidate in available:
            if candidate == process:
                direct.append(process)
            else:
                aliases.append({"mechanism": process, "database": candidate})
            continue
        reverse = reverse_process(candidate)
        if reverse and reverse in available:
            inverse_only.append({"mechanism": process, "database_forward": reverse})
        else:
            missing.append(process)
    return BolsigAudit(tuple(required), tuple(direct), tuple(aliases), tuple(inverse_only), tuple(missing))


def _is_delimiter(line: str) -> bool:
    return bool(re.fullmatch(r"-{5,}", line.strip()))


def _parse_number(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "e"))


def _forward_excitation_tables(database: Path) -> dict[str, tuple[float, list[tuple[float, float]]]]:
    """Read threshold/table pairs from standard LXCat excitation blocks."""
    lines = database.read_text(encoding="utf-8", errors="replace").splitlines()
    tables: dict[str, tuple[float, list[tuple[float, float]]]] = {}
    for index, line in enumerate(lines):
        if line.strip().upper() != "EXCITATION" or index + 2 >= len(lines):
            continue
        process = normalise_process(lines[index + 1])
        threshold_fields = lines[index + 2].strip().split()
        if not threshold_fields:
            continue
        try:
            threshold = _parse_number(threshold_fields[0])
        except ValueError:
            continue
        start = next((cursor for cursor in range(index + 3, len(lines)) if _is_delimiter(lines[cursor])), None)
        if start is None:
            continue
        table: list[tuple[float, float]] = []
        for cursor in range(start + 1, len(lines)):
            if _is_delimiter(lines[cursor]):
                break
            fields = lines[cursor].split()
            if len(fields) < 2:
                continue
            try:
                table.append((_parse_number(fields[0]), _parse_number(fields[1])))
            except ValueError:
                continue
        if table:
            tables[process] = (threshold, table)
    return tables


def _render_explicit_inverse(
    forward_process: str,
    threshold_ev: float,
    table: list[tuple[float, float]],
    upper_to_lower_weight_ratio: float,
) -> str:
    """Render an explicit negative-threshold superelastic collision block.

    For a forward excitation with energy loss ``U`` and cross section
    ``sigma_f(E)``, detailed balance gives
    ``sigma_i(e) = (g_lower/g_upper) * (e+U)/e * sigma_f(e+U)``.
    The generated first point is the finite linear-threshold limit inferred
    from the first positive-energy source point.  Source records are retained
    unchanged; this is an appended, auditable inverse record.
    """
    lower, upper = forward_process.split(" -> ", 1)
    positive = [(energy, sigma) for energy, sigma in table if energy > threshold_ev]
    if not positive:
        raise ValueError(f"No positive-energy data after threshold for {forward_process}")
    first_energy, first_sigma = positive[0]
    epsilon = first_energy - threshold_ev
    if epsilon <= 0:
        raise ValueError(f"Invalid first energy point for {forward_process}")
    lower_to_upper = 1.0 / upper_to_lower_weight_ratio
    inverse: list[tuple[float, float]] = [(0.0, lower_to_upper * threshold_ev * first_sigma / epsilon)]
    for energy, sigma in positive:
        inverse_energy = energy - threshold_ev
        inverse_sigma = lower_to_upper * energy / inverse_energy * sigma
        inverse.append((inverse_energy, inverse_sigma))
    rendered = [
        "EXCITATION",
        f"{upper} -> {lower}",
        f" {-threshold_ev:.12e} / explicit superelastic energy gain; generated by detailed balance",
        f"COMMENT: PK2 generated inverse of {forward_process}; g_upper/g_lower={upper_to_lower_weight_ratio:.12g}",
        "COMMENT: source forward record retained unchanged; see bolsig_database_manifest.json",
        "------------------------------------------------------------",
    ]
    rendered.extend(f" {energy:.12e} {sigma:.12e}" for energy, sigma in inverse)
    rendered.append("------------------------------------------------------------")
    return "\n".join(rendered)


def _render_forward_alias(
    source_process: str,
    alias_process: str,
    threshold_ev: float,
    table: list[tuple[float, float]],
) -> str:
    """Render an appended compatibility alias without changing source data."""
    rendered = [
        "EXCITATION",
        alias_process,
        f" {threshold_ev:.12e} / copied threshold for ZDPlasKin process-label compatibility",
        f"COMMENT: PK2 compatibility alias of {source_process}; source record retained unchanged",
        "------------------------------------------------------------",
    ]
    rendered.extend(f" {energy:.12e} {sigma:.12e}" for energy, sigma in table)
    rendered.append("------------------------------------------------------------")
    return "\n".join(rendered)


def generate_detailed_balance_database(
    source: Path,
    target: Path,
    upper_to_lower_weight_ratio: float = 1.0,
) -> dict[str, object]:
    """Append explicit inverse blocks while leaving every source line intact."""
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite {target}")
    if upper_to_lower_weight_ratio <= 0:
        raise ValueError("upper_to_lower_weight_ratio must be positive")
    tables = _forward_excitation_tables(source)
    blocks: list[str] = []
    aliases: list[dict[str, str]] = []
    for source_process, alias_process in FORWARD_PROCESS_ALIASES_TO_APPEND.items():
        if source_process not in tables:
            raise ValueError(f"Missing required forward alias source record: {source_process}")
        threshold, table = tables[source_process]
        blocks.append(_render_forward_alias(source_process, alias_process, threshold, table))
        aliases.append({"source": source_process, "appended_alias": alias_process})
    for process in DETAILED_BALANCE_FORWARD_PROCESSES:
        if process not in tables:
            raise ValueError(f"Missing required forward excitation record: {process}")
        threshold, table = tables[process]
        blocks.append(_render_explicit_inverse(process, threshold, table, upper_to_lower_weight_ratio))
    source_text = source.read_text(encoding="utf-8", errors="replace").rstrip("\r\n")
    target.write_text(source_text + "\n\n" + "\n\n".join(blocks) + "\n", encoding="utf-8", newline="\n")
    return {
        "transform": "append_explicit_superelastic_inverse_v1",
        "source": str(source.resolve()),
        "source_sha256": sha256(source),
        "target": str(target),
        "target_sha256": sha256(target),
        "forward_records_modified": False,
        "appended_forward_process_aliases": aliases,
        "upper_to_lower_statistical_weight_ratio": upper_to_lower_weight_ratio,
        "generated_inverse_processes": [reverse_process(process) for process in DETAILED_BALANCE_FORWARD_PROCESSES],
        "formula": "sigma_inverse(e)=(g_lower/g_upper)*((e+U)/e)*sigma_forward(e+U)",
        "zero_energy_rule": "linear_threshold_limit_from_first_positive_forward_data_point",
    }


def stage_database(source: Path, build_dir: Path, audit: BolsigAudit) -> dict[str, object]:
    """Copy the approved source verbatim as the case-local BOLSIG database."""
    if not audit.accepted:
        raise ValueError("Refusing to stage an unverified BOLSIG database; inspect the audit report")
    target = build_dir / "bolsigdb.dat"
    if target.exists():
        raise FileExistsError(f"Refusing to overwrite {target}")
    shutil.copy2(source, target)
    manifest = {
        "source": str(source.resolve()),
        "source_sha256": sha256(source),
        "staged": str(target),
        "staged_sha256": sha256(target),
        "audit": audit.as_dict(),
    }
    (build_dir / "bolsig_database_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
