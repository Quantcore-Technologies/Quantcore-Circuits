# Use cases

Each recipe below is one thing people do with quantcore-circuits: the steps in short, and where to read more. Pick the one
closest to your task. All of them end in the same `design.json`, so you can combine them.

## Draw a qubit by hand in KLayout

Use this when you want to see and move the geometry yourself.

1. Install the plugin ([plugin](../plugin/index.md)) and open KLayout.
2. Place an `Xmon`, two bond pads and a readout resonator from the panel; connect them with *Connect* or *Route handles*.
3. Run the Flow strip: Check, LOM, Simulate, Fab ([flow strip](../plugin/flow-strip.md)).

Follow the [Q1 + R1 tutorial](../plugin/TUTORIAL_q1_r1.md). Pins and routing: [place and route](../plugin/place-and-route.md).

## Script a chip in Python

Use this for repeatable designs, sweeps and notebooks.

1. Create a `Designer`, add components with `add`, connect them with `route`.
2. Call `show()` to build; with `live=True` every change is redrawn in KLayout.
3. Call `drc()` and `lom()`; save with `save("my_chip.json")`.

Start with [getting started](../getting-started.md), then the [Designer guide](../library/designer.md) and
[tutorial 0](../tutorials/00-quickstart.md).

## Start from target frequencies

Use this when you know the qubit frequency, anharmonicity, readout frequency and coupling, but not the geometry.

1. Run `qcc synth --f-q 5.1 --alpha -220 --f-r 7.2 --g 90`. It prints L_J, the total capacitance, the coupling
   capacitance and the lambda/4 length.
2. Turn a circuit file into a layout with `qcc circuit layout build/<name>.circuit.json -o build/synth.json`.
3. Open the result in KLayout and refine it.

Limit: this is built for one template, an Xmon with a lambda/4 readout on one feedline. See [LOM](../library/lom.md) and
[tutorial 4](../tutorials/04-feedback-loop.md).

## Check a chip before it goes to fab

Use this on a new or imported design.

1. Run the DRC: `qcc design drc DESIGN` (dangling pins, overlaps, crossings, the 100 µm pad rule, die-frame keep-outs).
2. Run the netlist check: `qcc design netlist DESIGN` (declared against drawn connections: opens and shorts).
3. Export the mask: `qcc mask DESIGN`. The layer map, cheese and corner rounding come from the PDK.

Rules and layers: [routing and DRC](../library/routing-drc.md), [PDK](../library/pdk.md), [fab export](../library/fab.md).

## Simulate part of a chip and bring the numbers back

Use this when the lumped estimates are not enough and you have HFSS or Q3D (AEDT 2024 R1 or later).

1. Define a sim group: the instances and routes to cut out, plus a margin (the plugin's Simulate dialog, or
   `Designer.sim_group`).
2. Build the job (`qcc sim build`), solve it (`qcc sim run`), or render it into an AEDT project without solving
   (`qcc hfss render`).
3. Read the results back (`qcc results collect`). They fill the LOM, which then uses FEM values.

Details: [simulation](../library/simulation.md), [results](../library/results.md). Note that no converged AEDT run has been
made yet; see [status](status.md).

## Tune a design toward its targets

Use this when the simulated numbers miss the goals you set.

1. Set `targets` in the design (for example `f_q_GHz` and `alpha_MHz` per qubit, `f_GHz` and `g_MHz` per resonator).
2. Run `qcc analyse DESIGN JOB --feedback`. The estimators vote, the consensus is compared with the targets, and a new
   revision is proposed.
3. Apply it (`qcc results apply`), rebuild and check again. Open `qcc dashboard` to follow the residuals.

Details: [feedback](../library/feedback.md), [dashboard](dashboard.md), [tutorial 4](../tutorials/04-feedback-loop.md).

## Rebuild a published chip

Use this to learn from a real design or to start from one.

1. Open the [design notebooks](../designs/overview.md). Each one rebuilds a chip from the literature or a design library
   (Qiskit Metal, KQCircuits, qpdk and others) with the Quantcore library and PDK.
2. Run its Setup and Design cells; the whole chip appears in KLayout or as a picture.
3. Change a parameter and rebuild, or continue with the LOM and FEM cells.

How the notebooks are built: [notebook template](../designs/notebook-template.md).
