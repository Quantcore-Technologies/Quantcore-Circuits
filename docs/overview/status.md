# Status: what is built and what is left

State on 2026-11-18, taken from the code, the logs and the saved notebook outputs. Dates are the last real run.

- **done**: built and run for real.
- **partial**: built, part of it unverified or missing.
- **export only**: solver input is written but never solved.
- **missing**: not built.

## What has never been verified

These gaps matter most.

- **No converged AEDT run.** Every eigenmode used fast settings (at most 3 passes, delta f 2.8-3.2 % against a 1 % target).
  A converged eigenmode needs a machine with 32 GB or more. In tutorial 4 the LOM and the FEM chi differ by about 54 %.
- **The kept FEM results are stale.** Every kept tutorial result was solved for an earlier revision of its job. 57 of 153
  sampled sim groups export differently since the November export changes, so they must be solved again.
- **Palace, Elmer and Sonnet were never solved.** Only the input files are written; solving with them is a future
  development goal. The Linux runner and queue were never used on a server.
- **The FEM loop never closed on target.** Tutorial 4 got to about 0.2 % of the targets but reports "on target (FEM):
  False".
- **The plugin's eigenmode run, `--aedt gui`, and a whole-chip simulation from the GUI** were never run. Whole-chip Run
  LOM of the 12- and 5-qubit tutorial chips takes more than 10 minutes.
- **The wheel** was built on 2026-11-17 and installed from the wheelhouse in a scratch environment (`qcc selftest`:
  29 of 29 checks).
- **The fast test suite** passed on 2026-11-19 on the release tree, with the PyPI releases of KQCircuits, Quantum
  Metal, SQcircuit, QuCat and PyAEDT installed: 3132 passed, 270 skipped (the AEDT read-back tests need local AEDT
  result files and skip without them). The tutorial "saved clean" test was dropped on 2026-11-18: tutorials are saved with their outputs.
- There is **no AEDT screenshot** in these docs: capturing one needs AEDT running.

## Modules

| Module | Page | Status | Last real run / evidence |
|---|---|---|---|
| KLayout plugin (menu, tools, panel, Flow strip) | [plugin tour](../plugin/tour.md) | done | GUI smokes all pass 2026-11-17 (83, 49, 39, 37 checks; 62 cells; 95 tutorial checks); end-to-end with a real non-graphical AEDT Q3D |
| KLive scripted design (`Designer`) | [scripted design](../plugin/klive.md) | done | live loop 0.1 s per change 2026-11-02; window handling 2026-11-13 |
| PDK | [PDK](../library/pdk.md) | done | rules changed 2026-11-17, 105 fab exports compared |
| Component library and catalog | [components](../components/cells/index.md) | done | 62-cell GUI sweep 2026-11-17; 142 cell pages |
| `design.json` schema and Python export | [routing and DRC](../library/routing-drc.md) | done | 105 examples round-trip 2026-11-15 |
| Assembly and routing | [routing and DRC](../library/routing-drc.md) | done, edge cases open | every example builds 2026-11-18 |
| Connectivity DRC and netlist | [routing and DRC](../library/routing-drc.md) | done | rules added 2026-11-17 |
| Layout to LOM and LOM simulation | [LOM](../library/lom.md) | done; model gaps | all 93 notebooks 2026-11-18 |
| Circuit IR, estimators, consensus, QuTiP | [LOM](../library/lom.md), [results](../library/results.md) | done | consensus on real FEM 2026-11-13 |
| Sim-group export | [simulation](../library/simulation.md) | done for Ansys | angled-crossing ports 2026-11-18 |
| HFSS / Q3D driver (AEDT 2024 R1) | [simulation](../library/simulation.md) | done with fast settings | real solves 2026-11-03/04, 11-13, 11-14, 11-17 |
| Elmer, Palace, Sonnet | [simulation](../library/simulation.md) | export only; future development goal | never solved |
| Runner and server queue | [simulation](../library/simulation.md) | partial | unit tests only |
| Result read-back | [results](../library/results.md) | done for AEDT | 2026-11-13 |
| Reports and plots | [results](../library/results.md) | partial | LOM and consensus plots yes; convergence, S21, EPR as tables only (plots being built) |
| Dashboard tracker | [dashboard](dashboard.md) | done | all tutorials 2026-11-13; `t04` served 2026-11-18 |
| Feedback and co-design | [feedback](../library/feedback.md) | partial | one real FEM loop (tutorial 4, 2026-11-13) |
| LOM-first synthesis | [LOM](../library/lom.md) | done for Xmon + lambda/4 on one feedline | `examples/lom_from_layout.ipynb` |
| Fab export | [fab](../library/fab.md) | done; wafer assembly being built, mask assembly missing | 105 exports 2026-11-17 |
| `qcc` CLI | [CLI reference](../reference/cli.md) | done | the reference page lacks `design junctions` and `design placement-junction` |
| Wheel and packaging | [getting started](../getting-started.md) | partial | wheel built and installed in a scratch env; 0.0.1b0 was the first PyPI release, 0.0.2 the current one |
| Docs site | [the docs](../index.md) | partial | rewritten as a section guide 2026-11-19; the `design.json` field reference is still missing |

### The three design routes

| Route | Status | Evidence |
|---|---|---|
| Code-first in Jupyter, live in KLayout | done | tutorials 0-4, checker runs 2026-11-18 |
| Drag and drop in the plugin to netlist, `circuit.json`, `design.py` | done | tutorials 1-4 redrawn in the GUI 2026-11-17, layout difference 0, 0, 0 and 3.9 µm squared |
| KLayout, render, sim parameters, LOM | done for Q3D | end-to-end smoke 2026-11-17; eigenmode from the GUI never run |
| LOM first (targets to layout) | done for one template | Xmon + lambda/4 on one feedline |

### Milestones of the original plan

| M | Milestone | State |
|---|---|---|
| M0 | environment and skeleton | done; CI on GitHub Actions (lint, tests on Ubuntu and Windows, docs, release) |
| M1 | PDK and mask export | done |
| M2 | components with ports | done |
| M3 | design model and builder | done |
| M4 | live loop | done |
| M5 | KLayout plugin | done except freeform shape to component |
| M6 | simulation builder | done for Ansys; flip-chip two-face export missing |
| M7 | Linux runner, Elmer, Palace | not done (export and queue code only) |
| M8 | results store and circuit IR | done (SQLite rows of JSON; no Parquet or NPZ arrays) |
| M9 | extraction and four adapters | done |
| M10 | pyEPR, QuTiP, consensus | done; eigenmode never converged on this PC |
| M11 | surrogates | partial (power-law calibration, no FEM sweeps) |
| M12 | co-design optimiser | partial (emulated loop; one real FEM loop) |
| M13 | feedback UI | done (dashboard, plugin tabs); per-instance hover values missing |

## What is left, ranked

| # | Item | Kind | Size |
|---|---|---|---|
| 1 | **Simulation PC.** Solve the kept FEM set again on the current library (tutorial 0: 3 jobs, tutorial 4: 9, the subsets of 1-3) and keep it | never verified | M (3-4 h of AEDT) |
| 2 | **Simulation PC.** One converged FEM run (eigenmode + EPR, driven) for tutorials 0 and 4 on a 32 GB machine or the server | never verified | M |
| 3 | **Simulation PC** (needs the FEM results of 1-2). Calibrate the LOM against the kept FEM: hanger kappa per kind, TransmonCross claws, claw-to-ground C, chi | built, partial | M |
| 4 | LOM robustness: floating unconnected pins, QuCat at 8 or more junctions, whole-chip LOM of 21 qubits (**simulation PC** for the big chips) | not built | M-L |
| 5 | **Simulation PC.** Close the FEM feedback loop on target and document "at most N FEM iterations" | never verified | M |
| 6 | **Simulation PC.** Q3D nets above 8000 points: unite pieces in AEDT after import | not built | S-M |
| 7 | Moved to Future development goals below | | |
| 8 | **Simulation PC** (FEM sweeps). Co-design levels M11 and M12: FEM-sweep surrogates, HFSS sign-off with a bias record (Palace verify is a future goal) | not built | L |
| 9 | **Simulation PC.** Flip-chip two-face FEM export | not built | M |
| 10 | Docs: field reference for `design.json` and the other file formats, regenerate the CLI page, refresh design images and spec numbers | partial | M |
| 11 | Plots for convergence, S21 with fit, EPR participations, mesh extrapolation | being built | S |
| 12 | Moved to Future development goals below | | |
| 13 | Install from PyPI on a fresh PC and the plugin from Salt | wheel installs in a scratch env; PyPI and Salt not yet checked | S-M |
| 14 | One green fast test suite. "Tutorials saved clean" is settled: the tutorials keep their outputs | done on the release tree (2026-11-19, 3132 passed) | S |
| 15 | Mask and wafer assembly | being built (wafer assembly) | M |
| 16 | Router edge cases: node near a corner, waypoint between r and 2r (the tiny-leftover zigzag is done, fixed 2026-11-18) | built, partial | S |
| 17 | LOM model requests: pad-to-pad coupler line C, StarQubit pad arcs, IDC kappa at 1.2 µm gaps, Purcell filter between series caps, SQUID static flux bias | not built | M |
| 18 | Analysis extras: SQcircuit T1 and T-phi, QuTiP `mesolve`, TLS surface participations, asymmetric SQUID cells, NbN per element | not built | M each |
| 19 | Eigenmode mesh reuse for driven runs | experiment | S |
| 20 | Remaining designs (hyperbolic lattice, flip-chip TSV, quick demo mask, community specs, UT Austin wireless JPA) | not built | M |
| 21 | Dashboard Fab step; per-instance values in KLayout | per-instance values being built; Fab step not built | S |

(S, M, L: small, medium, large.) Items marked **Simulation PC** need 32 GB of RAM or more; the checklist is
[the simulation PC page](simulation-pc.md).

### In progress

Being built and not yet verified:

- Lumped-junction EPR from the LOM and from the eigenmode runs, and the convergence, S21 fit and EPR plots.
- Wafer assembly of dies on 4 and 6 inch wafers.
- Per-instance values in KLayout.
- Custom components: a custom qubit and a spiralmon, a spiral capacitor and a tunable resonator.
- Packaging: wheel with dependencies, `qcc selftest`, install scripts, the developer guide.

### Future development goals

Not part of the simulation PC work; only the input files are written today.

| Item | State | Size |
|---|---|---|
| Linux runner, Palace and Elmer solves, Palace EPR reader | never verified, not built | L |
| Sonnet and Elmer result readers and a `qcc-sonnet` test | not built | S-M |
| Palace verify step of the co-design levels | not built | M |

### Plugin

Open items:

- Never solved from the GUI: an eigenmode run from the Simulate dialog, `--aedt gui`, a whole-chip simulation.
- Live PCells: KLayout asks to save on close after the swap; shape-parameter instances stay static; importing the library
  inside KLayout needs approved environment changes.
- No per-instance values on hover; the circuit picture is crowded on big chips; mirrored placement is not in the smokes.
- Freeform shape to component capture is not built. Snapping a component to a line is not built.
- Node snapping offers the start port's angle only. The termination of an existing free end is edited in the JSON.
- A node closer to a corner than the bend's cut fails in KQC; only the preview warns.
- One unreproduced click flake in 8 runs; sim groups are not drawable (Simulate makes them); half-built routes have no
  handles.
- Xmon default junction "Trilayer Junction" (0.1 µm test finger) gives L_J of about 202 nH (kept for now).
- Metal StarQubit: pins on solid metal, the coupler arm meets ground at the pin.

## Library requests from the notebook rewrite

Collected while rewriting the v2 design notebooks ([design notebooks](../designs/notebook-template.md)); none is built.
The numbering follows the order the requests came up: R1 to R11 and B-R1 to B-R11 from the first and second groups of
notebooks (R1 to R4 apply to both), B4-R1 to B4-R5 from the amplifier notebooks. The notebook lists are not exhaustive.

| Request | One line | Notebooks that need it |
|---|---|---|
| R1 | Reuse a solved eigenmode mesh in a driven run (`export_job(..., mesh_from=...)`) | every notebook with an eigenmode group |
| R2 | After feedback the drawn junction keeps its fingers: set `junction_params.lj_nH` too, or flag it in the DRC | `m51`, `a5`, `a6`, `qubit_test_chip`, `filled_qubit_test_chip`, `flipmon_test_chip`, `xmon_cap_sim`, KQC SQUID chips |
| R3 | Confirm `codesign` pairs a qubit with a lambda/2 readout that ends on a coupled pad, finger capacitor or tee | `m51`, `a5`, `sqchip_em`, `demo`, `demo_twoface`, `munchqubits` |
| R4 | A multi-pair `loop.iterate` that keeps the FEM minus LOM offset | all notebooks with an iterate cell |
| R5 | `loop.analyse` is slow on 17-100 qubits (every estimator on every pair); the notebooks pass `group=` | `m53`, `demoqpu17`, `tut222`, `ibm_falcon_27q` |
| R6 | Feedback for qubits without a readout (qubit-only surrogate) | `tut13`, `tut222`, `m54`, `tut443` |
| R7, B-R2 | `epr_values` with no readout per qubit (accept `readouts={q: None}`); a qubit-only form | `tut13`, `m54`, `iswap1`-`iswap3`, `a7`, `two_transmon`, `simple` |
| R8 | Feedback bounds for designs whose targets are outside the PDK R_n window (`pdk_lj_bounds(..., keep_outside=True)`) | `a4`, `a7`, `m53`, the five community chips, `tutorial_5` |
| R9 | Add C-matrix mutual capacitances as branches when no route or coupling declares them | `component_examples` |
| R10 | LOM model for `TunableCoupler02` (series SQUID in the line); the coupled group fails in QuCat | `iswap2` |
| R11 | Drop unreachable targets (e.g. alpha) in `target_copy` or `loop.feedback` | `google_tc_cell`, `google_tc_2x2`, `ibm_bowtie_5q`, `ibm_falcon_27q` |
| Driven with one port | `driven_values` fits notches only; add an S11 or transmission-peak fit (also B-R2, B-R8) | `sqchip_em`, `ibm_bowtie_5q`, `gatemon_test_chip`, `shaping`, `simple` |
| StarQubit junction port | The exporter makes no polygon for port 2, so no eigenmode job | `m54` |
| B-R1 | LOM model for a lambda/2 in transmission between two IDCs (a wire today), so feedback has no pair | `gatemon_test_chip` |
| B-R3 | Kept Q3D results should count for an L_J-only revision (a geometry hash beside the design hash) | every Results 5 that changes only L_J |
| B-R4 | `design_copy(...).save(path, name=...)`: a revision keeps the design name, so its FEM jobs collide | all notebooks with an iterate cell |
| B-R5 | Check that an 8-resonator line's eigenmode setup solves at least 8 modes | `resonator_test_chip` |
| B-R6 | KQC qubit cells (`Swissmon`, `DoublePads`, ...) lack `qcc_category = "qubit"`, so `layout_step` counts them as "other" | KQC qubit chips |
| B-R7 | Flip-chip groups simulate one face only (`face_stack`); a two-face stack is needed | `demo_twoface`, `quality_factor_twoface`, `crossing_twoface` |
| B-R9 | Zoom views of one-PCell chips from refpoints, not coordinates read off pictures | the eight one-PCell test chips |
| B-R10 | Snapshot without the ground grid (`with_grid` chips rebuild about 0.9 M holes per segment) | `with_grid` KQC chips |
| B-R11 | Chip launchers know only SMA8, ARD24 and DC24 | `sample_holder_test` |
| B4-R1 | Keep a driven job's Touchstone file with the kept results (or fit reflection resonances), so S11 can be read again later | the amplifier JPAs |
| B4-R2 | A `q_min` argument for `driven_from_eigenmode` (its mode pick needs Q > 100; the inductive JPA's Q is about 71) | `twpa_sim_jpa` |
| B4-R3 | Check how `fill` treats the JTWPA's grounded resonator pads | `jtwpa_4wm` |
| B4-R4 | A one-supercell KI-TWPA extraction instead of meshing the whole 18.5 mm line | `ki_twpa_serpentine` |
| B4-R5 | Decide on a chip-sized sim group for a driven S11 (a design change, so not made) | `unsw_kipa` |
