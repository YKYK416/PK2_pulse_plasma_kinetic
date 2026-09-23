# Gas1 CSTR scan at 1 ms residence time

## Case

- Reactor: gas-phase 0D CSTR
- Residence time: `tau_res = 1.0 ms`
- Pressure/feed: `1 atm`
- Feed and initial temperature: `400 K`
- Feed composition: `N2:H2 = 1:1`
- Pulse: `50 Td / 0 Td`, `10 kHz`, `20% duty`
- Wall relaxation: enabled
- Surface reactions: disabled
- Fixed electron density: `1.17e8 cm^-3`
- Parallel horizons: `1, 10, 50, 100, 200, 500, 1000, 2000, 5000, 10000 ms`

The CSTR term is implemented in the case-local generated ZDPlasKin module. In
the baseline scan it is applied directly in the RHS and in the diagonal
Jacobian. The equivalent continuous source is

\[
\frac{dn_i}{dt}=\omega_i+\frac{n_{i,\mathrm{feed}}-n_i}{\tau_{\mathrm{res}}},
\]

for gas-heavy species only. Electrons and surface states are excluded from the
flow mask. The feed contains N2 and H2 only; the other gas-heavy feed densities
are zero.

## Scan result

All native processes returned code `0`, and all phase/time/species/rate
structure checks passed. The DVODE quality gate did not pass at any horizon
because the solver emitted `T + H = T` warnings.

| Horizon (ms) | Cycles | Final NH3 (cm^-3) | DVODE warnings | Numerical gate |
|---:|---:|---:|---:|:---:|
| 1 | 10 | 2.0751681e7 | 38 | diagnostic |
| 10 | 100 | 1.7239728e8 | 628 | diagnostic |
| 50 | 500 | 1.7255171e8 | 3,328 | diagnostic |
| 100 | 1,000 | 1.7218085e8 | 6,728 | diagnostic |
| 200 | 2,000 | 1.7112201e8 | 13,438 | diagnostic |
| 500 | 5,000 | 1.7237544e8 | 33,773 | diagnostic |
| 1,000 | 10,000 | 1.7208245e8 | 67,383 | diagnostic |
| 2,000 | 20,000 | 1.7139176e8 | 133,723 | diagnostic |
| 5,000 | 50,000 | 1.7360643e8 | 335,259 | diagnostic |
| 10,000 | 100,000 | 1.7320802e8 | 669,100 | diagnostic |

The concentration quickly approaches an order of `1.7e8 cm^-3` outlet value,
which is qualitatively different from the unbounded NH3 growth of the closed
0D calculation. This is the expected consequence of the 1 ms inlet/outlet
turnover, but the absolute value remains diagnostic until the DVODE warning
problem is resolved.

## Numerical remediation run

The warning source was isolated to DVODE's non-negative bound-retraction loop:
when a low-density state is close to zero, repeated trial-step reductions can
reach machine precision even though DVODE returns successfully. A separate
diagnostic mode, `species_tolerance_mode: positive_unbounded`, removes that
retraction loop, evaluates chemistry and flow rates on a non-negative trial
state, and projects the accepted state back to the non-negative domain. It is
not silently substituted into the baseline case because it changes the
trajectory and therefore requires its own sensitivity evidence.

The full scan was rerun with phase-local solver time and this mode. All ten
horizons returned code `0`, had zero solver errors, zero `T + H = T` messages,
and no negative sampled species endpoint:

| Horizon (ms) | Final NH3 (cm^-3) | DVODE warnings | Negative sampled endpoints |
|---:|---:|---:|---:|
| 1 | 2.1182890e7 | 0 | 0 |
| 10 | 1.5436440e8 | 0 | 0 |
| 50 | 1.5447506e8 | 0 | 0 |
| 100 | 1.5447566e8 | 0 | 0 |
| 200 | 1.5447603e8 | 0 | 0 |
| 500 | 1.5447588e8 | 0 | 0 |
| 1,000 | 1.5447576e8 | 0 | 0 |
| 2,000 | 1.5447591e8 | 0 | 0 |
| 5,000 | 1.5447552e8 | 0 | 0 |
| 10,000 | 1.5447618e8 | 0 | 0 |

Reproduction configuration and output root:

`configs/gas_phase/cstr/gas1_T400K_N2-0p5_H2-0p5_P1atm_tau1ms_positive_unbounded_scan.yaml`

`run_data/diagnostics/gas1_cstr_tau1ms_positive_unbounded_scan_20260921T`

Run command:

```powershell
python scripts/run_pulse_case.py `
  --case configs/gas_phase/cstr/gas1_T400K_N2-0p5_H2-0p5_P1atm_tau1ms_positive_unbounded_scan.yaml `
  --append-detailed-balance-inverses `
  --output-root run_data/diagnostics/gas1_cstr_tau1ms_positive_unbounded_scan_20260921T `
  --max-workers 3
```

These values demonstrate a warning-free, nearly time-invariant CSTR trajectory
under the positivity-filtered diagnostic integrator. They do not replace the
baseline table as a certified mechanism result until the positivity treatment
has been independently sensitivity-checked against an integrator with native
positivity support.

## Reproducibility

Configuration:

`configs/gas_phase/cstr/gas1_T400K_N2-0p5_H2-0p5_P1atm_tau1ms_scan.yaml`

Run command:

```powershell
python scripts/run_pulse_case.py `
  --case configs/gas_phase/cstr/gas1_T400K_N2-0p5_H2-0p5_P1atm_tau1ms_scan.yaml `
  --append-detailed-balance-inverses `
  --output-root run_data/diagnostics/gas1_cstr_tau1ms_scan_20260921T `
  --max-workers 3
```

The output root contains the build manifest, case-local patched module, and
one isolated result directory per horizon. The build manifest records
`PK2_CSTR_FLOW_PATCH_V2_RHS_WITH_EXACT_MAP_API` and the feed/residence-time
parameters. The baseline command above uses the scalar bounded solver; the
warning-free diagnostic run uses the separate configuration listed above.
