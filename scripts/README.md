# Commands and plotting recipes

This directory is reserved for thin command-line entry points and versioned
plot recipes.  Shared simulation, validation, CSV-reading, and plotting logic
belongs in `src/pk2_pulse/` rather than being duplicated in each command.

The existing scripts in `GasPulse/0D/scripts/` are retained as legacy drivers
until their external ZDPlasKin dependencies are made configurable.
