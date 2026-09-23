"""Discover and stage the local ZDPlasKin runtime without absolute paths."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil


@dataclass(frozen=True)
class ZDPlasKinRuntime:
    runtime_dir: Path
    cross_section_database: Path
    compiler: Path

    @property
    def preprocessor(self) -> Path:
        return self.runtime_dir / "preprocessor.exe"

    @property
    def dvode_source(self) -> Path:
        return self.runtime_dir / "dvode_f90_m.F90"

    @property
    def bolsig_dll(self) -> Path:
        return self.runtime_dir / "bolsig_x86_64_g.dll"

    @property
    def bolsig_library(self) -> Path:
        return self.runtime_dir / "bolsig_x86_64_g.lib"

    def required_files(self) -> tuple[Path, ...]:
        return (self.preprocessor, self.dvode_source, self.bolsig_dll, self.bolsig_library, self.cross_section_database, self.compiler)


def discover_runtime(project_root: Path, runtime_dir: Path | None = None, cross_section_database: Path | None = None) -> ZDPlasKinRuntime:
    """Locate vendor assets relative to the repository's workspace parent."""
    workspace_root = project_root.resolve().parent
    candidates = (
        workspace_root / "ZDPlasKin_2.0a_Windows" / "ZDPlasKin_2.0a_Windows",
        workspace_root / "ZDPlasKin_2.0a_Windows",
    )
    selected_runtime = runtime_dir.resolve() if runtime_dir else next((candidate for candidate in candidates if (candidate / "preprocessor.exe").is_file()), candidates[0])
    selected_database = (
        cross_section_database.resolve()
        if cross_section_database
        else workspace_root / "bolsigplus072024-win" / "SigloDataBase-LXCat-04Jun2013.txt"
    )
    compiler_name = shutil.which("gfortran")
    compiler = Path(compiler_name).resolve() if compiler_name else Path("gfortran")
    runtime = ZDPlasKinRuntime(selected_runtime, selected_database, compiler)
    missing = [str(path) for path in runtime.required_files() if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing ZDPlasKin runtime input(s):\n  - " + "\n  - ".join(missing))
    return runtime


def stage_runtime(runtime: ZDPlasKinRuntime, build_dir: Path) -> None:
    """Place native files beside a case-local build without mutating vendor files."""
    sources = [runtime.preprocessor, runtime.dvode_source, runtime.bolsig_dll, runtime.bolsig_library]
    # Preserve vendor-supplied DLL dependencies and auxiliary uppercase data
    # files in the case-local build.  ``bolsigdb.dat`` is staged separately
    # only after the mechanism/database audit accepts it.
    sources.extend(sorted(runtime.runtime_dir.glob("*.dll")))
    sources.extend(sorted(runtime.runtime_dir.glob("*.DAT")))
    for source in dict.fromkeys(sources):
        target = build_dir / source.name
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite staged runtime file: {target}")
        shutil.copy2(source, target)
