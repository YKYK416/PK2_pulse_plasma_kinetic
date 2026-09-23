# External ZDPlasKin environment

The repository discovers local vendor assets relative to its workspace parent
by default:

```text
../ZDPlasKin_2.0a_Windows/ZDPlasKin_2.0a_Windows/
../bolsigplus072024-win/SigloDataBase-LXCat-04Jun2013.txt
```

The first directory supplies `preprocessor.exe`, `dvode_f90_m.F90`, and the
gfortran-compatible BOLSIG DLL/import library. The second file is a source
database of electron-collision cross sections. A calculation stages a
case-local verbatim copy of the approved source as `bolsigdb.dat`; it does not
commit vendor binaries or generated databases.

Run `scripts/preflight_pulse_case.py` before a simulation. It resolves the
Gas1 configuration, finds the compiler/runtime, hashes the cross-section
source, and audits every `BOLSIG A -> B` process requested by the mechanism.
The runner refuses an unresolved process or a process supplied only in the
opposite direction. Record resolved paths and hashes in each local case
manifest. Never commit generated DLLs, build products, runtime logs, or
machine-specific absolute paths.
