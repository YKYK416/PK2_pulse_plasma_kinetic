# PK2 pulsed-plasma ammonia simulations

This repository organizes pulsed plasma-kinetic studies of ammonia synthesis.
Versioned configurations describe the mechanism, reactor boundary, pulse,
feed, and solver settings. Shared Python code audits inputs, prepares a local
ZDPlasKin build, runs pulse horizons, and validates the generated outputs.

The project covers four model families: gas-phase or surface-assisted
chemistry, each in closed 0D or 0D CSTR form. Case definitions live under
`configs/`; shared runtime code lives under `src/pk2_pulse/` and command-line
entry points under `scripts/`.

## Scientific status

The current Gas1 configuration is an initial-1-atm, constant-volume,
fixed-400-K case with a 50-Td / 0-Td square-wave pulse at 10 kHz and 20% duty
cycle. Its BOLSIG audit still identifies collision processes that are not
directly supplied by the candidate cross-section source. A failed audit blocks
the normal build and run path. The optional inverse-process construction is
diagnostic only and does not establish a scientifically validated result.

Existing closed-0D and CSTR trajectories are documented as diagnostic where
the DVODE roundoff-warning or numerical-convergence checks have not passed.
Do not present them as certified concentrations or periodic steady states.
See the [cross-section decision record](docs/CROSS_SECTION_DECISION_GAS1.md)
and [results and limitations](docs/RESULTS_AND_LIMITATIONS.md) for the current
evidence and interpretation.

## Repository layout

```text
configs/                    # versioned case and shared solver/pulse inputs
mechanisms/                 # mechanism sources, metadata, and required parameters
src/pk2_pulse/              # shared configuration, audit, build, and run logic
scripts/                    # preflight, simulation, scans, and plotting commands
studies/                    # versioned study definitions
docs/                       # project structure, methods, and result limitations
GasPulse/0D/                # archived legacy scripts and historical data
run_data/                   # local builds, manifests, logs, and case outputs
generated_figures/          # local batch-rendered figures
```

Configuration files and mechanism inputs are versioned. Generated case
directories under `run_data/` and bulk figures under `generated_figures/` are
Git-ignored; the current local `run_data/` contains the large per-case outputs.
Only selected, reviewed results or figures belong in the repository. The
[project structure guide](docs/PROJECT_STRUCTURE.md) describes the policy.

## Local workflow

Install Python and the Fortran compiler, and place the local ZDPlasKin and
BOLSIG source files in the locations described by
[`external/README.md`](external/README.md). From the repository root, inspect
the default Gas1 case with:

```powershell
python scripts/preflight_pulse_case.py
```

This reports the resolved runtime and cross-section audit without creating a
build directory. The runner also has a non-writing plan mode:

```powershell
python scripts/run_pulse_case.py --dry-run
```

Proceed with a normal run only when the BOLSIG audit is accepted. The
`--append-detailed-balance-inverses` option is provided solely for explicitly
labelled engineering diagnostics; its results are not an approved Gas1
scientific dataset. The preflight, build, and run behavior is documented in
[`scripts/README.md`](scripts/README.md).

Scripts retained under `GasPulse/0D/scripts/` are historical. Some depend on
the former machine-local Hong/PK1 helper stack; use the shared workflow above
for current work.
