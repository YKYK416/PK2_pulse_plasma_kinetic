# Commands and plotting recipes

This directory contains thin command-line entry points and versioned plot
recipes. Shared configuration, BOLSIG auditing, runtime discovery, validation,
and execution logic belongs in `src/pk2_pulse/`.

`preflight_pulse_case.py` is the mandatory first command for a new pulsed
calculation. It checks the versioned case configuration, ZDPlasKin runtime,
gfortran, cross-section database, and every mechanism BOLSIG label before any
build directory is created.

`prepare_gas_mechanism.py` creates a local, Git-ignored build copy of the Hong
input with active surface reactions explicitly disabled. It preserves the
project-managed source mechanism and writes an adjacent transform manifest.

`run_pulse_case.py` is the standalone Gas1 execution entry point.  It uses the
shared configuration, BOLSIG audit, runtime staging, generated Fortran driver,
vendor preprocessor, and gfortran toolchain.  It first audits every requested
electron-collision process.  If the audit is not accepted, it exits before
creating a build directory or starting a native executable.

For every completed horizon, the runner writes `pulse_summary.csv`,
`species_endpoints.csv` for all active gas species, and
`mean_reaction_rates.csv` for the full-horizon mean rate of every generated
reaction. The case-local build contains `preprocessor_quality.json` so vendor
preprocessor warnings remain visible in the run record.

Every horizon manifest also contains a `dvode_audit` block. It counts the
vendor DVODE `T + H = T` roundoff warnings and negative solver states. The
runner keeps a complete result for diagnosis, but its exit status is nonzero
unless the structural validators pass and the DVODE audit reports zero
warnings. This prevents a long trajectory from being silently presented as
numerically certified.

For long scans, `run.output_every_cycles` limits diagnostic CSV volume while
always retaining the initial and final pulse endpoints; it does not change
the integration. The Gas1 2/5/10 s (2000/5000/10000 ms) diagnostic case samples every 100 cycles
(10 ms) and accepts a user-selected `--max-workers` value.

Use a non-mutating inspection first:

```powershell
python scripts/run_pulse_case.py --dry-run
```

Once a complete, approved cross-section database is supplied, run the scan
with isolated parallel horizon directories:

```powershell
python scripts/run_pulse_case.py --max-workers 3
```

For the explicitly diagnostic detailed-balance construction used to prove the
local execution path, add `--append-detailed-balance-inverses`. It appends
compatibility and inverse records to a case-local `bolsigdb.dat`; it never
changes the LXCat source. This option is not an approved Gas1 result path and
its manifest records that status.

The existing scripts in `GasPulse/0D/scripts/` are retained as historical
drivers. They rely on the former machine-local PK1 helper stack and are not
dependencies of the new preflight or run path.
