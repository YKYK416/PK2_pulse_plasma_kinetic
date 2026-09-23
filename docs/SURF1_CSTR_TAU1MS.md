# Surf1 surface-assisted CSTR time scan

## Model

Surf1 reuses the Gas1 CSTR boundary condition and activates the project-managed
surface mechanism:

\[
\frac{dn_i}{dt}=\omega_i+\frac{n_{i,\mathrm{feed}}-n_i}{\tau_{\mathrm{res}}},
\qquad i\in\text{gas-heavy species},
\]

\[
\frac{dn_s}{dt}=\omega_s,
\qquad s\in\{\mathrm{Surf},\mathrm{HSurf},\mathrm{NSurf},\mathrm{NHSurf},\mathrm{NH2Surf}\}.
\]

Electrons are prescribed and surface states are excluded from the CSTR flow
mask. Surface chemistry therefore couples back to the gas phase through the
native reaction source terms, while the site states remain in the reactor.

## Gas1-matched condition

| Item | Setting |
|---|---:|
| Temperature | 400 K |
| Pressure | 1 atm |
| Feed | N2:H2 = 1:1 |
| Reduced field | 50 Td on / 0 Td off |
| Frequency | 10 kHz |
| Duty cycle | 20% |
| Electron density | 1.17e8 cm^-3, prescribed |
| CSTR residence time | 1 ms |
| Surface site density | 2.91234567901235e17 cm^-3 |
| Initial surface state | Surf = site density; other surface states = 0 |
| Scan horizons | 1, 10, 50, 100, 200, 500, 1000, 2000, 5000, 10000 ms |

The site density is the `Tot_sur = 1e15` value in the mechanism converted by
the source convention `0.5*V/(A*roughness)` using `V = 48.6`, `A = 3370`, and
`roughness = 2.1`.

## Files and command

Configuration:

`configs/surface_assisted/cstr/surf1_T400K_N2-0p5_H2-0p5_P1atm_tau1ms_scan.yaml`

The four mechanism auxiliary files are now checked in beside
`mechanisms/surface_assisted/kinet_source.txt`; the runner stages them into
each build and each horizon directory. Run:

```powershell
python scripts/run_pulse_case.py `
  --case configs/surface_assisted/cstr/surf1_T400K_N2-0p5_H2-0p5_P1atm_tau1ms_scan.yaml `
  --append-detailed-balance-inverses `
  --output-root run_data/surf1_cstr_tau1ms_scan `
  --max-workers 3
```

The four required files are:

- `REACTION_E_IN.DAT`
- `REACTION_E_BASIS.DAT`
- `ENTROPY_PARA_IN.DAT`
- `ENTROPY_INFO_BASIS.DAT`

## Parameter-file provenance

The historical PK1 locations referenced by the legacy scripts
(`F:\\Codex\\PK1` and `F:\\Codex\\PK1\\Hong`) are not present on this
machine. The corresponding public upstream is
[`wwwccttoo/DFT-microkinetic`](https://github.com/wwwccttoo/DFT-microkinetic),
under `Model_SA_Const_Entropy_base`; all four Surf1 files were recovered from
that directory and match the local PK3 copies byte-for-byte by SHA-256:

- [`REACTION_E_IN.DAT`](https://github.com/wwwccttoo/DFT-microkinetic/blob/main/Model_SA_Const_Entropy_base/REACTION_E_IN.DAT)
- [`REACTION_E_BASIS.DAT`](https://github.com/wwwccttoo/DFT-microkinetic/blob/main/Model_SA_Const_Entropy_base/REACTION_E_BASIS.DAT)
- [`ENTROPY_PARA_IN.DAT`](https://github.com/wwwccttoo/DFT-microkinetic/blob/main/Model_SA_Const_Entropy_base/ENTROPY_PARA_IN.DAT)
- [`ENTROPY_INFO_BASIS.DAT`](https://github.com/wwwccttoo/DFT-microkinetic/blob/main/Model_SA_Const_Entropy_base/ENTROPY_INFO_BASIS.DAT)

This resolves the missing-file issue from the GitHub upstream; the historical
PK1 local directory itself remains unavailable.

The runner refuses to create a native build when any of these files is absent;
they contain mechanism parameters and must not be replaced with placeholders.
The build also applies a narrow compatibility patch after the vendor
preprocessor: two 21-value entropy `READ` statements are split into Fortran
continuation lines, and the surface rate subroutine explicitly imports the
shared `density` array. This addresses the Windows preprocessor's 256-character
line truncation without changing the reaction source or parameter values.
The generated surface-rate routine reads the four auxiliary files once per
executable and reuses the raw arrays on subsequent RHS evaluations; this
removes repeated filesystem I/O during the time scan while preserving the
upstream temperature-dependent formulas.
The Surf1 scan profile also uses the recovered stable settings
`n_sub_on=96`, `n_sub_off=64`, and
`positive_radical_floor_unbounded`; the original 48/32 profile reached a
DVODE corrector-convergence failure near 10 ms.
Each horizon is written under `results/<horizon>ms/`, including
`pulse_summary.csv`, `species_endpoints.csv`, `surface_endpoints.csv`, and
`mean_reaction_rates.csv`.
