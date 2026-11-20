# Four-qubit mux (Metal A.3)

Four pocket transmons in a row, each read out by its own λ/4 resonator, all on one shared feedline. The four
resonators have stepped lengths (6.8 to 7.4 mm) so one line reads all four. It is the Qiskit Metal "A.3" full-design
example (Apache-2.0, © IBM and contributors), adapted from the SQDMetal benchmark devices. The Quantcore rebuild is
distributed under GPL-3.0.

Build this one to learn multiplexed readout, the standard small-processor readout layout. The qubits are not coupled
to each other, so the chip isolates the readout architecture.

```{image} ../../images/designs/metal/a3_four_qubit_mux.png
:alt: The whole a3 chip as the v2 notebook builds it
:width: 100%
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/metal/a3_four_qubit_mux.ipynb` (an older one-cell version is kept as `a3_four_qubit_mux.v1.ipynb`) |
| Source | Qiskit Metal `A.3-Four-qubit-multiplexed-readout.ipynb`, © IBM and contributors, Apache-2.0 |
| Chip | 16 × 9 mm (the source's size, larger than the 7.5 mm Quantcore die), CPW 10 / 6 µm |
| On the chip | 4 pocket transmons · 4 λ/4 readouts (6.8, 7.0, 7.2, 7.4 mm) · 4 coupled-line tees · 1 feedline · 2 bond pads |
| Builds today | yes (layout built on 2026-11-19 in 9 s) |

## How the notebook builds it

```{image} ../../images/designs/metal/a3_four_qubit_mux_steps.png
:alt: The layout segments of a3, one picture each
:width: 100%
```

1. **Die.** An empty 16 × 9 mm chip with the QCT frame (dicing marks, alignment grids, chip boundary, device ID).
2. **Bond pads.** Input and output launchpads, slid to the 100 µm pad-edge rule (the picture zooms on one pad).
3. **Readout line.** Four coupled-line tees on the feedline, one above each future qubit.
4. **Qubits.** Four Metal pocket transmons with Quantcore junctions, each with one readout pad.
5. **Readout resonators.** Four λ/4 meanders of stepped length from the tees to the qubits.
6. **Coupling.** None: the four qubits are deliberately uncoupled.
7. **Control lines.** None; the qubits are driven and read through their readouts.
8. **Whole chip.** Sim groups for the FEM jobs, the content centred in the die, the design saved.

## LOM estimates

Numbers are from a run of this notebook on 2026-11-19 (Setup, Design, Check and the LOM cells, 25 s): QuCat normal modes with QuTiP dressed values.

| group | qubit | f_q (GHz) | α (MHz) | resonator | f_r (GHz) | κ (MHz) | χ (MHz) |
|---|---|---|---|---|---|---|---|
| Q1+read1 | Q1 | 7.445 | -345 | clt1 | 4.031 | 0.0967 | -0.237 |
| Q2+read2 | Q2 | 7.445 | -345 | clt2 | 3.93 | 0.0898 | -0.205 |
| Q3+read3 | Q3 | 7.445 | -345 | clt3 | 3.835 | 0.0835 | -0.179 |
| Q4+read4 | Q4 | 7.444 | -345 | clt4 | 3.744 | 0.0777 | -0.157 |

```{image} ../../images/designs/metal/a3_four_qubit_mux_lom.png
:width: 80%
:alt: LOM plot of a3_four_qubit_mux
```

These are lumped-model estimates from component formulas and calibration, not FEM results. [The LOM page](../../library/lom.md) says how far to trust them.

## Build spec

The rest of this page is the detailed spec the notebook was built from: every component, port, route and length.

> The `metal:` references in this spec build as written, through the `metal:` wrapper (ports are the Metal pin names, parameters the Metal options). The Quantcore and KQC substitutions are optional.

Source: Quantum Metal `docs/tut/full-design-examples/A.3-Four-qubit-multiplexed-readout.ipynb`. Licence Apache-2.0.
It is adapted from the SQDMetal benchmark devices (Sommers *et al.*, arXiv:2511.01220, 2025).
The chip has four `TransmonPocket` qubits in a row, each with one readout pad. Four λ/4 resonators of stepped length
hang off one straight feedline through CoupledLineTees. This is the standard small-processor readout architecture.
Chip 16 000 × 9000 µm, centred, so **Designer = Metal + (8000, 4500)**. CPW 10/6 µm, fillet 90 µm.
A first build uses these substitutions: KQC `DoublePads` (or `Xmon(claws=["n"])`), hangers, `BondPad`.

### Components
| instance | catalog ref | key params (µm) | at (x, y) | rot | notes |
|---|---|---|---|---|---|
| Q1 … Q4 | KQC `DoublePads(island1_extent=[425, 90], island2_extent=[425, 90], island_island_gap=30, ground_gap=[650, 650])` (metal:TransmonPocket) | Metal pad_width 425, pocket_height 650, readout (loc_W +1, loc_H +1) | (3500 + 3000 k, 2700), k = 0…3 | 0 | `cplr` faces N. The Metal readout pin is (x + 425, 2895) facing E |
| clt1 … clt4 | hangers on FL (metal:CoupledLineTee) | coupling_length 350, space 3, down_length 300, fillet 90, short | centres (3500 + 3000 k, 6300) | 0 | leg at x + 175 |
| LPin | `BondPad(80, 80, gap 58, taper 122)` | | (525, 6300) | 270 | faces E |
| LPout | `BondPad` | | (15475, 6300) | 90 | faces W |

### Routes
| route | from → to | type, length | waypoints / hanger | notes |
|---|---|---|---|---|
| FL | LPin.a → LPout.a | cpw 14 950 | — | Metal f0 2625, f1–f3 2300 each, f4 2625, plus 4 × 700 tee prime |
| read1 | Q1.cplr → `FL.hanger(s=2975, length=350, side="right", ground_gap=3, direction="backward", end="short")` | meander 7450 | — | Metal 6.8 mm + 650 tee |
| read2 | Q2.cplr → `FL.hanger(s=5975, …)` | meander 7650 | — | Metal 7.0 mm |
| read3 | Q3.cplr → `FL.hanger(s=8975, …)` | meander 7850 | — | Metal 7.2 mm |
| read4 | Q4.cplr → `FL.hanger(s=11975, …)` | meander 8050 | — | Metal 7.4 mm |

All four hangers share length 350, side "right", ground_gap 3, direction "backward" and end "short". The Metal
readout routes run from the tee to the qubit with leads 100/100.

### Launchers, pads, test structures, markers, labels
2 pads (W/E). There are no markers.

### LOM node structure
4 transmons, each with C_g to its own λ/4 (7.45 / 7.65 / 7.85 / 8.05 mm, stepped about 100 MHz). Each λ/4 has a κ to
the single FL between two 50 Ω ports. There are no buses and no control lines.

### Targets (if stated)
None. Estimates: λ/4 ≈ 4.24 / 4.13 / 4.03 / 3.93 GHz on sapphire.

### Simplifications for a first rebuild
1. Build it as a generator over k = 0…3 (`with d.batch():`). It is the direct Metal counterpart of
   `lom.synthesize` N-qubit feedline layouts, so compare the hanger κ / χ estimates across the four resonators.
2. `Xmon(claws=["n"])` works equally well if the Xmon LOM model is preferred.

### Quantcore PDK rebuild

The notebook is a Quantcore PDK rebuild of the source, not a replica: the netlist, LOM and imported components are kept, and the process is Quantcore's.

Notebook: [`examples/designs/metal/a3_four_qubit_mux.ipynb`](../../../examples/designs/metal/a3_four_qubit_mux.ipynb).

- Chip: the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 16 × 9 mm chip (the design does not fit the 7.5 mm die); no KQC chip frame.
- Stack: sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); Metal's `DesignPlanar` default is silicon (εr 11.45, 750 µm), so the LOM capacitances, resonator frequencies and FEM jobs here are for sapphire rather than the source's substrate.
- Junctions: Quantcore Nb/AlOx/Nb trilayer junctions (`junction_type` from `layouts.registry.trilayer_junction`): fingers on 2/0 + 4/0, spacer 50/0 with the 51–53/0 gradient, sized on the PDK junction rule (Nb Δ = 1.4 meV, I_c·R_n = πΔ/2e, R_n·A 13.5 kΩ·µm² and C_J 50 fF/µm² assumed); all four qubits get the PDK nominal junction, 0.5 × 0.6 µm fingers → R_n = 45 kΩ, L_J = 6.73 nH, C_J = 15 fF (in the 40–50 kΩ window), in place of Metal's `hfss_inductance` 10 nH (+ 2 fF assumed). Expected f_q ≈ 7.4 GHz (an estimate), above the ≈ 4 GHz λ/4 readouts as in the tutorial.
- Kept: the topology and every Metal component with the source's options (through the `metal:` wrapper), positions and orientations, every route's end pins and total length, the sim groups (readouts 6.8 / 7.0 / 7.2 / 7.4 mm).
