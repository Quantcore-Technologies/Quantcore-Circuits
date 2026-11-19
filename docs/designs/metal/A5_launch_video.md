# Launch-video chip (Metal A.5)

A ring of four pocket transmons joined by four λ/2 buses. Each qubit has its own λ/2 readout to a coupled bond pad and
its own charge line to a corner pad, and all lines use a wider 15 / 9 µm CPW. It is the chip from the Qiskit Metal
launch video (Apache-2.0, © IBM and contributors). The Quantcore rebuild is distributed under GPL-3.0.

Build this one to learn how a ring of coupled qubits is laid out with no shared feedline: every readout ends on its
own pad, and the charge lines end on open-to-ground stubs next to each pocket. The bus pad heights differ (30 and
50 µm) to detune neighbouring qubits.

```{image} ../../images/designs/metal/a5_launch_video.png
:alt: The whole a5 chip as the v2 notebook builds it
:width: 100%
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/metal/a5_launch_video.ipynb` (the one-cell version before the rewrite: `a5_launch_video.v1.ipynb`) |
| Source | Qiskit Metal `A.5-Launch-video-example.ipynb`, © IBM and contributors, Apache-2.0 |
| Chip | 10.2 × 7.4 mm (the source's 9 × 6.2 mm grown by 0.6 mm per side), CPW 15 / 9 µm |
| On the chip | 4 pocket transmons · 4 λ/2 readouts (5.5 and 13 mm) · 4 λ/2 buses (5.6 / 5.7 mm) · 4 charge lines · 8 bond pads |
| Builds today | yes: layout run 2026-11-19, 11 s, the saved design is byte-identical to the one before the rewrite |

## How the notebook builds it

```{image} ../../images/designs/metal/a5_launch_video_steps.png
:alt: The layout segments of a5, one picture each
:width: 100%
```

1. **Die.** An empty chip with the QCT frame (dicing marks, alignment grids, chip boundary, device ID).
2. **Bond pads.** Four corner pads for the charge lines, slid to the 100 µm pad-edge rule (the picture zooms on one pad).
3. **Readout pads.** Four coupled launchpads, one per qubit: a pad with a series capacitor.
4. **Qubits.** Four Metal pocket transmons with Quantcore junctions, in a ring.
5. **Readout resonators.** Four λ/2 resonators, routed clear of the charge lines.
6. **Coupling.** Four λ/2 buses closing the ring between neighbouring qubits.
7. **Charge lines.** One line from each corner pad to an open-to-ground stub beside its qubit.
8. **Whole chip.** Sim groups for the FEM jobs (the ring core and each qubit with its readout), the content centred in the die, the design saved.

## LOM estimates

Numbers are from a run of this notebook on 2026-11-19 (Setup, Design, Check and the LOM cells, 19 s): QuCat normal modes with QuTiP dressed values.

| group | qubit | f_q (GHz) | α (MHz) | resonator | f_r (GHz) | κ (MHz) | χ (MHz) |
|---|---|---|---|---|---|---|---|
| Q1+ol1 | Q1 | 6.967 | -297 | ol1 | 10.59 | 9.07 | -2.48 |
| Q2+ol2 | Q2 | 6.979 | -298 | ol2 | 4.676 | 0.818 | -0.69 |
| Q3+ol3 | Q3 | 6.967 | -297 | ol3 | 10.59 | 9.07 | -2.48 |
| Q4+ol4 | Q4 | 6.979 | -298 | ol4 | 4.676 | 0.818 | -0.69 |

| group | pair | ZZ (kHz) | neighbours | hybridised |
|---|---|---|---|---|
| Q1+cpw1+Q2 | Q1-Q2 | 215 | yes | no |
| Q3+cpw2+Q2 | Q2-Q3 | 235 | yes | no |
| Q3+cpw3+Q4 | Q3-Q4 | 215 | yes | no |
| Q1+cpw4+Q4 | Q1-Q4 | 235 | yes | no |

```{image} ../../images/designs/metal/a5_launch_video_lom.png
:width: 80%
:alt: LOM plot of a5_launch_video
```

These are lumped-model estimates (component formulas and calibration), not FEM results; see [the LOM page](../../library/lom.md) for how far to trust them.

## Build spec

The rest of this page is the detailed spec the notebook was built from: every component, port, route and length.

> **Update 2026-11-03:** frame = **source**: build with `chip={"die_frame": False, ...}` so the replica keeps its own size and frame (the Quantcore PDK die frame is for Quantcore chips only). `metal:<Class>` wrappers are READY (ports = Metal pin names, params = Metal options), so the `metal:` refs in this spec build as written; the Quantcore/KQC substitutions stay optional.

Source: Quantum Metal `docs/circuit-examples/full-design-flow-examples/A.5-Launch-video-example.ipynb`, first video.
The second video re-creates the qubit core only, for an HFSS render. Licence Apache-2.0.
This is the same family as `51_four_qubit_chip`, with four differences:
- `TransmonPocket` without charge lines, each with 3 pads.
- Wider 15/9 µm CPW.
- Buses of 5.6/5.7 mm.
- Charge lines that start at `OpenToGround` ends 0.35 mm outside each pocket. Readout goes to coupled launchpads at
  5.5 mm (E/W) and 13.0 mm (S/N).
Chip: DesignPlanar default 9000 × 6000 µm, centred, so **Designer = Metal + (4500, 3000)**. Fillet 90 µm, Metal
layer 1, junctions from `Fake_Junctions.GDS`.
**Buildable now: yes**. Substitutions: `Xmon` for TransmonPocket, `BondPad` + `FingerCapacitorSquare`, free ends.

### Components
Metal TransmonPocket options: pad_width 425, pocket_height 650; pads a (+1, −1, pad_width 200), b (−1, +1,
pad_height 30), c (−1, −1, pad_height 50). First build: `Xmon(claws=["n","w","e"])` with claw_n = readout (a).

| instance | catalog ref | at (x, y) | rot | claw mapping (Metal pin, Designer frame) |
|---|---|---|---|---|
| Q1 | `Xmon` (metal:TransmonPocket) | (6922.5, 3000) | 270 (Metal 0) | claw_n→E = a (7347.5, 2802.5); claw_w→N = b (6497.5, 3197.5) bus to Q4; claw_e→S = c (6497.5, 2802.5) bus to Q2 |
| Q2 | `Xmon` | (4500, 2050) | 180 (Metal 270) | claw_n→S = a (4302.5, 1625); claw_w→E = b (4697.5, 2475) bus to Q1; claw_e→W = c (4302.5, 2475) bus to Q3 |
| Q3 | `Xmon` | (2077.5, 3000) | 90 (Metal 180) | claw_n→W = a (1652.5, 3197.5); claw_e→N = c (2502.5, 3197.5) bus to Q4; claw_w→S = b (2502.5, 2802.5) bus to Q2 |
| Q4 | `Xmon` | (4500, 3950) | 0 (Metal 90) | claw_n→N = a (4697.5, 4375); claw_e→E = c (4697.5, 3525) bus to Q1; claw_w→W = b (4302.5, 3525) bus to Q3 |
| OTG1 … OTG4 | free ends (metal:OpenToGround, width 15, gap 9) | (7271, 3000), (4500, 1699), (1729, 3000), (4500, 4301) | — | charge-line tips; `dir` 0, −90, 180, 90 |
| P1_C … P4_C | `BondPad(80, 80, gap 58, taper 122)`, trace 15/9 | (8500, 5812), (8500, 188), (500, 188), (500, 5812) | 180, 0, 0, 180 | corner charge pads |
| P1_Q … P4_Q | `BondPad` + `FingerCapacitorSquare` (metal:LaunchpadWirebondCoupled) | pads (8520, 3000), (3510, 188), (480, 3000), (5490, 5812); caps at the tie pins (8450, 3000), (3510, 258), (550, 3000), (5490, 5742) | pads 90, 0, 270, 180; caps 0, 90, 0, 90 | readout pads |

### Routes (all 15/9 µm)
| route | from → to | type, length | waypoints | notes |
|---|---|---|---|---|
| cpw1 | Q1.claw_e → Q2.claw_w | meander 5600 | — | Metal Q1.c→Q2.b, lead 200/200, asym +140 |
| cpw2 | Q3.claw_w → Q2.claw_e | meander 5700 | — | Metal Q3.b→Q2.c, asym −140, lead flipped |
| cpw3 | Q3.claw_e → Q4.claw_w | meander 5600 | — | Metal Q3.c→Q4.b, asym +140 |
| cpw4 | Q1.claw_w → Q4.claw_e | meander 5700 | — | Metal Q1.b→Q4.c, asym −140, flipped |
| ol1, ol3 | Q1.claw_n → cap(P1_Q); Q3.claw_n → cap(P3_Q) | meander 5500 | — | λ/2 readout; lead 350/150, asym +140, flipped |
| ol2, ol4 | Q2.claw_n → cap(P2_Q); Q4.claw_n → cap(P4_Q) | meander 13 000 | — | long λ/2, about 4.5 GHz on Si (estimate) |
| cap stubs | cap → P*_Q.a | cpw ≈ 70 | — | |
| line_cl1 | P1_C.a → `free_end((7271, 3000), dir=0, term=6)` | cpw 3925 | nodes [(8500, 5500), (7500, 5500), (7500, 3000)] | Metal RouteAnchors, anchors (3, 0), (3, 2.5), (4, 2.5) mm, reversed |
| line_cl2 | P2_C.a → `free_end((4500, 1699), dir=-90, term=6)` | cpw 5356 | [(8500, 500), (6500, 500), (6500, 1500), (4500, 1500)] | |
| line_cl3 | P3_C.a → `free_end((1729, 3000), dir=180, term=6)` | cpw 3925 | [(500, 500), (1500, 500), (1500, 3000)] | |
| line_cl4 | P4_C.a → `free_end((4500, 4301), dir=90, term=6)` | cpw 5356 | [(500, 5500), (2500, 5500), (2500, 4500), (4500, 4500)] | |

### Launchers, pads, test structures, markers, labels
8 pads (4 corner charge pads, 4 edge readout pads). The corner pads at ±4000 µm fit inside the 9 mm chip. There are
no markers.

### LOM node structure
The structure is the same as `51_four_qubit_chip`: 4 islands, a ring of 4 λ/2 buses (5.6/5.7 mm), 4 λ/2 readouts
with series C to the ports, and 4 open charge lines (C_d).

### Targets (if stated)
None. The junctions are Fake_Junctions (Metal default Lj 10 nH). The second half only renders the core to HFSS
eigenmode ("FourQ"), with no numbers.

### Simplifications for a first rebuild
1. Reuse the 51 builder and change CPW (`a=15, b=9` per route), lengths and pad positions.
2. The OTG charge tips sit outside the original 650 µm pocket. With the smaller Xmon they are far from the island,
   so move them 100–150 µm inward if the drive coupling matters.
3. Ignore `lead_direction_inverted` (flip); the Designer places its own meanders.

### Quantcore PDK rebuild (2026-11-03)

The notebook is a **Quantcore-PDK rebuild**, not a replica (design rule, 2026-11-03): the netlist, LOM and imported components are kept, the process is Quantcore's.

Notebook: [`examples/designs/metal/a5_launch_video.ipynb`](../../../examples/designs/metal/a5_launch_video.ipynb).

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), on the source's chip (9 × 6.2 mm, see below) grown by 0.6 mm on every side (box `(-600, -700, 9600, 6700)`) so that the four corner charge-line pads clear the PDK marker areas; every coordinate stays the source's.
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); Metal's `DesignPlanar` default is silicon (εr 11.45, 750 µm), so the LOM capacitances, resonator frequencies and FEM jobs here are for sapphire, not the source's substrate.
- **Junctions:** Quantcore Nb/AlOx/Nb trilayer junctions (`junction_type` from `layouts.registry.trilayer_junction`): fingers on 2/0 + 4/0, spacer 50/0 with the 51–53/0 gradient, sized on the PDK junction rule (Nb Δ = 1.4 meV, I_c·R_n = πΔ/2e, R_n·A 13.5 kΩ·µm² and C_J 50 fF/µm² assumed); all four qubits get the PDK nominal junction, 0.5 × 0.6 µm fingers → R_n = 45 kΩ, L_J = 6.73 nH, C_J = 15 fF (in the 40–50 kΩ window) (the source's `Fake_Junctions` carry no value; the pre-rebuild build assumed 10 nH + 2 fF). Expected f_q ≈ 7.0 GHz (estimate; was 6.23 / 6.24 GHz). The bus pads still detune each bus-coupled pair (30 µm pad `b` at one qubit, 50 µm pad `c` at the other), so the pairs do not hybridise.
- **Kept:** the topology and every Metal component with the source's options (through the `metal:` wrapper), positions and orientations, every route's end pins and total length, the sim groups (buses 5.6 / 5.7 mm, readouts 5.5 / 13.0 mm, the four charge lines, the 15/9 µm CPW).
