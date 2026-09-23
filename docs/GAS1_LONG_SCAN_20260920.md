# Gas1 long diagnostic scan

- Run date: 2026-09-20
- Case: 1 atm initial pressure, 400 K, N2/H2 = 1:1, 50 Td on / 0 Td off, 10 kHz, 20% duty, closed 0D, fixed electron density, wall relaxation enabled, surface reactions disabled.

Command:

```powershell
python scripts/run_pulse_case.py `
  --case configs/gas_phase/closed_0d/gas1_T400K_N2-0p5_H2-0p5_P1atm_long_scan.yaml `
  --append-detailed-balance-inverses `
  --output-root run_data/diagnostics/gas1_long_scan_20260920T `
  --max-workers 3
```

The three horizons ran concurrently in isolated directories. Long-run
diagnostics were sampled every 100 cycles (10 ms); initial and final phase
endpoints were always retained. This changes only output volume, not the
integration path.

| Horizon | Cycles | Final NH3 (cm^-3) | Mean NH3 accumulation (cm^-3 s^-1) | DVODE `T+H=T` warnings | Structural checks |
|---:|---:|---:|---:|---:|:---|
| 2000 ms | 20,000 | 1.0626416901e13 | 5.3132084505e12 | 69,567 | pass |
| 5000 ms | 50,000 | 2.7590934615e13 | 5.5181869235e12 | 166,664 | pass |
| 10000 ms | 100,000 | 5.5423397203e13 | 5.5423397200e12 | 328,304 | pass |

The final physical-clock errors were below `6e-10 s`; all three processes
returned code 0. Each produced 467 mean reaction-rate rows and 43 active gas
species. The run manifests are under:

```text
run_data/diagnostics/gas1_long_scan_20260920T/results/2000ms/manifest.json
run_data/diagnostics/gas1_long_scan_20260920T/results/5000ms/manifest.json
run_data/diagnostics/gas1_long_scan_20260920T/results/10000ms/manifest.json
```

## Numerical status

The runner now treats a nonzero DVODE warning count as a failed numerical
quality gate, even when the vendor solver continues and returns code 0. The
three horizons therefore have `dvode_audit.accepted = false`; they are
diagnostic trajectories, not convergence-certified results.

The short tests showed why warning suppression is not an acceptable fix:
restarting at every substep or changing to a phase-local solver time reduced
some warnings but shifted the 1 ms NH3 endpoint by roughly 1--6%. The current
implementation keeps physical time, applies `SOFT_RESET` only at the two
field discontinuities, records every warning, and refuses to label the long
scan numerically accepted.

The long-run envelope is approximately linear after the initial transient:
the mean NH3 accumulation rises from `5.313e12` cm^-3 s^-1 at 2 s to
`5.542e12` cm^-3 s^-1 at 10 s. This is useful for debugging and trend
inspection only until a solver/mechanism sensitivity study removes the
warning-driven uncertainty.

The BOLSIG database remains a case-local detailed-balance diagnostic
construction, not an approved Gas1 cross-section result. The existing
cross-section and mechanism caveats therefore still apply independently of
the numerical warning gate.
