# The flow

Quantcore circuits turns a chip idea into a layout, checks it, simulates it and feeds the numbers back into the
design. One file, `design.json`, goes through the whole flow. This page lists the steps, the three ways to start, the
files each step writes and the `qcc` command for each step.

## The loop

```{figure} ../images/system/as_built.svg
:width: 100%

The loop as built on 2026-11-18. Green: built and run for real. Orange: built, part of it unverified. Yellow: solver
input is written but was never solved. Grey: not built.
```

| Step | What happens | Page |
|---|---|---|
| Draw | Place components, connect pins, route lines. Three ways: the KLayout plugin, the Python `Designer` (live in KLayout), or LOM-first synthesis from targets | [plugin tour](../plugin/tour.md), [KLive scripts](../plugin/klive.md), [LOM](../library/lom.md) |
| Process rules | One PDK: stack, die frame, 100 µm pad rule, keep-outs, cheese, junction process | [PDK](../library/pdk.md) |
| Build and check | `design.json` to a KQC layout; routing; DRC and netlist | [routing and DRC](../library/routing-drc.md) |
| LOM | The layout becomes a lumped circuit; QuCat and QuTiP give f_q, alpha, f_r, chi, kappa, g | [LOM](../library/lom.md) |
| Simulate | A sim group is cut out of the chip and written as an HFSS / Q3D job (also Elmer, Palace, Sonnet input) | [simulation](../library/simulation.md) |
| Read back | Solver output becomes `results/results.json`, fills the LOM, is plotted | [results and plots](../library/results.md) |
| Tune | Consensus against targets, then a proposed next revision | [feedback](../library/feedback.md) |
| Fab | Mask file with the QCT layer map | [fab export](../library/fab.md) |
| Watch | The dashboard follows all of the above | [dashboard](dashboard.md) |

The steps are a loop: after Tune you go back to Draw (or straight to Build) with the new revision.

## Three ways in

All three write the same `design.json`, so you can switch between them in the middle of a design.

| Way in | You do | Best for |
|---|---|---|
| The plugin | Draw in KLayout: place components from the panel, connect pins, route handles. The panel's Flow strip runs the next steps | Drawing by hand; checking a chip by eye |
| Python and KLive | Write `Designer(...)` calls in a notebook or script. Each change is rebuilt and redrawn in KLayout in about 0.1 s | Repeatable designs, parameter sweeps, notebooks |
| LOM first | Give the qubit and resonator targets. `qcc synth` and `qcc circuit layout` solve the knobs and lay out the chip | Starting from frequencies instead of geometry |

Every component carries a lumped model whose nodes map to its ports, so the layout is a node-connected netlist and the
mapping works in both directions (layout to LOM, LOM to layout). Without a solver the LOM values are component
estimates; after HFSS or Q3D the extracted C-matrix replaces them.

## Files each step writes

Build outputs go to `build/` (git-ignored) next to where you run the command. `<name>` is the design name.

| Step | File | What it holds |
|---|---|---|
| Draw | `design.json` (where you save it, often `examples/`) | The design: instances, routes, couplings, sim groups, targets |
| Build | `build/<name>.oas` and `build/<name>.qcc.json` | The KQC layout and a sidecar with ports and handles that the plugin overlays |
| LOM | `build/<name>.circuit.json` | The lumped circuit of the layout (nodes, branches, knobs, targets) |
| Simulate | `build/jobs/<design>_<group>_<analysis>/` | One job folder: `job.json`, the geometry, solver scripts |
| Read back | `<job>/results/results.json` | Parsed solver output; kept results of the same job are not solved again |
| Store | `results.sqlite` | The SQLite results store (set `QCC_RESULTS_STORE` to move it) |
| Tune | `build/<run>/revisions/rev<N>.json` | One design file per proposed revision |
| Watch | `build/<run>/state.json`, `build/<run>/shots/` | What the dashboard shows: steps, values, screenshots |
| Fab | `build/<name>_fab.oas` | The mask file with the fab layer map |

## The same flow on the command line

```bat
qcc synth --f-q 5.1 --alpha -220 --f-r 7.2 --g 90                  REM LOM first: Lj, C_sigma, Cg, lambda/4 length
qcc build examples/q1_r1_feedline.json --show                      REM build and open in KLayout
qcc design drc examples/q1_r1_feedline.json                        REM pins, handles, boundary, overlaps, crossings
qcc circuit export examples/q1_r1_feedline.json                    REM layout to LOM netlist (build/<name>.circuit.json)
qcc circuit simulate build/q1_r1_feedline.circuit.json             REM QuCat modes and kappa, QuTiP spectrum
qcc sim build examples/q1_r1_feedline.json -g Q1R1 -a q3d_cmatrix  REM job folder for a sim group
qcc hfss render examples/q1_r1_feedline.json                       REM whole chip into an AEDT project (no solve)
qcc sim run build/jobs/q1_r1_feedline_Q1R1_q3d_cmatrix             REM solve locally and collect results
qcc analyse examples/q1_r1_feedline.json build/jobs/q1_r1_feedline_Q1R1_q3d_cmatrix --feedback
qcc mask examples/q1_r1_feedline.json                              REM fab export with the PDK rules
qcc dashboard                                                      REM follow the run
```

All commands and options are in the [`qcc` reference](../reference/cli.md).

## Original plan

The plan was written when the project was still called `qcd`. It is kept here as written.

```{figure} ../images/system/original_plan.png
:width: 100%

The original architecture sketch. The package is now `quantcore_circuits` (command `qcc`), the dashboard is a web app,
and the plugin is Quantcore's own, not KQCircuits'. The as-built diagram above shows what exists.
```
