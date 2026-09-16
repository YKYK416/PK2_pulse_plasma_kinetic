# Mechanism registry

Each mechanism family has a small versioned metadata file.  The metadata makes
the selected chemistry explicit even when the corresponding `kinet.inp` is
stored outside Git because of size, licensing, or controlled provenance.

Before executing a case, fill `source_file` and `sha256` from the local,
reviewed mechanism file.  A runner must reject a case whose runtime mechanism
does not match that hash.  The surface-assisted mechanism must additionally
declare and initialize its surface sites; gas-phase cases must keep all surface
reactions disabled.
