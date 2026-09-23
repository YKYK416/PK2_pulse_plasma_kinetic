# Shared implementation

Reusable modules belong here: configuration loading, BOLSIG cross-section
auditing, vendor-runtime discovery/staging, closed-0D Fortran driver rendering,
native build orchestration, result validation, and common plotting primitives.
Do not add a second copy of those functions under each mechanism or reactor
directory.

`driver.py` and `build.py` replace the legacy generator dependency for the
Gas1 and Surf1 0D workflows. They do not import `zdp_gui`, `zdp_runtime`, or
any `F:\\Codex\\PK1` path. Native staging is forbidden until `bolsig.py`
accepts the complete database audit; see `docs/CROSS_SECTION_DECISION_GAS1.md`.

For Gas1, the build stages a mechanism-local transform that disables configured
surface chemistry and optionally wall relaxation without changing the
provenance mechanism. For Surf1, the active surface mechanism is staged as-is
along with its four runtime parameter files; surface site states are initialized
by the generated driver and excluded from CSTR flow. The driver records active
species endpoint densities, surface densities/coverages when enabled, and
full-horizon mean reaction rates. The generated module receives the configured
DVODE `MXSTEP` only through an anchored case-local patch.
