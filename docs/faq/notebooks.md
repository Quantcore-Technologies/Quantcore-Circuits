# Notebooks

Questions about the tutorial notebooks and the design notebooks. The pages are the [tutorials](../tutorials/index.md),
the [design notebooks](../designs/overview.md) and the [notebook template](../designs/notebook-template.md).

## Which notebook?

### What is the difference between the tutorials and the design notebooks?

The five **tutorials** (`examples/tutorials/`) teach the loop in order and are saved with all their outputs, so you can
read them without running anything. The **design notebooks** (`examples/designs/<group>/`) rebuild published or example
chips (IBM, Google, Qiskit Metal, KQC, ...) one segment at a time, each with a picture, then follow the plugin's steps:
Check, LOM, Simulate, Results, Fab. Start with tutorial 0. See [tutorials](../tutorials/index.md) and
[design notebooks](../designs/overview.md).

### What are the `.v1` notebooks?

The older form of a design notebook, kept byte for byte next to its rewrite (`<id>.v1.ipynb` beside `<id>.ipynb`). Both
write the same `<id>.json`, so run one or the other, not both in a row expecting different files. The tests skip `.v1`
notebooks. See the [notebook template](../designs/notebook-template.md).

### Where do the saved outputs and kept FEM results live?

A notebook keeps the outputs of the cells it was run with (that is wanted). Solved results sit next to it in a `fem/`
folder (for the tutorials `examples/tutorials/fem/`) and are not solved again.

## Running

### Do the notebooks start AEDT?

Not as shipped. `RUN_FEM = False` exports the jobs and loads kept results. Set `RUN_FEM = True` (or a set such as
`{"q3d_cmatrix"}`) to solve in AEDT 2024 R1 or later. `AEDT_MODE` picks `batch`, `gui` or `attach`; `RESOLVE = False`
does not solve again when kept results of the same revision exist; `FEM_FAST = True` uses the fast settings. See
[simulation](simulation.md) for the modes.

### The notebook does not open KLayout, or I want no window.

By default a notebook is live: each `add`, `route` and `set` is sent to KLayout over KLive, and the window opens at the
first build. Set `QCC_LIVE=0` before starting Jupyter for headless runs; builds then write `build/<name>.oas` and headless
renders. Without KLayout installed the notebooks fall back to headless. See [KLive](../plugin/klive.md).

### What do I run first, and in which environment?

`conda activate qcd`, `set OPENBLAS_NUM_THREADS=2` on a small PC, then
`jupyter lab examples/tutorials/00_quickstart_klive_and_pdk.ipynb` from the repository root. Run from the top. See the
[tutorials](../tutorials/index.md).

### How long does a notebook take?

The tutorials with `RUN_FEM = False` take 1 to 5 minutes. With solving on, each FEM job adds minutes: Q3D about 3, eigenmode
10 to 25, driven 20 to 40 (times on a 31 GB workstation, fast settings). The design notebooks list their timings on their
own pages.

### What does "Same design as before" mean?

The last Design cell saves `<id>.json` and prints whether it is byte-identical to the file it replaces. If it says
"differs", the notebook changed the design; compare with the `.v1` and fix the notebook, not the JSON.

### Can I run only part of a chip?

Yes. Before the FEM cell, render and solve a subset (the feedline plus the pairs you choose) as a convergence and
sanity check; afterwards render the whole chip at fast settings. The LOM itself always uses the whole chip. See
[simulation](simulation.md) and [the LOM](lom.md).

### Can I watch a notebook in the dashboard?

Yes. Put `track.start("name", dashboard=True)` at the top or set `QCC_TRACK=1`, then run `qcc dashboard`. See
[the dashboard](../overview/dashboard.md).

## Design notebooks and their pages

### Does every design notebook build?

Each v2 design notebook was run up to the whole-chip render and checked with "Same design as before"; the LOM, FEM and
feedback cells were not run. The "Builds today" row on a design's page says what happened. See
[design notebooks](../designs/overview.md).

### Where are the LOM estimates of a design?

On the design's page, under "LOM estimates", from a separate pass (the notebook's LOM cells, or the `.v1` output for big
chips). They are lumped estimates, not FEM; see [the LOM](lom.md).
