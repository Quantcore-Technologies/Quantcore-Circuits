# Python library

`quantcore_circuits` is the Python package behind everything else in this repository: the command line `qcc`, the
KLayout plugin and the dashboard all call it. You use it directly when you design in a script or a notebook, or when
you want to change a step of the flow. The package is a thin layer over KQCircuits (geometry, routing, solver export),
Quantum Metal (LOM) and the quantisation libraries.

Start with [the Designer API](designer.md); it covers most of what a script needs. The table below says what each
part of `src/quantcore_circuits/` is for.

## Package map

| Part | What it is for | Main entry points | Page |
|---|---|---|---|
| `designer.py` | Build a chip in Python, live in KLayout | `Designer`, `Designer.add`, `.route`, `.sim_subset`, `.drc`, `.lom` | [Designer](designer.md) |
| `design/` | The `design.json` model: schema `qcc/0.1`, loading, hashing, `design.py` round trip | `load_design`, `Design` | [Routing and DRC](routing-drc.md) |
| `layouts/` | The component library: Quantcore cells, the KQC and Quantum Metal registry, wafers and fab export | `resolve_cell`, `catalog`, `export_fab` | [Components](components.md), [Fab export](fab.md) |
| `layouts/others/flip_chip.py`, `sim_tools/` | Flip-chip and TSV designs: cells, faces, per-face DRC, multi-face sim export | `CpwTsvTransition`, `QcFlipChipConnectorRf` | [Flip-chip and TSV](flip-chip.md) |
| `pdk/` | The Quantcore process: stack, layers, die frame, keep-outs, cheese, junction process | `get_pdk`, `Pdk` | [PDK](pdk.md) |
| `assembly/` | `design.json` into a KQC chip: snaps, routing, pad rule, DRC, netlist, sidecar | `build`, `write_layout`, `drc.check` | [Routing and DRC](routing-drc.md) |
| `route/` | Route plans into waveguides and meanders, with length fixing | `router.fix_length` | [Routing and DRC](routing-drc.md) |
| `lom/` | Layout to lumped circuit, LOM simulation, targets to layout | `lom_from_design`, `simulate.simulate`, `synthesize` | [LOM](lom.md) |
| `circuit/` | The `circuit.json` model, filling it with results, estimators, consensus, Hamiltonians | `fill.fill`, `consensus` | [LOM](lom.md), [Results](results.md) |
| `analysis/` | Parameter extraction: Metal LOM, pyEPR, scqubits, QuCat, SQcircuit, QuTiP; results parsing and store | `results.collect_results` | [Results](results.md) |
| `sim_tools/` | Sim groups, job export (Q3D, HFSS, Elmer, Palace, Sonnet), the AEDT driver, runners | `export.export_job`, `hfss.render`, `hfss.solve_job` | [Simulation](simulation.md) |
| `loop.py`, `codesign.py`, `optimise.py` | The analysis half of the loop: consensus, surrogate, proposals, new revision | `loop.analyse`, `loop.feedback`, `codesign.propose` | [Feedback](feedback.md) |
| `guiflow.py` | The plugin's Simulate, Results and Fab steps as functions | `plan_subset_groups`, `selection_group` | [Plugin flow strip](../plugin/flow-strip.md) |
| `live/` | klive client, design file watcher, headless and GUI snapshots | `snapshot`, `gui_snapshot` | [KLayout scripts](../plugin/klive.md) |
| `review/`, `track.py`, `autotrack.py`, `cards.py` | The dashboard server and the run state it shows | `review.connect`, `track.start` | [Dashboard](../overview/dashboard.md) |
| `plots.py` | Plot helpers and PlotSpec builders shared with the dashboard | `use_style`, `plot_spec` | [Results](results.md) |
| `plugins.py` | Extension points for extra solvers and analyses (Python entry points) | `AnalysisPlugin` | [Simulation](simulation.md) |
| `cli.py` | The `qcc` command | `qcc --help` | [CLI reference](../reference/cli.md) |

The full list of functions and classes is in the [Python API reference](../reference/python-api.md).

```{toctree}
:maxdepth: 1
:hidden:

designer
components
custom-components/index
flip-chip
pdk
routing-drc
lom
simulation
results
epr
feedback
fab
wafer
```
