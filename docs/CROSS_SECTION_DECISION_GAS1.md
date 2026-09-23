# Gas1 BOLSIG cross-section decision record

## Status

**Blocked for scientific interpretation: no Gas1 solver run may be treated as
scientifically valid until an approved cross-section audit passes.** The block
applies to the 1-atm, 400-K, N2/H2 = 1:1 closed-0D case with a 50-Td / 0-Td
square-wave pulse.

This is a data-provenance block, not a compiler or Python implementation
block.  The local ZDPlasKin runtime can be discovered and a Fortran driver can
be generated, but neither capability supplies missing electron-collision data.

## Audited inputs

| Item | Project location | Role |
| --- | --- | --- |
| Gas1 case | `configs/gas_phase/closed_0d/gas1_T400K_N2-0p5_H2-0p5_P1atm.yaml` | Requested thermodynamic state and pulse |
| Mechanism | `mechanisms/gas_phase/kinet.inp` | Required `! BOLSIG ...` process labels |
| Candidate source | `../bolsigplus072024-win/SigloDataBase-LXCat-04Jun2013.txt` | LXCat-formatted collision records |
| Audit implementation | `src/pk2_pulse/bolsig.py` | Exact/alias/reverse/missing classification |

Run the audit without creating a build directory:

```powershell
python scripts/preflight_pulse_case.py
```

## Raw-source result

The mechanism requests 40 unique BOLSIG processes.  The bundled candidate
source provides 21 direct matches and 4 deliberately finite typography/case
aliases.  It does not provide an approved record for the remaining 15
mechanism requests:

- 12 are **inverse-only**: the database supplies a forward excitation record,
  while `kinet.inp` requests the corresponding de-excitation process.  They
  are `N2(v1)` through `N2(v8)` to ground-state N2, and the H2 electronic
  states `B3SIG`, `B1SIG`, `C3PI`, and `A3SIG` to ground-state H2.
- 3 are **missing**: `H2(v1) -> H2`, `H2(v2) -> H2`, and `H2(v3) -> H2`.

`src/pk2_pulse/bolsig.py` reports these separately.  An inverse-only label is
not silently promoted to a direct match.

## Diagnostic construction and runtime proof

For engineering diagnosis only, `bolsig.py` can create a new case-local
`bolsigdb.dat` without editing any source forward record. It appends:

- 16 negative-threshold inverse superelastic records, generated with
  `g_upper/g_lower = 1.0` and
  `sigma_inverse(e)=(g_lower/g_upper)*((e+U)/e)*sigma_forward(e+U)`;
- 9 forward compatibility records whose data table is copied unchanged, solely
  to remove source-header threshold suffixes or bridge the historic
  `N2(a'1)`/`N2(a\`1)` typography mismatch.

The 2026-09-20 local 1-ms / 10-cycle diagnostic completed with exit code 0:
the loader reported 18 species and 67 collisions, linked all 41 BOLSIG
requests, and wrote 21 finite CSV endpoint rows ending at 1 ms. The DVODE log
also reports repeated `T + H = T` step-size warnings near pulse transitions.
Therefore this proves data/driver/preprocessor/compiler connectivity only; it
does **not** demonstrate numerical convergence or validate the selected
statistical weights. The exact source and derived SHA-256 values, transforms,
and run output are retained in the diagnostic manifest under
`run_data/diagnostics/gas1_unmodified_bolsig_20260920T120734Z/`.

Use it only by opting in explicitly:

```powershell
python scripts/run_pulse_case.py --append-detailed-balance-inverses --max-workers 3
```

The resulting case manifest is marked `diagnostic_only_not_a_gas1_result`.

## Current diagnostic case boundary

The current Gas1 case is explicitly an **initial-1-atm, constant-volume,
fixed-400-K** calculation. It uses a prescribed, constant electron density
with an implicit stationary neutralizing background; it is not a
self-consistent discharge calculation. `surface_reactions: disabled` is
enforced in the build-local mechanism. The current case retains
`wall_relaxation: enabled`, so its 17 wall-relaxation reactions and their
geometry parameters remain active; only the 37 reactions containing `Surf`
species are removed. The generated mechanism therefore contains 467 reactions
and 43 active gas species.

Each result directory now includes `species_endpoints.csv` for every active
gas species at every pulse endpoint and `mean_reaction_rates.csv` for the
time-averaged rate of every generated reaction. The build also writes
`preprocessor_quality.json`, recording the vendor's duplicate-reaction and
long-Fortran-record warnings rather than silently ignoring them. The local
generated module is patched, with exact anchors, to receive the case's DVODE
`MXSTEP` setting; vendor runtime files are never edited.

These scope and observability improvements do not resolve the cross-section
or convergence blocks above.

## Why this cannot be solved by a filename or text substitution

An excitation cross section is not automatically a validated superelastic
de-excitation cross section.  Constructing the inverse requires a stated
physical convention, including state energies and statistical weights, and
must be consistent with the collision-data format and BOLSIG calculation.
Likewise, an unrelated GitHub mechanism or a differently curated LXCat set
cannot be merged process-by-process without preserving source provenance and
checking every label and threshold.

The project therefore forbids the following shortcuts:

- copying a forward record under a reversed process label;
- treating an inverse-only match as an exact match;
- renaming an arbitrary external collision record to satisfy the audit;
- creating `bolsigdb.dat` by concatenating unreviewed databases;
- presenting a run completed with any of the above as a Gas1 result.

## Permitted paths to unblock

One of the following must be supplied and recorded before an execution is
enabled:

1. The original PK1/Hong `bolsigdb.dat`, accompanied by a mechanism-compatible
   source/provenance record; or
2. an authoritative collision-data source covering all requested processes,
   including explicit inverse-process construction rules, state energies, and
   statistical weights where needed; or
3. an explicitly approved reduced mechanism that removes unsupported BOLSIG
   reactions and documents the scientific implications.

For paths 1 and 2, the candidate database is re-audited.  It is staged
verbatim only when `BolsigAudit.accepted` is true; the staged copy and source
SHA-256 are written to the local run manifest.  Path 3 requires a new versioned
mechanism and its own decision record; it must not overwrite the Hong source.

## Related external-code finding

The public [DFT-microkinetic repository](https://github.com/wwwccttoo/DFT-microkinetic)
is useful for understanding the historical QtPlaskin/ZDPlasKin execution
organization, but its README does not establish that it distributes the exact
N2/H2 collision database required here.  It is therefore a code-reference
source, not an automatically approved cross-section source.  See
[`PK1_RUNTIME_REFERENCE.md`](PK1_RUNTIME_REFERENCE.md).
