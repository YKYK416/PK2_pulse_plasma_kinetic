"""Create an auditable gas-only ZDPlasKin mechanism build copy.

The project-managed Hong input retains surface species and surface-reaction
records for provenance.  This tool never edits that source.  Instead it writes
a local build copy in which active reactions involving known surface species
are prefixed with ``#OFF#``.  A manifest records both source and output hashes
and the exact disabled source lines.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_ROOT / "mechanisms" / "gas_phase" / "kinet.inp"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "run_data" / "mechanism_preflight" / "gas_phase"
SURFACE_SPECIES = ("Surf", "HSurf", "NSurf", "NHSurf", "NH2Surf")
SURFACE_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])(?:" + "|".join(SURFACE_SPECIES) + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
SURFACE_RATE_BLOCK_START = "# Metal surface column is selected."


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_lf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def is_active_surface_reaction(line: str, in_reactions: bool) -> bool:
    stripped = line.lstrip()
    return (
        in_reactions
        and "=>" in line
        and not stripped.startswith(("#", "!"))
        and SURFACE_TOKEN.search(line) is not None
    )


def transform(source_text: str) -> tuple[str, list[dict[str, object]], list[dict[str, object]]]:
    """Disable active surface reactions and their marked rate-calculation block."""
    lines = source_text.splitlines(keepends=True)
    output: list[str] = []
    disabled_reactions: list[dict[str, object]] = []
    disabled_rate_statements: list[dict[str, object]] = []
    in_reactions = False
    in_surface_rate_block = False

    for line_number, line in enumerate(lines, start=1):
        code = line.strip().upper()
        if code == "REACTIONS":
            in_reactions = True
        elif in_reactions and code == "END":
            in_reactions = False
            in_surface_rate_block = False
        elif in_reactions and line.strip().startswith(SURFACE_RATE_BLOCK_START):
            in_surface_rate_block = True

        should_disable_rate_statement = in_surface_rate_block and line.lstrip().startswith("$")
        if is_active_surface_reaction(line, in_reactions) or should_disable_rate_statement:
            line_ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            record = line.rstrip("\r\n")
            output.append(f"#OFF# {record}{line_ending}")
            target = disabled_rate_statements if should_disable_rate_statement else disabled_reactions
            target.append({"line": line_number, "record": record})
        else:
            output.append(line)

    if in_reactions:
        raise ValueError("Input mechanism has an unterminated REACTIONS block")
    return "".join(output), disabled_reactions, disabled_rate_statements


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    source = args.source.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Missing source mechanism: {source}")
    output_dir = args.output_dir.resolve()
    output_path = output_dir / "kinet.inp"
    manifest_path = output_dir / "mechanism_transform_manifest.json"
    if output_path.exists() or manifest_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing preflight output: {output_dir}")

    source_bytes = source.read_bytes()
    source_text = source_bytes.decode("utf-8")
    transformed_text, disabled_reactions, disabled_rate_statements = transform(source_text)
    if not disabled_reactions:
        raise ValueError("No active surface reactions were found; refusing an empty transform")
    remaining_active = [
        index
        for index, line in enumerate(transformed_text.splitlines(), start=1)
        if is_active_surface_reaction(line, True)
    ]
    if remaining_active:
        raise ValueError(f"Surface reactions remain active at line(s): {remaining_active}")

    output_dir.mkdir(parents=True, exist_ok=False)
    output_bytes = transformed_text.encode("utf-8")
    output_path.write_bytes(output_bytes)
    manifest = {
        "transform": "disable_active_surface_reactions_v1",
        "source": str(source),
        "source_sha256_raw": sha256_bytes(source_bytes),
        "source_sha256_canonical_lf": sha256_bytes(canonical_lf(source_text).encode("utf-8")),
        "output": str(output_path),
        "output_sha256": sha256_bytes(output_bytes),
        "surface_reactions_disabled": len(disabled_reactions),
        "surface_rate_statements_disabled": len(disabled_rate_statements),
        "disabled_reactions": disabled_reactions,
        "disabled_rate_statements": disabled_rate_statements,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(output_path),
        "manifest": str(manifest_path),
        "surface_reactions_disabled": len(disabled_reactions),
        "surface_rate_statements_disabled": len(disabled_rate_statements),
        "output_sha256": manifest["output_sha256"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
