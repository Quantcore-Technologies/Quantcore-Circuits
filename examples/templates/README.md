# Notebook templates

`full_loop_template.ipynb` is the starting point for your own design notebook. It walks the whole Quantcore loop:

layout → LOM → eigenmode simulations of the components → the same mesh for the FEM runs → extract and analyse → feedback

On the default chip (one Xmon and one λ/4 hanger readout on a feedline, Quantcore PDK) it runs as shipped, with no
solver: the layout and LOM sections build and simulate, the FEM sections export their jobs and say "no solved results
yet", the feedback section runs on the LOM.

## Use it

1. Copy the notebook next to your own files (for example `examples/mine/`) and rename it.
2. In section 0 change `NAME`, `OUT`, the targets `F_Q` and `F_R`, and the switches if you have the simulation PC.
3. Go down the notebook. Every cell you change is marked `# TODO:`. Run from the first changed cell down.
4. Run headless with `QCC_LIVE=0`, or with KLayout open (the default) to see every change in the window.

| Section | Cells | Needs |
|---|---|---|
| 0 Setup and switches | imports, `RUN_FEM`, `RESOLVE`, `FEM_FAST`, `AEDT_MODE`, `MAX_ITER`, targets | nothing |
| 1 Layout | die, pads, feedline, qubit, readout, control lines, whole chip (sim group, targets, `save_design`), DRC | nothing |
| 2 LOM | `simulate_groups`, `plot_lom`, read against the targets, tune the readout | nothing |
| 3 Eigenmode | `export_sims`, `fem_stage` for the eigenmode job | simulation PC to solve |
| 4 FEM on the eigenmode's mesh | Q3D C-matrix, `driven_from_eigenmode` | simulation PC to solve |
| 5 Extract and analyse | `fill`, FEM against LOM, plots, lumped EPR | kept results |
| 6 Feedback | `loop.analyse`, `loop.feedback`, a revision, `iterate_to_target` | nothing |
| 7 Fab | mask export and pictures | nothing |

## Files it writes

| File | What |
|---|---|
| `<OUT>/<NAME>.json` | the design (the deliverable); written by `save_design` |
| `<OUT>/<NAME>_*.png` | the layout and plot pictures (git-ignored) |
| `<OUT>/fem/` | kept FEM results, one folder per job (survives `build/`) |
| `build/jobs/` | exported AEDT jobs |
| `build/<NAME>/revisions/` | the feedback revisions |
| `build/<NAME>_fab.oas` | the mask |

The guide is `docs/tutorials/write-your-own-notebook.md`. The v2 form every design notebook follows is described in
`docs/designs/notebook-template.md`; this template is the shorter version for a new chip.
