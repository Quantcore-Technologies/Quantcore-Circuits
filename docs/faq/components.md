# Components and pins

Questions about the component libraries, how parts connect, and what a qubit needs before you can simulate it. The
catalogue is under [Components](../components/cells/index.md); the guide is the
[library's components page](../library/components.md).

## Libraries and pins

### What are the three component libraries?

| Library | What it is |
|---|---|
| `quantcore` | The Quantcore PDK cells (57), with fab junctions and LOM models; start here |
| `kqc` | KQCircuits cells, used as they are |
| `metal` | Qiskit Metal cells wrapped as `metal:<name>` |

The plugin's component list has a library drop-down and a class drop-down (qubit, resonator, capacitor, launcher, ...).
See [components](../library/components.md).

### What is a pin?

A pin is a connection point of a component: a position, a direction and the CPW width `a` and gap `b`. Routes and snaps
connect to pins. Every cell page under [Components](../components/cells/index.md) has a picture of its pins and a pins
table.

### Why does the same cell appear in more than one library?

Some cells exist in more than one library. A cell that existing designs use keeps an alias, so old designs still
rebuild. The groups and their recommendations are in [DUPLICATES](../components/DUPLICATES.md).

### Why does a cell place nothing, or fail?

Not every cell can stand alone on a chip (wafer maps, markers), and some wrapped `metal:` cells need parameters. The
plugin reports a clear message instead of a script error. The state of each cell is in
[component status](../plugin/COMPONENTS_STATUS.md) and [SIM_EXPORT_AUDIT](../components/SIM_EXPORT_AUDIT.md).

## Qubits and junctions

### Where do I set the junction (L_J) of a qubit?

On the qubit's entry in `design.json` (`instances.Q1.junction`: `Lj_nH`, `Cj_fF`, optional `flux_phi0` and `asym`).
In the plugin use the component dialog's Junction section: type any one of L_J, I_c or R_n and the other two follow from
the PDK gap, then add C_J. These values are for the LOM and the simulation only; the drawn junction is for fab.
See [library components](../library/components.md).

### What is the difference between the drawn junction and the simulation value?

The drawn junction (`junction_type`, for example Quantcore Squid, on layers 2/0, 4/0 and 50 to 53/0) is for fab and is
never exported to a simulation. A simulation replaces it with a lumped inductor (L_J) in parallel with C_J across the
gap. If `Lj_nH` is empty, the PDK value of a drawn Quantcore trilayer junction is used; KQC junction types have no PDK
value, so set one. See [the LOM](lom.md) and [Simulation](simulation.md).

### What resistance window does the PDK ask for?

R_n of 40 to 50 kOhm for the whole device (the whole SQUID, not each junction). The default Quantcore SQUID is two 90 kOhm
junctions, 45 kOhm, L_J about 6.73 nH. A value outside the window is a `pdk_rn` design warning, not an error. See
[PDK and fab](pdk-fab.md).

### What happens to a pin nothing connects to?

The DRC warns (`dangling_port`) and the layout builds. A pin left open should stay floating in the LOM, never grounded,
since there is no junction to ground it through. This is a known library gap: a whole-chip LOM can fail with "open or
shorted" (tutorial 3 does). See [the LOM](lom.md).

## Hangers, merges and your own parts

### The hanger only worked from an Xmon. Why?

It was not Xmon-specific: the Xmon claw happens to face the feedline. A pin that faces sideways needs extra corners, and
the router now adds them, so hangers from TwoPadTransmon, Flipmon and Gatemon build. A Gatemon's `readout` port is the
island edge, so the dialog presets the normal line width.

### Does my resonator hang beside the feedline or merge into it?

By default it hangs (a coupler parallel to the line). Press **Ctrl+Shift+J** in Connect, or tick "Merge into FL" in the
route dialog, to split the feedline with a T-junction and end the route on its stem; the same box converts later. See
[place and route](../plugin/place-and-route.md).

### Can the coupler be closer to the feedline for a stronger coupling?

Yes. The route and hanger dialogs have a coupler gap for each of the two lines (the gap facing the other line). They
apply only along the coupler and default to each line's own gap `b`. Narrowing them raises kappa; the build refuses a gap
that would cut into the other line. The extra ground strip is drawn as metal, so it is in the fab mask and the simulation.

### How do I add my own component?

Write a cell with ports and a LOM model, as in the worked example `examples/custom_component/pad_gap_capacitor.py`; the
[Q1 + R1 tutorial](../plugin/TUTORIAL_q1_r1.md) has a section on it. It then shows up in the component list, builds,
passes the DRC and simulates. See [library components](../library/components.md).
