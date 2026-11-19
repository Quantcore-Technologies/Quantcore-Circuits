# Contributing

Thank you for helping with quantcore-circuits. This guide covers the dev setup, the tests, the docs build and how to
send a change. Paths are from the repository root.

## Set up a checkout

You need Python 3.11 or newer (a conda or venv environment) and git.

```bash
git clone https://github.com/Quantcore-Technologies/Quantcore-Circuits.git
cd Quantcore-Circuits
pip install torch --index-url https://download.pytorch.org/whl/cpu   # SQcircuit (analysis extra) needs PyTorch
pip install -e ".[all,dev]"
qcc kqc-files        # KQCircuits' scripts and font; not needed when kqcircuits is a checkout in editable mode
qcc selftest
```

`all` is `analysis` + `sim` + `notebook`. `dev` is pytest, ruff and pre-commit. `requirements/tested.txt` lists the
exact versions the tests run with.

### Upstream snapshots (optional)

The library depends on KQCircuits, Quantum Metal, SQcircuit, QuCat and PyAEDT. `pip` installs them from PyPI. If you
want their current main branches instead, for example to test against a fix that is not released yet,
`scripts/fetch_other_libs.sh` clones them (shallow) into `third_party/` from their upstream repositories. It takes
optional repository names (`bash scripts/fetch_other_libs.sh klive pyPalace`, or `all`) and honours `KQC_REF`,
`METAL_REF`, `QUCAT_REF` and `SQC_REF` to pin a branch or commit. Install the clones you want with
`pip install -e third_party/<name>` (KQCircuits: `third_party/KQCircuits/klayout_package/python`).

### The dashboard

The live dashboard's source is in `reviewer/` (Vite + React). The built app is tracked in
`src/quantcore_circuits/review/static/`. Only if you change the dashboard:

```bash
cd reviewer && npm install && npm run build
```

## The tests

Run them from the checkout. On a shared machine set `OPENBLAS_NUM_THREADS=2`.

| Tier | Command | What |
|---|---|---|
| fast | `pytest -m "not slow"` | No GUI, no solver. Skips the notebook runs, the full export sweep and the co-design loop |
| slow | `pytest -m slow` | Notebook runs, the full export sweep, the co-design loop. Minutes to hours |
| solver | `pytest -m solver` | Needs `ansysedt`, ElmerSolver or Palace on the PATH; skipped when absent |
| one file | `pytest tests/test_selftest.py -q` | While you work, run only the tests of what you touched |

Tests marked `analysis` are skipped when the analysis stack is missing. `qcc selftest` is the 30-second check of an
install. Some tests need extra local material and skip without it: the legacy components, and the AEDT projects
under `tests/data/aedt_2024r1` (marker `aedt_fixture`; AEDT projects are not kept in git because every AEDT
edition writes its own, and the notebooks make them).

## Style and checks

- Code style is [ruff](https://docs.astral.sh/ruff/) with a line length of 120 (`ruff check src tests`).
- `pre-commit install` runs the checks on every commit.
- Notebooks: `python scripts/check_notebook_api.py NOTEBOOK.ipynb` checks a notebook without running it (the nbformat
  schema, the syntax, every name, every import, and the call signatures against the library). Add `--clean` for
  notebooks that must have no outputs.
- Use the spelling "Quantcore" (lowercase c) in text, UI and docs.

## Build the docs

The docs are Sphinx + MyST in `docs/`. Use a separate environment so the library environment stays as tested.

```bash
pip install -r docs/requirements.txt
QCC_DOCS_FAST=1 sphinx-build -b html docs docs/_build/html -q     # fast: skips the API reference
sphinx-build -b html docs docs/_build/html                        # full: also builds the API reference
```

On Windows set the variable first (`set QCC_DOCS_FAST=1`, or `$env:QCC_DOCS_FAST = "1"` in PowerShell). The fast build
takes seconds; the full build writes `docs/reference/api/` into the source tree while it runs, so use it for the final
check. The generated component and CLI pages come from `python scripts/make_docs.py` (needs the library installed).
More in [docs/hosting.md](docs/hosting.md).

## Work on the KLayout plugin

The plugin is `kplugin/` (a KLayout Salt package; it uses only KLayout's own Python). To try your changes without
installing it, start KLayout with the plugin loaded from the checkout:

```bash
klayout_app -e -rm kplugin/load_dev.py
```

(On Windows `klayout_app.exe`, from KLayout's install folder.) `Designer(..., live=True)` starts KLayout the same way.
`qcc` must be on the PATH, or set in **Quantcore → Settings…**. The plugin's structure and its tests are described in
[kplugin/README.md](https://github.com/Quantcore-Technologies/Quantcore-Circuits/blob/main/kplugin/README.md).

## Issues and pull requests

- Open an issue for a bug or an idea first if the change is large. For a bug, give the `qcc --version`, your operating
  system, and the smallest design or script that shows it.
- Branch from `main`, keep a pull request to one topic, and add or update a test for a behaviour change.
- Make sure `pytest -m "not slow"` and `ruff check src tests` pass, and the docs build has no warnings from the pages
  you touched.
- Open the pull request against `main`.

## License

quantcore-circuits is licensed under GPL-3.0-or-later (it builds on KQCircuits, which is GPL-3.0). By contributing you
agree that your contribution is licensed under the same terms.
