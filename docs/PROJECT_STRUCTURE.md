# Project structure and data policy

## Purpose

This repository separates a reproducible plasma-kinetic study definition from
the large, machine-local outputs that it produces.  It is designed for four
model families:

| Mechanism | Reactor model |
| --- | --- |
| Gas phase | Closed 0D |
| Gas phase | 0D CSTR |
| Surface assisted | Closed 0D |
| Surface assisted | 0D CSTR |

Mechanism selection, reactor boundary, pulsed electric field, feed, and solver
settings belong to a case configuration.  The Python/Fortran driver-generation
logic and plotting primitives should remain shared rather than copied for each
model family.

## Version-control policy

The following are committed:

- `configs/`: declarative case inputs;
- `mechanisms/*/mechanism.yaml` and mechanism-source documentation;
- `src/`, `scripts/`, and `studies/`: shared implementation and reproducible
  analysis plans;
- `docs/` and a deliberately selected small set of final figures in
  `docs/figures/`.

The following are local and ignored:

- `run_data/`: generated build directories, native runtime files, raw CSVs,
  logs, and manifests for potentially numerous cases;
- `generated_figures/`: figures produced in bulk from plot recipes.

An accepted result may be summarized in a committed study document, but raw
outputs stay local unless there is a specific review or archival reason to add
them.

## Case identity

Every runner should derive a stable case ID from the resolved configuration and
the mechanism hash.  The ID should include readable physical fields and a short
configuration hash, for example:

```text
gas-closed0d-T300-N2_0p1-H2_0p9-EN140-f10k-d50-t200ms-8f3c1a
surface-cstr-T300-N2_0p1-H2_0p9-EN140-f10k-d50-tau50ms-2d91be
```

The local output location is therefore:

```text
run_data/<mechanism-id>/<reactor-id>/<case-id>/
├── build/
├── runtime/
├── results/
├── logs/
└── manifest.json
```

`manifest.json` must record the fully resolved configuration, mechanism hash,
toolchain version, command exit status, and validation result.  It is the link
between an ignored local calculation and its committed configuration.

## Configuration composition

`configs/common/` contains reusable pulse and solver settings.  A concrete
configuration under `configs/<mechanism>/<reactor>/` names its mechanism and
reactor boundary and references those common components.  Until a configuration
loader is implemented, the YAML `includes` values document that intended merge;
the concrete file still states all scientifically important fields.

## Plotting policy

Plotting code should be split into shared readers/styles/primitives and small
versioned recipe files.  A recipe identifies the input case manifests, selected
variables and phases, groupings, axes, and output names.  It must not rely on
an unrecorded hard-coded local output path.

Use a custom Python script only when a plot needs scientific transformation that
cannot be expressed by a recipe.  Generated images default to
`generated_figures/<study-id>/`; copy only publication-ready or documentation
figures to `docs/figures/` when they should be tracked.

## Legacy snapshot

`GasPulse/0D/` is preserved without relocation in this first organization
step.  It contains the accepted gas-phase closed-0D rescue trajectories and
the scripts that produced them.  Those scripts have external, machine-specific
ZDPlasKin paths and should be migrated into the shared runtime only after the
two mechanism sources and target ZDPlasKin environment are available.
