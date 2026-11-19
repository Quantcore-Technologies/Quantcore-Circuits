# The LOM

Questions about the lumped-element model (LOM): what it is, what it gives you before any simulation, and how far to trust
it. The page is [LOM](../library/lom.md).

## What it is

### What is the LOM?

A circuit made from the layout. Each component has a model that maps its ports to nodes and branches (capacitances,
junctions, lines); routes become conductors or resonators; the pieces merge into one netlist. Solving it gives qubit and
resonator frequencies, anharmonicity, couplings and the dispersive shift in seconds, with no FEM. See
[LOM](../library/lom.md).

### How do I run it?

`d.lom()` in Python gives the netlist and `simulate_lom(lb, d.design)` solves it; on the command line
`qcc circuit export DESIGN` then `qcc circuit simulate CIRCUIT [--json --png]`; in the plugin Run LOM (Ctrl+Shift+O). See
[the flow strip](../plugin/flow-strip.md).

### Where do I see and edit the LOM values of a component?

To see them: the panel's LOM tab after Run LOM (modes, parameters against targets, every branch with its value and where it
came from, the circuit picture), and the read-only circuit rows at the end of a component or route dialog. To edit: the
junction rows (L_J, I_c or R_n, C_J) and targets in the component dialog, and Edit > Add coupling for lumped couplings.
Capacitances are not typed in: they follow the geometry, or FEM results once imported.

## Accuracy

### What does the LOM estimate, and how accurate is it?

It estimates f_q, alpha, f_r, kappa, chi and couplings from component formulas and calibration. It is an estimate: the
claw-to-ground capacitance of a TransmonCross is about 2 times low, the hanger kappa uses one constant for all hangers
(lambda/4 about 35 percent low, open lambda/2 about 5 times low), and the Purcell filter between series capacitors is not
loaded. Against SQcircuit the LOM solver agrees to 0.1 percent on f_q and 1 percent on alpha for the check circuits; that
tests the solver, not the geometry formulas. Use FEM values when you need them. See [LOM](../library/lom.md).

### Which solvers does it use?

QuCat for the normal modes and kappa, QuTiP for the dressed spectrum, and estimators from Qiskit Metal, SQcircuit and
scqubits (and pyEPR when an eigenmode result exists). A consensus picks one value per parameter and flags the spread.

### Why is the readout frequency different from the bare lambda/4 value?

The dialog's length estimate is the bare lambda/4 on your substrate's permittivity. The claw and coupler add capacitance,
which pulls the real frequency lower (a 4200 µm line: 7.5 GHz bare, 6.65 GHz with the claw in one design). The loss
tangent changes Q, not frequency.

### Can I change the substrate?

Yes, in Chip settings (thickness, relative permittivity, loss tangent). A changed value is stored in the PDK string, for
example `quantcore_nb_sapphire_v1+substrate(eps_r=11.45)`, and the LOM, simulation exports and length estimate use it.

## Scope

### Why does the LOM always run on the whole chip?

By design: the LOM solves the whole chip in one network and has no per-group mode. Subsets exist only on the simulation
side, before the FEM cell. If the whole-chip run is too heavy for your PC, run it on a bigger machine. QuCat reaches its
recursion limit at 8 junctions, and a whole-chip run of a 21-qubit chip did not finish on a laptop (9 minutes, 4.7 GB).

### Run LOM says "open or shorted" or "nothing to simulate".

"Nothing to simulate" means the design has no qubit or inductor yet. "Open or shorted" comes from a pin that is not
connected: the LOM should keep an open pin floating, but today it fails on such chips (tutorial 3). Connect the pin, or run
the LOM on a design where every pin is used. See [status](../overview/status.md).

### Can I design from targets instead of from a layout?

Yes. `qcc synth --f-q --alpha --f-r --g` solves L_J, C_sigma, C_g and the lambda/4 length for one qubit with a readout, and
`qcc circuit layout CIRCUIT -o OUT --live` draws the chip. It works for the Xmon with a lambda/4 readout on a feedline;
other topologies are not built. See [the flow](../overview/flow.md).
