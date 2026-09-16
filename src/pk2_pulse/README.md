# Shared implementation

Future reusable modules belong here: configuration loading, mechanism
provenance checks, closed-0D/CSTR driver construction, runtime invocation, CSV
validation, and common plotting primitives.  Do not add a second copy of those
functions under each mechanism or reactor directory.

No legacy driver has been moved yet because the current drivers depend on a
machine-local ZDPlasKin/Hong runtime and the surface mechanism is not present
in this repository.
