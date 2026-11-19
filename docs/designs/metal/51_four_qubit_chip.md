# Four-qubit ring (Metal 51)

Four transmon qubits sit in a diamond and talk to each other through a ring of four bus resonators. Each qubit has
its own readout resonator, which ends on its own coupled bond pad (there is no shared feedline), and its own charge
line for driving it. The layout comes from Qiskit Metal's four-qubit example (tutorial 51 / 2.21, Apache-2.0), rebuilt
on the Quantcore PDK: sapphire, Quantcore trilayer junctions, the QCT die frame and bond pads 100 µm from the edge.

Build this one to learn λ/2 readouts that end on a coupled pad, qubit–qubit coupling through λ/2 buses, and charge
lines wired through corner points.

```{image} ../../images/designs/metal/m51_four_qubit_chip.png
:alt: The whole m51 chip as the v2 notebook builds it
:width: 100%
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/metal/m51_four_qubit_chip.ipynb` (the one-cell version before the rewrite: `m51_four_qubit_chip.v1.ipynb`) |
| Source | Qiskit Metal `51-Four_qubit_chip.ipynb` (same layout as tutorial 2.21), © IBM and contributors, Apache-2.0 |
| Chip | 9 × 6.5 mm (the source's size, larger than the 7.5 mm Quantcore die), CPW 10 / 6 µm |
| On the chip | 4 pocket transmons · 4 λ/2 readouts (8.6 mm) · 4 λ/2 buses (9 mm) · 4 charge lines · 8 bond pads |
| Builds today | yes: layout run 2026-11-19, 12 s, the saved design is byte-identical to the one before the rewrite |

## How the notebook builds it

```{image} ../../images/designs/metal/m51_four_qubit_chip_steps.png
:alt: The eight layout segments of m51, one picture each
:width: 100%
```

1. **Die.** An empty 9 × 6.5 mm chip with the QCT frame (dicing marks, alignment grids, chip boundary, device ID).
2. **Bond pads.** Four corner pads for the charge lines, slid to the 100 µm pad-edge rule.
3. **Readout pads.** Four coupled launchpads, one per edge: a pad with a series capacitor.
4. **Qubits.** Four Metal pocket transmons with Quantcore junctions (L_J 6.73 nH), rotated so their pads face.
5. **Readout resonators.** One 8.6 mm λ/2 serpentine from each qubit to its launchpad.
6. **Coupling.** Four 9 mm λ/2 buses close the ring between neighbouring qubits.
7. **Charge lines.** One line from each qubit's charge pin to its corner pad.
8. **Whole chip.** Sim groups for the FEM jobs, the content centred in the die, the design saved.

## LOM estimates

Numbers are from a run of this notebook on 2026-11-19 (Setup, Design, Check and the LOM cells, 23 s): QuCat normal modes with QuTiP dressed values.

| group | qubit | f_q (GHz) | α (MHz) | resonator | f_r (GHz) | κ (MHz) | χ (MHz) |
|---|---|---|---|---|---|---|---|
| Q1+ol1 | Q1 | 7.126 | -437 | ol1 | 7.012 | 2.74 | 86.4 |
| Q2+ol2 | Q2 | 7.126 | -437 | ol2 | 7.012 | 2.74 | 86.4 |
| Q3+ol3 | Q3 | 7.126 | -437 | ol3 | 7.012 | 2.74 | 86.4 |
| Q4+ol4 | Q4 | 7.126 | -437 | ol4 | 7.012 | 2.74 | 86.4 |

| group | pair | ZZ (kHz) | neighbours | hybridised |
|---|---|---|---|---|
| Q1+cpw1+Q4 | Q1-Q4 | – | yes | yes |
| Q3+cpw2+Q4 | Q3-Q4 | – | yes | yes |
| Q3+cpw3+Q2 | Q2-Q3 | – | yes | yes |
| Q1+cpw4+Q2 | Q1-Q2 | – | yes | yes |

```{image} ../../images/designs/metal/m51_four_qubit_chip_lom.png
:width: 80%
:alt: LOM plot of m51_four_qubit_chip
```

These are lumped-model estimates (component formulas and calibration), not FEM results; see [the LOM page](../../library/lom.md) for how far to trust them.

## Build spec

The rest of this page is the detailed spec the notebook was built from: every component, port, route and length.

> **Update 2026-11-03:** frame = **source**: build with `chip={"die_frame": False, ...}` so the replica keeps its own size and frame (the Quantcore PDK die frame is for Quantcore chips only). `metal:<Class>` wrappers are READY (ports = Metal pin names, params = Metal options), so the `metal:` refs in this spec build as written; the Quantcore/KQC substitutions stay optional.

Source: Quantum Metal `docs/circuit-examples/F.Small-quantum-chips/51-Four_qubit_chip.ipynb`. The same layout, cell for
cell, is in `docs/tut/2-From-components-to-chip/2.21-Design-a-4-qubit-full-chip.ipynb`, so build it once.
Licence Apache-2.0 (© 2017 IBM and contributors). The chip has four `TransmonPocketCL` qubits in a diamond, joined by a
ring of four 9 mm λ/2 bus meanders. Each qubit is read out through an 8.6 mm λ/2 meander that ends on a capacitively
coupled launchpad, and has a charge line to a corner pad.
Chip 9000 × 6500 µm. Notebook 51 sets `size_y` twice, so `size_x` keeps the 9 mm default; 2.21 sets 9 × 6.5 mm
explicitly. The Metal origin is the chip centre, so **Designer = Metal + (4500, 3250)**.
CPW 10/6 µm everywhere, route fillet 99.99 µm. Metal layer 1 only. The junctions are `FakeJunction_01` placeholders.
The Metal substrate is the default silicon, 750 µm thick.
**Buildable now: yes**, with these substitutions: `Xmon` for TransmonPocketCL, `BondPad` + KQC `FingerCapacitorSquare`
for LaunchpadWirebondCoupled, and free-end charge lines.

### Components
Metal TransmonPocketCL options (same for all four qubits): pads 455 × 90 µm, pad_gap 30, pocket 650 × 650. The
connection pads are a (loc_W +1, loc_H −1, pad_width 70), b (−1, −1, 125) and c (−1, +1, 110), all with cpw_extend 50.
The charge line has cl_off_center −50 and cl_pocket_edge 180.
First build: `Xmon(cross_length=300, claws=["n","w","e"])`, with claw_n as the readout claw facing outward.
Faithful build: `metal:TransmonPocketCL` with the options above.

| instance | catalog ref | key params | at (x, y) | rot | notes |
|---|---|---|---|---|---|
| Q1 | `Xmon` (metal:TransmonPocketCL) | see above | (6920, 3319) | 270 (Metal 0) | claw_n→E readout; claw_w→N bus to Q4 (Metal c); claw_e→S bus to Q2 (Metal b) |
| Q2 | `Xmon` | | (4500, 2392.4) | 180 (Metal 270) | claw_n→S readout; claw_w→E bus to Q1 (c); claw_e→W bus to Q3 (b) |
| Q3 | `Xmon` | | (2080, 3319) | 90 (Metal 180) | claw_n→W readout; claw_e→N bus to Q4 (b); claw_w→S bus to Q2 (c) |
| Q4 | `Xmon` | | (4500, 4107.6) | 0 (Metal 90) | claw_n→N readout; claw_e→E bus to Q1 (b); claw_w→W bus to Q3 (c) |
| P1_C … P4_C | `BondPad` (metal:LaunchpadWirebond) | pad_width 80, pad_height 80, pad_gap 58, taper_length 122 (= Metal default pad) | (8045, 6062), (8045, 438), (955, 438), (955, 6062) | 180, 0, 0, 180 | charge-line pads, lead_length 0 |
| P1_Q … P4_Q | `BondPad` (metal:LaunchpadWirebondCoupled) | same pad params | (8520, 3250), (3510, 438), (480, 3250), (5490, 6062) | 90, 0, 270, 180 | readout pads; Metal pos = taper tip |
| C1Q … C4Q | KQC `FingerCapacitorSquare` | defaults (port a at −x, b at +x) | (8420, 3250), (3510, 538), (580, 3250), (5490, 5962) | 0, 90, 0, 90 | stands in for the coupled pad's gap capacitor; sits at the Metal `tie` pin |

All four junctions point to the chip centre (south arm after rotation). Metal pin positions, for reference, in the Designer frame:
Q1 a (7295, 3124) E, b (6545, 3124) W, c (6545, 3514) W, CL (7337, 3364) E.
Q2 a (4305, 2017) S, b (4305, 2767) N, c (4695, 2767) N, CL (4545, 1975) S.
Q3 a (1705, 3514) W, b (2455, 3514) E, c (2455, 3124) E, CL (1663, 3274) W.
Q4 a (4695, 4483) N, b (4695, 3733) S, c (4305, 3733) S, CL (4455, 4525) N.

### Routes
| route | from → to | type, length | waypoints / end | notes |
|---|---|---|---|---|
| cpw1 | Q1.claw_w → Q4.claw_e | meander 9000 | auto | Metal Q1.c→Q4.b, lead 100/250, asymmetry −413.75 |
| cpw2 | Q3.claw_e → Q4.claw_w | meander 9000 | auto | Metal Q3.b→Q4.c, asymmetry +413.75 |
| cpw3 | Q3.claw_w → Q2.claw_e | meander 9000 | auto | Metal Q3.c→Q2.b, asymmetry −551.75 |
| cpw4 | Q1.claw_e → Q2.claw_w | meander 9000 | auto | Metal Q1.b→Q2.c, asymmetry +551.75 |
| ol1 | Q1.claw_n → C1Q.a | meander 8600 | auto | λ/2 readout; Metal lead 430/0, asym +150 |
| ol2 | Q2.claw_n → C2Q.b | meander 8600 | auto | lead 535/0, asym +200 |
| ol3 | Q3.claw_n → C3Q.b | meander 8600 | auto | lead 430/0, asym +150 |
| ol4 | Q4.claw_n → C4Q.a | meander 8600 | auto | lead 535/0, asym +200 |
| t1 … t4 | C1Q.b→P1_Q.a, C2Q.a→P2_Q.a, C3Q.a→P3_Q.a, C4Q.b→P4_Q.a | cpw ≈ 60–100 | — | cap-to-pad stubs |
| CL1 | P1_C.a → `free_end((7337, 3364), dir=0, term=6)` | cpw 3277 | nodes [(8045, 5837), (7457, 5837), (7457, 3364)] | Metal RouteAnchors, reversed |
| CL2 | P2_C.a → `free_end((4545, 1975), dir=-90, term=6)` | cpw 4866 | [(8045, 663), (6500, 663), (6500, 1775), (4545, 1775)] | Metal anchor (2, −2.5) mm |
| CL3 | P3_C.a → `free_end((1663, 3274), dir=180, term=6)` | cpw 3415 | [(955, 663), (1543, 663), (1543, 3274)] | |
| CL4 | P4_C.a → `free_end((4455, 4525), dir=90, term=6)` | cpw 4866 | [(955, 5837), (2500, 5837), (2500, 4725), (4455, 4725)] | Metal anchor (−2, 2.5) mm |

The meander lengths are Metal `total_length`, the full route length from pin to pin. A free end's `dir` equals the
Metal Charge_Line pin normal, and `term=6` gives an open end (Metal charge lines end open in their own etch pocket).

### Launchers, pads, test structures, markers, labels
There are 8 pads: 4 corner charge-line pads (P*_C) and 4 edge readout pads (P*_Q, east/south/west/north). The source
has no markers, labels or test structures. Use the chip defaults (`with_grid` False).

### LOM node structure
- Q1–Q4: each has an island with C to ground and a JJ. Each claw is a coupler node (C_g).
- Bus ring: B1 Q1–Q4, B2 Q3–Q4, B3 Q3–Q2, B4 Q1–Q2. Each is a λ/2 CPW of 9 mm with C_g at both claws.
- Readout: R1–R4 are λ/2 CPWs of 8.6 mm. Each has C_g at the qubit claw and a series C (FingerCapacitorSquare) to a
  50 Ω port P*_Q. There is no shared feedline.
- Control: 4 open charge lines, each a small C_d to the island and a 50 Ω port P*_C. There are no flux lines.

### Targets (if stated)
None are stated. No Lj is set, so take the Metal renderer default, Lj 10 nH and Cj 0: `junction={"Lj_nH": 10,
"Cj_fF": 2}` (Cj 2 fF as in the Metal LOM examples). Rough λ/2 estimates, not targets: 9 mm bus ≈ 7.0 GHz on
sapphire (6.6 on Si), 8.6 mm readout ≈ 7.3 GHz (6.9 on Si).

### Simplifications for a first rebuild
1. Use Xmon for TransmonPocketCL, rotated as in the table, so claw_n faces the readout pad and the two bus claws face
   their neighbours. Ignore the pocket's two-pads-per-side geometry.
2. Replace each coupled launchpad with a BondPad plus a FingerCapacitorSquare at the Metal `tie` pin. This builds a
   λ/2 between the claw and the series cap.
3. Make each charge line a free end (`term=6`) at the Metal pin. The Xmon readout claw sits on the qubit axis, so if
   the DRC flags CL1–CL4 against the readout meander, shift those free ends 150 µm away from the readout axis.
4. Drop the meander asymmetries; set only lengths. Add `nodes` only if a meander collides.

### Quantcore PDK rebuild (2026-11-03)

The notebook is a **Quantcore-PDK rebuild**, not a replica (design rule, 2026-11-03): the netlist, LOM and imported components are kept, the process is Quantcore's.

Notebook: [`examples/designs/metal/m51_four_qubit_chip.ipynb`](../../../examples/designs/metal/m51_four_qubit_chip.ipynb).

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 9 × 6.5 mm chip (the design does not fit the 7.5 mm die); no KQC chip frame.
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); Metal's `DesignPlanar` default is silicon (εr 11.45, 750 µm), so the LOM capacitances, resonator frequencies and FEM jobs here are for sapphire, not the source's substrate.
- **Junctions:** Quantcore Nb/AlOx/Nb trilayer junctions (`junction_type` from `layouts.registry.trilayer_junction`): fingers on 2/0 + 4/0, spacer 50/0 with the 51–53/0 gradient, sized on the PDK junction rule (Nb Δ = 1.4 meV, I_c·R_n = πΔ/2e, R_n·A 13.5 kΩ·µm² and C_J 50 fF/µm² assumed); all four qubits get the PDK nominal junction, 0.5 × 0.6 µm fingers → R_n = 45 kΩ, L_J = 6.73 nH, C_J = 15 fF (in the 40–50 kΩ window) (the source's `FakeJunction_01` has no value; the pre-rebuild build assumed 10 nH + 2 fF). Expected f_q ≈ 7.1 GHz (estimate; were 6.33 GHz): now above the ≈ 6.85 GHz λ/2 buses instead of 0.5 GHz below them.
- **Kept:** the topology and every Metal component with the source's options (through the `metal:` wrapper), positions and orientations, every route's end pins and total length, the sim groups (buses 9000 µm, readouts 8600 µm, the four charge lines).
