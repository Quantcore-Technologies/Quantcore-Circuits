# Tutorials

The tutorials are five Jupyter notebooks in `examples/tutorials/`. Each one takes a chip through the whole Quantcore
loop, one small step at a time: PDK, layout, DRC, lumped model (LOM), FEM jobs, results back into the LOM, feedback,
and fab export. Take them in order the first time. Tutorial 0 builds a one-qubit chip from nothing. Tutorials 1 to 3
rebuild existing chips with the library and the Quantcore PDK. Tutorial 4 runs the loop as a loop on two coupled qubits.

The notebooks are saved with their outputs, so you can read them (and these pages) without running anything. The
pages here only describe them; nothing was run to write them.

## What each one teaches

| Tutorial | What you build | What you learn | Needs AEDT? | Run time |
|---|---|---|---|---|
| [0 Quickstart](00-quickstart.md) | One Xmon, a λ/4 readout and a feedline | The PDK, live KLayout, DRC, netlist, LOM, one sim group with three FEM jobs, feedback, fab export | Only to re-solve | about 1 min; with `RUN_FEM = True` add about 3 min (Q3D), 10 to 15 min (eigenmode), 20 to 40 min (driven) |
| [1 Chip 12](01-chip12.md) | A legacy nine-qubit test chip with a direct pair and a tunable-coupler triple | Rebuilding an existing chip in the PDK, `near=` hangers, LOM against legacy targets, J and ZZ, Q3D and eigenmode on a subset | Only to re-solve | about 1 min with the kept FEM results; with `RUN_FEM = True` add about 3 + 5 min Q3D and 5 + 20 min eigenmode |
| [2 IBM bowtie](02-ibm-bowtie.md) | IBM's five-qubit chip: two triangles joined by λ/2 buses | Pocket transmons, buses and tees, J by avoided crossing, stage 1 on a subset and stage 2 on the whole netlist, rendering into AEDT without solving | Only to re-solve or render | about 2 to 3 min; with `RUN_FEM = True` add about 1 + 4 min for the subset |
| [3 Surface 17](03-surface17.md) | Two 17-qubit surface-code chips from one generator | A generator-built chip, airbridges at crossings, per-qubit LOM with its feedline, LOM against a paper's table | Only to re-solve or render | about 3 to 5 min |
| [4 Feedback loop](04-feedback-loop.md) | Two coupled Xmons with two readouts on one feedline | LOM-first synthesis, a LOM loop, FEM minus LOM as feedback, revision 1, "I want f_q1 = X" | Only to re-solve | about 2 to 4 min; with `RUN_FEM = True` about 25 min per FEM iteration |

Run times are the ones in `examples/tutorials/README.md` (a workstation with 31 GB RAM). With the default
`RUN_FEM = False` no notebook starts AEDT: the FEM cells read the kept results in `examples/tutorials/fem/`.

Other notebooks and example files that sit directly in `examples/` are listed on [Other examples](other-examples.md).

## Open and run them

1. Start Jupyter in the `qcd` conda environment, from the repository root:

   ```bat
   conda activate qcd
   jupyter lab examples/tutorials/00_quickstart_klive_and_pdk.ipynb
   ```

2. Run the cells from the top. The first code cell finds the repository root and loads the helper module
   `examples/tutorials/_tut.py` (`T`), which holds the tables, snapshots and the FEM round trip.
3. Read each markdown cell before its code cell: it says what the step does and what to look for.

Each notebook is self-contained, so you can also open any one of them on its own.

### Live KLayout or headless

By default the notebooks are **live**: every `add`, `route` and `set` is rebuilt and sent to KLayout over KLive
(`localhost:8082`), so you watch the chip grow. `KLAYOUT_GUI = True` (the default, next to `LIVE`) opens the KLayout
window with the Quantcore plugin at the first build if it is not running. See [KLive](../plugin/klive.md) for how
scripts drive KLayout.

For no window, set `QCC_LIVE=0` before starting Jupyter. Every build then writes `build/<name>.oas` plus its
`.qcc.json` sidecar, and the pictures are headless KLayout renders with the GUI colours. Without KLayout installed the
notebooks fall back to headless on their own. The saved outputs of the tutorials come from headless runs.

### The switches at the top

Every notebook has a settings cell near the top:

| Switch | Meaning |
|---|---|
| `LIVE`, `KLAYOUT_GUI` | Redraw KLayout on every change; open the window if needed. |
| `RUN_FEM` | `False` by default: jobs are exported, not solved, and kept results are loaded. `True` (or a set such as `{"q3d_cmatrix"}`) solves in AEDT 2024 R1 or later. |
| `AEDT_MODE` | `"batch"` (a new non-graphical AEDT, default), `"gui"` (a new window you can watch) or `"attach"` (the AEDT you already have open). |
| `FEM_FAST` | Fast test settings for every job: minutes, not converged. |
| `SIM_SUBSET`, `FEM_WHOLE` | Stage 1 simulates a subset of the chip; stage 2 puts its values in the whole LOM. `FEM_WHOLE = True` also simulates the whole chip. |
| `RESOLVE` | Solve again even when a kept result of the same job exists. |

### The kept FEM results

With `RUN_FEM = False`, every "bring it back" cell reads `results.json` and `job.json` from
`examples/tutorials/fem/<job>/`. That is why the FEM tables in the notebooks have numbers without AEDT. Each kept
result prints "the kept results were solved for another revision of this job (design hash or settings differ); they
are shown as they are". The library changed after the solve; the values are real, but a new solve would differ a
little. `RESOLVE = True` solves again.

The kept results were solved with the fast settings, so most are not converged (the notebooks print the pass count
and the last Δ). Judge them as trends, not as final values.

```{note}
`RUN_FEM = True` needs AEDT 2024 R1 or later, installed and licensed. The notebooks never close an AEDT window they
did not start. See [Simulation](../library/simulation.md) for the job folders and the solver settings.
```

### Where the files go

| What | Where |
|---|---|
| The designs the tutorials save | `examples/tutorials/designs/t0N_*.json` (`qcc build` and `qcc mask` work on them) |
| Snapshots | `examples/tutorials/img/t0N_<view>.png` |
| Solved FEM results | `examples/tutorials/fem/<job>/` |
| Builds, jobs, revisions | `build/` (not in git), for example `build/jobs/<design>_<group>_<analysis>/` |
| Progress for the dashboard | `build/t0N/state.json`, shown by the [dashboard](../overview/dashboard.md) |

## Two FEM stages

Every tutorial runs its FEM part the same way, and the LOM is always the whole netlist:

1. **Stage 1, the subset check.** `SIM_SUBSET` picks `(qubit, readout)` pairs. Each becomes a small box that is
   rendered and solved on its own. The notebook shows FEM values only: convergence, the raw C-matrix, eigenmodes,
   S21 notches, and the FEM-filled capacitances next to their estimates. If they look sane, go on.
2. **Stage 2, the whole LOM.** The subset values are filled into the whole netlist; every other branch keeps its
   component estimate. The LOM runs on that netlist, is compared with the FEM, and feeds the next revision.

See [the flow](../overview/flow.md) for the whole loop and [the LOM](../library/lom.md) for how far to trust the
estimates.

```{toctree}
:maxdepth: 1
:hidden:

00-quickstart
01-chip12
02-ibm-bowtie
03-surface17
04-feedback-loop
other-examples
write-your-own-notebook
```
