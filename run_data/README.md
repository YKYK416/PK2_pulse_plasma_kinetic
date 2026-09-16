# Local simulation data

This directory is created for local case outputs.  It is Git-ignored except for
this file.  A case runner should create:

```text
run_data/<mechanism-id>/<reactor-id>/<case-id>/{build,runtime,results,logs}/
```

Do not place reusable configuration or source code here.  Record enough
provenance in each local `manifest.json` to reproduce or audit the calculation
from the corresponding committed configuration.
