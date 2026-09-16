# PK2 pulse-plasma kinetic simulations

This repository records a focused 0D plasma-kinetic study of square-wave pulsed ammonia synthesis using the Hong gas-phase mechanism. It currently contains the reproducible local drivers, validated closed-reactor trajectories, and the figures derived from those trajectories.

## Current verified scope

The accepted results are for a **closed, zero-dimensional, pure-gas reactor**. The model is deliberately limited to gas-phase chemistry:

- Hong gas-phase mechanism: 48 species and 469 reactions.
- Surface reactions disabled.
- Initial gas: `x(N2) = 0.1`, `x(H2) = 0.9`, `Tgas = 300 K`.
- Fixed electron density: `1.17e8 cm^-3`.
- Square-wave reduced electric field: 140 Td during discharge and 0 Td in afterglow.
- Frequency: 10 kHz, so one period is 100 microseconds.
- Duty cycle: 0.5, therefore `t_on = 50 microseconds` and `t_off = 50 microseconds`.

The closed-reactor model has no inlet, outlet, wall loss, or surface chemistry. Consequently, it is appropriate for studying early-time pulsed gas-phase accumulation, but it does **not** have a CSTR-style material steady state.

## Validated closed-0D data

The long-time trajectories use the stabilized integration configuration `ATOL = 1e8 cm^-3`, `RTOL = 1e-4`, `MXSTEP = 500000`, with 48 discharge and 32 afterglow substeps per pulse. Each listed trajectory passed its endpoint/time/phase validation.

| Horizon | Number of periods | Final NH3 concentration (cm^-3) |
| ---: | ---: | ---: |
| 1 ms | 10 | `7.69698e13` |
| 10 ms | 100 | `4.19398e14` |
| 50 ms | 500 | `1.02479e15` |
| 100 ms | 1000 | `1.68116e15` |
| 200 ms | 2000 | `2.77599e15` |

The 10--200 ms raw endpoint trajectories and per-cycle summaries are versioned in `GasPulse/0D/squarewave_T300K_N2-0p1_H2-0p9_EN140Td_f10kHz_d50/time_scan_rescue_20260912/`. PNG figures are in the matching `analysis/` directory.

## Repository layout

```text
GasPulse/0D/
├── scripts/                         # run and plotting drivers
├── squarewave_.../analysis/         # generated NH3 figures
└── squarewave_.../time_scan_.../    # accepted CSV trajectories and manifests
docs/
└── RESULTS_AND_LIMITATIONS.md       # interpretation, data status, and known limitations
```

Build products, DLLs, compiler objects, BOLSIG runtime files, execution logs, and interrupted calculations are intentionally excluded through `.gitignore`.

## Running the local workflow

The scripts were developed on Windows and expect the local Hong/ZDPlasKin helper stack already available in the author's wider workspace. In particular, `run_square_wave_0d.py` refers to a local Hong runtime/tool directory and a mechanism file; these external paths are not included in this repository. The archived accepted CSV files therefore remain the canonical data for this snapshot.

With those prerequisites available, a local Python environment can run the baseline driver and the rescue time scan, for example:

```powershell
& 'E:\software\Anaconda\python.exe' 'GasPulse\0D\scripts\run_square_wave_0d.py'
& 'E:\software\Anaconda\python.exe' 'GasPulse\0D\scripts\run_time_scan_rescue.py' --horizon-ms 100
```

Do not run these commands in an existing result directory: the scripts intentionally refuse to overwrite previous attempts.

## CSTR status

An exploratory pulsed CSTR driver for `tau = 50 ms` is included as `run_square_wave_cstr_tau50ms.py`. Its CSTR source-term wiring compiled and passed static checks, but the first runtime attempt stalled before producing a first time-series endpoint. It is not represented as a scientific result and is excluded from the tracked data. See [the limitations note](docs/RESULTS_AND_LIMITATIONS.md) before using or extending it.

## Reproducibility and reporting notes

- The trajectory figures use the initial point plus the end of each afterglow (`phase = 2`), so they show the cycle-to-cycle envelope rather than the within-period waveform.
- In the closed reactor, NH3 increased during both the discharge and afterglow in late simulated cycles; a monotonic envelope does not imply absence of pulsed electron-energy modulation.
- Do not describe the current results as CSTR, surface-assisted chemistry, energy efficiency, or a periodic steady state.
