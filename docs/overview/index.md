# The repository

quantcore-circuits is Quantcore's design loop for superconducting-qubit chips. You describe a chip (by drawing it in
KLayout, by writing Python, or by giving frequency targets), and the repository builds the layout, checks it, turns it
into a lumped circuit, prepares and reads back finite-element simulations, tunes the design toward its targets and
exports the mask. It is a thin layer over existing libraries: KQCircuits (geometry, routing, simulation export, AEDT
scripts), Qiskit Metal (lumped models), and QuCat, SQcircuit, scqubits and QuTiP (quantisation).

It has four front ends over one design file (`design.json`): a KLayout plugin, a Python library with the `qcc` command, a
set of notebooks (five tutorials and over a hundred design notebooks) and a web dashboard. The process is niobium on
sapphire, 650 µm thick, εr 10.25 (`quantcore_nb_sapphire_v1`, the default). The package imports KQCircuits, which is
GPL-3.0. Internal use is fine; distributing the package outside Quantcore would make it GPL as well.

New here? Read [getting started](../getting-started.md), then [the flow](flow.md) and [use cases](use-cases.md).

## Top-level folders

| Path | What it holds |
|---|---|
| `src/quantcore_circuits/` | The Python library and the `qcc` command ([library](../library/index.md)) |
| `kplugin/` | The Quantcore KLayout plugin, a Salt package ([plugin](../plugin/index.md)) |
| `reviewer/` | Source of the dashboard: Vite, React, Tailwind. It builds into `src/quantcore_circuits/review/static/` ([dashboard](dashboard.md)) |
| `examples/tutorials/` | Five tutorial notebooks, from a one-qubit chip to the whole loop ([tutorials](../tutorials/index.md)) |
| `examples/designs/` | The design notebooks, one folder per group: `metal`, `kqc`, `qpdk`, `sqdmetal`, `squadds`, `community`, `amplifiers`, `devicelayout`, `google`, `ibm`, `legacy` ([designs](../designs/overview.md)) |
| `examples/` (the rest) | The first-run notebooks `q1_r1_first_run` and `q1_r1_loop`, `lom_from_layout`, small `design.json` files, `custom_component/` (a user-written component), `fem_loop/` ([other examples](../tutorials/other-examples.md)) |
| `docs/` | These pages (Sphinx and MyST, [hosting](../hosting.md)). `docs/images/` holds the pictures the pages use |
| `tests/` | The pytest suite; no GUI or solver needed. `-m "not slow"` skips the notebook runs, the full FEM export sweep and the co-design loop |
| `scripts/` | Helper scripts: `build_wheel.py`, `dashboard.cmd`, `cdp-shot.mjs` (dashboard screenshots), notebook and export checks, generators for the docs, `fetch_other_libs.sh` |
| `assets/` | Logos (the Quantcore and Circuits wordmarks, light and dark) and the plugin tool icons |
| `requirements/` | `tested.txt`: the exact dependency versions the tests run with |
| `build/` | Outputs, git-ignored: layouts (`.oas` with a `.qcc.json` sidecar), `jobs/` (FEM job folders, some with kept results), run state, fab files. Do not wipe it casually |
| `dist/` | The wheel built by `scripts/build_wheel.py`, git-ignored |

### Top-level files

| File | What it is |
|---|---|
| `README.md` | Short overview, install and quick start |
| `CONTRIBUTING.md` | The developer route: checkout, editable installs, tests, conventions |
| `CHANGELOG.md` | What changed in each release |
| `LICENSE` | GPL-3.0-or-later |
| `pyproject.toml` | Package metadata (version 0.2.0, Python 3.11 or later) and the `qcc` entry point |

## Modules and how far they are built

Status: done = built and run for real; partial = built, part unverified or missing; export only = solver input is
written but never solved. The date and the evidence for each row are on [the status page](status.md).

| Module | What it does | Where it lives | Docs | Status |
|---|---|---|---|---|
| KLayout plugin | Place, connect and route components in KLayout; the panel runs the whole flow | `kplugin/` | [plugin](../plugin/index.md) | done; development paused 2026-11-17 |
| KLive scripting | `Designer` calls rebuild and redraw the chip in KLayout live | `designer.py`, `live/` | [KLive](../plugin/klive.md), [Designer](../library/designer.md) | done |
| PDK | Stack, die frame, 100 µm pad rule, keep-outs, cheese, junction process | `pdk/` | [PDK](../library/pdk.md) | done |
| Components | Quantcore, KQC and Metal cells with ports and LOM models | `layouts/` | [components](../library/components.md), [reference](../components/cells/index.md) | done |
| Design file | The `design.json` schema, loading, hashing, export to Python | `design/` | [routing and DRC](../library/routing-drc.md) | done |
| Assembly and routing | Design to KQC chip; Manhattan routes, meanders, hangers | `assembly/`, `route/` | [routing and DRC](../library/routing-drc.md) | done; edge cases open |
| Connectivity DRC | Dangling pins, overlaps, crossings, opens, keep-outs, netlist | `assembly/drc.py`, `assembly/netlist.py` | [routing and DRC](../library/routing-drc.md) | done |
| LOM | Layout to lumped circuit, LOM simulation, targets to layout | `lom/`, `circuit/` | [LOM](../library/lom.md) | done; model gaps |
| Simulation export | Sim-group cut-outs written as HFSS, Q3D, Elmer, Palace jobs | `sim_tools/` | [simulation](../library/simulation.md) | done for Ansys; Elmer and Palace export only |
| HFSS and Q3D driver | Renders and solves jobs in AEDT 2024 R1 or later | `sim_tools/hfss.py` | [simulation](../library/simulation.md) | done with fast settings; no converged run |
| Runner and queue | Solves jobs on a lab server | `sim_tools/runner.py` | [simulation](../library/simulation.md) | partial; unit tests only |
| Results | Parse solver output, fill the LOM, plots | `analysis/`, `plots.py` | [results](../library/results.md) | done for AEDT; plots partial |
| Feedback | Consensus against targets, surrogates, new revisions | `loop.py`, `codesign.py` | [feedback](../library/feedback.md) | partial; one real FEM loop |
| Fab export | Mask file with the QCT layer map | `layouts/wafers/` | [fab export](../library/fab.md) | done; wafer and mask assembly missing |
| Dashboard | Follows a run in the browser | `reviewer/`, `review/`, `track.py` | [dashboard](dashboard.md) | done |
| `qcc` command | Every step from a terminal | `cli.py` | [CLI reference](../reference/cli.md) | done |
| Notebooks | Five tutorials and the design notebooks | `examples/` | [tutorials](../tutorials/index.md), [designs](../designs/overview.md) | tutorials done; see the design pages for each chip |
| Packaging | A wheel for other machines | `scripts/build_wheel.py` | [getting started](../getting-started.md) | partial; never installed fresh |

```{toctree}
:maxdepth: 1
:hidden:

flow
use-cases
dashboard
status
simulation-pc
```
