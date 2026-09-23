# Results status and interpretation

## Accepted dataset

The tracked numerical dataset is the `attempt_02` closed-0D rescue series at 10, 50, 100, and 200 ms, plus the plotted analyses. The 100 and 200 ms manifests record successful return code `0`, exact requested final times, and accepted phase/time/density checks. The 10 and 50 ms CSVs were independently checked after completion; their original launcher did not finish its manifest because Windows returned empty captured standard text after a successful child run.

The modified long-time configuration was introduced after an earlier 10/50 ms run encountered DVODE step-size stagnation. It changes solver controls only, not the chemistry, temperature, feed composition, fixed electron density, field waveform, or surface-reaction status.

The current runner records the vendor DVODE `T + H = T` roundoff warning
count in every horizon manifest and refuses to call a horizon numerically
accepted when that count is nonzero. These messages are emitted by DVODE with
the explicit text that it will continue, so they are not equivalent to a
negative solver return; they are nevertheless a failed numerical-quality gate
for long-time trend claims until a tolerance/step-size sensitivity study
passes. The current 1 ms/1000 ms reference trajectories still contain such
warnings, so their absolute concentrations and linearity remain diagnostic.

## What the figures show

The figures sample a common pulse phase: the initial condition and each afterglow-end point (`phase = 2`). This is a stroboscopic trajectory. It suppresses the 50 microsecond on/off-scale modulation in favor of the slow accumulation envelope.

The 200 ms per-cycle data demonstrate that the pulse phases are not chemically identical. At cycle 2000:

| Quantity | Change in NH3 (cm^-3) |
| --- | ---: |
| 50 microsecond discharge | `+1.50e11` |
| 50 microsecond afterglow | `+8.30e11` |
| Complete 100 microsecond period | `+9.80e11` |

During the last 100 simulated periods, the mean relative NH3 increase was about `3.60e-4` per period. Hence the closed 0D system has not reached a periodic limit cycle at 200 ms: both half-periods still add net NH3, and there is no material outlet to balance the source.

## Model boundary

For a heavy gas species the closed model is simply

\[
\frac{dn_i}{dt}=\omega_i.
\]

A gas-phase CSTR would instead introduce inlet/outlet coupling,

\[
\frac{dn_i}{dt}=\omega_i+\frac{n_{\mathrm{feed},i}-n_i}{\tau}.
\]

Only the latter can generally approach a phase-consistent periodic reactor state under a repeated pulse, subject to convergence checks. It is not valid to infer a CSTR steady state from the present closed-reactor series.

## CSTR diagnostic scan: not numerically accepted

The shared runner now supports a case-local gas-heavy-species CSTR source and
Jacobian patch. The production scan applies the linear flow term with an
exact exponential map in Strang-split chemistry substeps. The equivalent
continuous source has the form
`ZDPlasKin_set_cstr_flow(tau_res, feed_density)`, with fixed electrons and
surface states excluded from the flow mask. A complete Gas1 scan at
`tau_res = 1 ms` is recorded in `docs/GAS1_CSTR_TAU1MS_SCAN_20260921.md`.

The baseline CSTR scan completed all requested horizons with return code `0`
and valid phase/time/species/rate structures, but every horizon still emitted
DVODE `T + H = T` warnings. It is therefore a diagnostic CSTR result, not a
numerically accepted steady-state dataset.

The warning mechanism was then isolated to the DVODE non-negative
bound-retraction path for low-density states. A separate case-local
`positive_unbounded` diagnostic mode now evaluates rates on a non-negative
trial state, allows DVODE to avoid the machine-precision retraction loop, and
projects accepted states back to the non-negative domain. The complete
1–10,000 ms CSTR scan under that mode has zero `T + H = T` messages, zero
solver errors, and no negative sampled endpoints; its NH₃ plateau is about
`1.54476e8 cm^-3`. Because this changes the numerical trajectory relative to
the bounded baseline, it is a warning-free diagnostic sensitivity run, not yet
a mechanism-certified replacement. A native positivity-preserving integrator
or an independent solver comparison is still required for certification.

The seven condition-scan points that still failed in the scalar positive mode
were recovered with a separate `positive_radical_floor_unbounded` diagnostic
mode. It combines the non-negative trial-state projection with relaxed
per-species absolute tolerances for low-density excited, radical, ionic, and
surface states, and uses `n_sub_on=240`, `n_sub_off=160`. All seven recovery
runs reached 1000 ms with zero DVODE errors, zero `T + H = T` warnings, valid
species/rate structures, and no negative sampled endpoints. This improves
solver robustness but remains a numerical diagnostic, not a certification of
absolute concentration accuracy.

## Data-use guidance

- Use the tracked CSV values for closed-0D NH3 time-history and phase-endpoint analysis.
- Treat the figures as envelope plots, not sub-period time-resolved profiles.
- Do not compare the closed-0D concentrations to a CSTR outlet concentration without adding and validating the flow boundary.
- Generated compiler/runtime files are excluded so the repository remains reviewable and portable; the required external Hong/ZDPlasKin runtime is documented in the project README.
