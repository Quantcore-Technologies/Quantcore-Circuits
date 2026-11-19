# Other examples

Besides the five [tutorials](index.md), `examples/` holds a few older notebooks, one folder per FEM milestone, a custom
component and some saved designs. This page lists each one in a row so you can find the one you need. The notebooks
here run the same loop as the tutorials but are less guided. Most use the switches `LIVE`, `RUN_FEM` and `AEDT_MODE`
described on the [tutorials index](index.md): with `RUN_FEM = False` nothing starts AEDT.

## Notebooks

| File | What it does | Saved outputs | Needs AEDT? |
|---|---|---|---|
| `examples/q1_r1_first_run.ipynb` | The whole loop for one qubit and its readout, in code: layout (live in KLayout), connect the dashboard, netlist and DRC, LOM simulation, render into HFSS, subset check, LOM builder to Hamiltonian to consensus, feedback to a new revision. Saves `q1_r1_code.json` | Yes (8 of 10 code cells) | Only with `RUN_FEM = True` |
| `examples/q1_r1_loop.ipynb` | The same chip as a loop: LOM-first targets, edit `design.json` and build, export an HFSS or Q3D job for `Q1R1`, extract with Metal LOM and cross-check with scqubits, QuCat and QuTiP, then tune the cross length to hit f_q with `pipeline_evaluator` (each iteration is a full simulation). Saves `q1_r1_feedline_tuned.json` | No | Yes, for the solve steps |
| `examples/lom_from_layout.ipynb` | Simulate the lumped circuit of a chip drawn in KLayout (or in code) without a full-wave run: get the netlist (*Quantcore, Export LOM circuit*, or `qcc circuit export`), simulate it, sweep L_J and the coupling capacitance, fill from a simulation and compare, and the reverse direction: two qubits from targets laid out with `layout_from_targets`. Saves `two_qubit_synth.json` | Yes (all 5 code cells) | No (the fill step uses a kept job if one exists) |

`q1_r1_first_run` is the code version of the click-through [Q1 + R1 tutorial](../plugin/TUTORIAL_q1_r1.md) for the
KLayout plugin. `lom_from_layout` is the one to open after you have drawn a chip in the plugin; see
[the LOM](../library/lom.md) for what the netlist and simulation mean.

## The FEM-loop milestone

| Path | What it is |
|---|---|
| `examples/fem_loop/fem_loop.ipynb` | One feedline with two hanging resonators, rendered into AEDT 2024 R1, solved (Q3D C-matrix, eigenmode with EPR, driven S21), read back and compared with the LOM; then three knobs change and it is done again. The point is that the solved values move with the geometry, not that they are converged. R1 is a λ/4 hanger (κ large enough for the S21 notch to resolve); R2 is a λ/2 open at both ends, a floating conductor that Q3D measures. The notebook has no saved outputs |
| `examples/fem_loop/fem_loop.py` | The same as a script: `build` writes the two designs and the LOM (seconds), `solve [rev ...]` adds the AEDT solves (batch, tens of minutes), `report` prints the table from whatever results exist |
| `fem_loop_rev0.json`, `fem_loop_rev1.json` | The two designs. Rev 1 changes R1's coupler 250 to 400 µm, R2's length (400 µm shorter) and R2's coupler 250 to 400 µm. Each has an `.oas`, a `.qcc.json` sidecar and a `.png` next to it |
| `results.json`, `results.md` | The comparison table. The kept `results.md` has LOM values only (for example R1 κ_ext 0.1464 to 0.3700 MHz); the FEM columns are empty |

## A custom component

| Path | What it is |
|---|---|
| `examples/custom_component/pad_gap_capacitor.py` | A short worked example of adding your own component: two pads facing across a gap in a CPW line (a series capacitor) as a KQC `Element` with ports `a` and `b`. Copy it into a folder of `src/quantcore_circuits/layouts/` and restart KLayout: `PadGapCapacitor` appears in the panel, in `qcc components`, in `design.json`, the DRC, the fab export and the LOM. See [components](../library/components.md) and the plugin tutorial |

## Saved designs

| File | What it is | Used by |
|---|---|---|
| `examples/q1_r1_feedline.json` | The reference one-qubit design (pads, Q1, feedline, readout, flux line, sim group `Q1R1`) | The CLI examples (`qcc build examples/q1_r1_feedline.json --show`), the plugin tour, `lom_from_layout` and the tests |
| `examples/q1_r1_code.json` | The same chip as written by `q1_r1_first_run` | That notebook |
| `examples/q1_r1_feedline_tuned.json` | The tuned design written by `q1_r1_loop` | That notebook |
| `examples/two_qubit_synth.json` | Two qubits and readouts synthesised from targets (`layout_from_targets`) | `lom_from_layout` and the dashboard-card tests |
| `examples/five_qubit_synth.json` | A five-qubit design of the same kind | The dashboard-card and design-to-Python tests |
| `examples/results.sqlite` | A results store: the default `results.sqlite` of the `ResultsStore` (set `QCC_RESULTS_STORE` to move it) | `qcc results show`, `q1_r1_loop` |

Build any of the designs with `qcc build <file.json> --show`. The designs saved by the tutorials themselves are in
`examples/tutorials/designs/` and are listed on the [tutorials index](index.md).

## The design notebooks

The notebooks under `examples/designs/` rebuild published chips (IBM, Google, Qiskit Metal, KQC and others), one per
chip, up to the whole-chip render. They have their own section, starting at the [design overview](../designs/overview.md).
