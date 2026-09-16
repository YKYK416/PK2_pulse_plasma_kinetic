# Results status and interpretation

## Accepted dataset

The tracked numerical dataset is the `attempt_02` closed-0D rescue series at 10, 50, 100, and 200 ms, plus the plotted analyses. The 100 and 200 ms manifests record successful return code `0`, exact requested final times, and accepted phase/time/density checks. The 10 and 50 ms CSVs were independently checked after completion; their original launcher did not finish its manifest because Windows returned empty captured standard text after a successful child run.

The modified long-time configuration was introduced after an earlier 10/50 ms run encountered DVODE step-size stagnation. It changes solver controls only, not the chemistry, temperature, feed composition, fixed electron density, field waveform, or surface-reaction status.

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

## CSTR exploratory attempt: not an accepted result

The project contains a first pulsed CSTR implementation for `tau = 50 ms`. It retains the generated `ZDPlasKin_set_cstr_flow(tau_res, feed_density)` call, so the CSTR source is intended to be coupled into the heavy-species RHS; fixed electrons, algebraic third bodies, and surface states are excluded from the flow mask. The input waveform is still 10 kHz / 50% duty cycle, i.e. 50 microseconds on and 50 microseconds off.

The CSTR build succeeded, but its initial run stalled before creating a `pulse_series` CSV and consumed no measurable CPU after BOLSIG initialization. It was deliberately stopped and is not part of the repository's tracked data. The driver should be diagnosed with a small, foreground smoke test before any long CSTR calculation is attempted.

## Data-use guidance

- Use the tracked CSV values for closed-0D NH3 time-history and phase-endpoint analysis.
- Treat the figures as envelope plots, not sub-period time-resolved profiles.
- Do not compare the closed-0D concentrations to a CSTR outlet concentration without adding and validating the flow boundary.
- Generated compiler/runtime files are excluded so the repository remains reviewable and portable; the required external Hong/ZDPlasKin runtime is documented in the project README.
