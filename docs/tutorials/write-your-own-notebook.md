# Write your own notebook

This page shows how to turn your own chip into a notebook that runs the whole design loop. You start from a template that
already builds a tiny chip (one Xmon and one λ/4 readout) and runs as far as the LOM without a solver, then change it one
segment at a time. Use it when none of the [tutorials](index.md) or design notebooks is close enough to your chip.

The loop the template follows:

**layout → LOM → eigenmode simulations of the components → the same mesh for the FEM runs → extract and analyse → feedback**

## Copy and rename

1. Copy `examples/templates/full_loop_template.ipynb` into your own folder, for example `examples/mine/`.
2. Rename it. In section 0 set `NAME` (the chip and its design file), `OUT` (where its JSON and pictures go) and the
   die size.
3. Open it in Jupyter, with KLayout running to watch every change, or run headless with `QCC_LIVE=0`.

Every cell you are expected to change is marked `# TODO:`. The notebook is split with `#` headings that match the
sections below.

## Set the switches and the targets

The switch cell in section 0 decides what may run.

| Switch | Meaning |
|---|---|
| `RUN_FEM = False` | no AEDT is started; FEM cells export jobs and load kept results |
| `FEM_FAST = True` | fast solver settings (minutes, not converged) |
| `AEDT_MODE = "batch"` | `batch`, `gui` or `attach` |
| `MAX_ITER = 3` | revisions the iterate cell may try |
| `F_Q`, `F_R` | your targets, in GHz |

Leave `RUN_FEM = False` on a small PC. Set it to `True` only on the [simulation PC](../overview/simulation-pc.md).

## Change the layout, one segment at a time

Section 1 builds the chip in seven segments. After each one `layout_step` draws a picture and prints what the chip holds
so far, so you see what the change did.

```{figure} ../images/tutorials/template_steps.png
:width: 100%

Segments 1 to 5 of the template chip: the die, a bond pad, the feedline, the Xmon, the readout resonator.
```

| Segment | What you change |
|---|---|
| 1.1 Die | the die size and chip ID |
| 1.2 Pads | where the pads sit on the feedline height; `edge="auto"` applies the 100 µm PDK rule |
| 1.3 Feedline | the route between the pads |
| 1.4 Qubit | the qubit class and its dimensions; the junction is sized from your target |
| 1.5 Readout | the coupling length and where the hanger meets the feedline |
| 1.6 Control lines | empty in the template; add your drive or flux line here |
| 1.7 Whole chip | targets, the sim group, centring, `save_design` |

Segment 1.7 writes `<NAME>.json`. That file is the deliverable: `qcc build`, `qcc mask`, the KLayout plugin and the
dashboard read it. The next cell runs the DRC; fix errors before going on (margins are warnings).

```{figure} ../images/tutorials/template_chip.png
:width: 55%

The whole template chip after segment 1.7.
```

## Run the LOM

Section 2 turns the layout into a lumped circuit and solves it in seconds. This is where you iterate.

```{figure} ../images/tutorials/template_lom.png
:width: 100%

The LOM of the first build: the qubit is close to 5.5 GHz, the readout (squares) lands low, near 6.25 GHz.
```

The table puts each value next to its target. On the shipped chip the qubit is at 5.51 GHz (target 5.5) and the readout
at 6.25 GHz (target 7.0): the claw loads the quarter-wave line. The next cell scales the readout length (λ/4 ∝ 1/f) until
the LOM reads 6.99 GHz, then saves the design again. The save reports "The design differs": that is the tuned length,
as it should be. These numbers are lumped-model estimates; [the LOM page](../library/lom.md) says how far to trust them.

## Decide what to simulate

Sections 3 and 4 are the FEM part. They always export the jobs; they solve only with `RUN_FEM = True`.

| Section | Job | Needs the simulation PC | Why |
|---|---|---|---|
| 3 Eigenmode | the sim group's eigenmode job | yes, to solve | the modes, their Q and the junction participation |
| 4.1 Q3D | the same group's capacitance matrix | yes, to solve | measured capacitances for the LOM |
| 4.2 Driven | `driven_from_eigenmode`: S21 on the eigenmode's mesh seeds | yes, to solve | the readout notch and κ |

The sim group is declared in segment 1.7 (`d.sim_subset(...)`): the part of the chip that a job cuts out. Keep it small:
a qubit with its readout, not the whole chip. Each of these sections starts with the marker "Simulation PC (32 GB+ RAM)". The
library cannot reuse a solved mesh in a driven setup, so `driven_from_eigenmode` copies the eigenmode job's mesh seeds and
frequency instead.

## Read the results

Section 5 brings the FEM numbers into the LOM's terms.

1. `fill` replaces the LOM's capacitance estimates with the Q3D values.
2. `epr_values` and `driven_values` read f_q, α, χ, f_r and κ from the eigenmode and driven jobs.
3. The FEM against LOM table gives each quantity with the difference in %.
4. The plot and EPR cells (`plot_convergence`, `plot_s21_fit`, `plot_epr`, the lumped EPR) print "not available yet" when
   their helper is missing, or show the plot.

Without results every cell prints one line saying what would appear. Put kept results in `<OUT>/fem/<job>/` (copy the
folder from the simulation PC) and the same cells fill in on any PC.

## Run the feedback

Section 6 is the loop.

1. `target_copy` writes your targets into a copy of the design, so the design file keeps its own.
2. `loop.analyse` runs every estimator and picks one value per quantity (the consensus), with its residual in tolerances.
   Kept Q3D results are passed in as `FILL`.
3. `loop.feedback` proposes new knob values (junction L_J, readout length, claw) and writes revision 1, built and checked.
4. `iterate_to_target` repeats until every target is inside its tolerance or `MAX_ITER` revisions were made.

```{figure} ../images/tutorials/template_iterate.png
:width: 45%

The residual falls below one tolerance in one revision (on the LOM).
```

A revision is only a file. To adopt it, set `ADOPT = True` in 6.3 (it copies the revision over your design file), then
carry the new numbers into your cells. Section 7 exports the mask.

## Habits that keep it working

- **`save_design` at the end of the layout.** It tells you whether the file changed. Do not hand-edit the JSON.
- **One change at a time.** Change one segment, run from there down, read the picture and the DRC, then go on.
- **Keep FEM results in `fem/`.** `build/` can be wiped; `<OUT>/fem/` is where kept results live and where the cells look.
- **Targets in a copy.** `target_copy` keeps the deliverable clean.
- **Do not solve twice.** `RESOLVE = False` loads kept results when they match the design.
- **Margins are warnings.** Errors must be zero; pad edge, keep-outs and centring are reported, not blocking.

## Where to look next

- [The designer API](../library/designer.md) and [the component libraries](../library/components.md) for what you can place.
- [The LOM](../library/lom.md), [simulation](../library/simulation.md) and [feedback](../library/feedback.md) pages for
  what each section calls.
- [Lumped EPR](../library/epr.md) for the participation helpers.
- [How a design notebook works](../designs/notebook-template.md): the longer form with eight design segments.
- [The simulation PC checklist](../overview/simulation-pc.md).
