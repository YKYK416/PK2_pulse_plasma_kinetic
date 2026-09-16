# Case configurations

These YAML files define what is to be simulated.  They are intentionally small
and versioned so that large local output directories do not need to be stored
in Git.

The current files define the four target model families and the common 10 kHz,
50% duty, 140 Td pulse.  They are templates for a future configuration loader;
they do not execute ZDPlasKin by themselves.  Only the gas-phase closed-0D
family currently has accepted legacy trajectories.  The gas-phase CSTR setup is
exploratory, and both surface-assisted setups await the controlled surface
mechanism.
