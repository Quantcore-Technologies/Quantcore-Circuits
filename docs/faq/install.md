# Install and environments

Questions about setting the project up, and about the files and programs it expects to find. The steps themselves are
on [Getting started](../getting-started.md).

## Environments

### How do I install it?

From PyPI, in a Python 3.11 or newer environment. Install the CPU build of PyTorch first (SQcircuit needs it), then the
package:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install "quantcore-circuits[all]"
qcc kqc-files
qcc selftest
```

`qcc kqc-files` fetches KQCircuits' simulation scripts and label font once (a few seconds, from the KQCircuits release on GitHub): the `kqcircuits` package on PyPI does not include them, and the HFSS / Q3D / Elmer export and KQC's chip-frame labels need them.

The KLayout plugin installs through KLayout's package manager (Salt, package `quantcore-circuits`). See
[Getting started](../getting-started.md).

### Which environments do I need?

One for the library, the `qcc` command, the notebooks and the plugin's calls. Building these docs is a separate matter:
the docs tools live in their own environment so they never change the tested versions. Do not install the docs
requirements into the library environment. See [Building these docs](docs.md).

### Can I install without internet?

Yes. Build the wheel and an offline wheelhouse on a machine with internet (`python scripts/build_wheel.py`,
`python scripts/build_wheelhouse.py`), copy it over and install from it. This is also useful for whole-chip LOM runs on
a bigger machine. See [the simulation PC page](../overview/simulation-pc.md).

### Do I need the `build/` folder?

No. `build/` is generated output (layouts, job folders, run state) and is git-ignored. Do not wipe it casually: kept FEM
results live there. The golden comparison tests against the legacy reference chips skip when that reference folder is
absent.

## Programs

### Which AEDT version do I need?

AEDT 2024 R1 (v241) or newer, only for HFSS and Q3D. The library finds it through `QCC_ANSYS_EXECUTABLE`, then the usual
install folders. Everything else (design, DRC, LOM, notebooks with `RUN_FEM = False`) runs without AEDT. See
[Simulation](simulation.md).

### Which KLayout version?

KLayout 0.30.5; the matching Python package `klayout==0.30.5` comes with the library. If KLayout is not found, set
`QCC_KLAYOUT` to `klayout_app.exe`. See [Getting started](../getting-started.md).

### Which environment variables matter?

| Variable | Effect |
|---|---|
| `QCC_LIVE=0` | The tutorials and design notebooks run headless: they do not push to or open KLayout (default `1`: live when KLayout answers) |
| `QCC_KLAYOUT` | Path of `klayout_app.exe` when it is not found |
| `KLAYOUT_HOME` | KLayout's settings folder (default `~/KLayout`); `open_klayout()` looks for the plugin's Salt link there, and loads the plugin straight from the repository when the link is missing |
| `QCC_ANSYS_EXECUTABLE` | The AEDT executable to use, any version |
| `QCC_AEDT_MODE` | Default AEDT mode: `batch`, `gui` or `attach` |
| `QCC_FEM_FAST=1` | Fast solver settings for every export |
| `QCC_TRACK=1` | Feed the dashboard from a notebook or script |
| `OPENBLAS_NUM_THREADS=2` | Set before starting Jupyter on a small PC so numerical libraries do not take every core |

### Why does a notebook say `qcc` or KLayout is missing?

Activate the env first (`conda activate qcd`), so `qcc` is on PATH. The plugin also looks for `qcc` in the `qcd` env
by itself. See [the plugin](klayout-plugin.md).
