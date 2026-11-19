# MQT SCPD benchmark chips

Eight benchmark chips (4 to 69 qubits) for automatic placement and routing of planar superconducting chips, from the MQT SCPD supplementary data (MIT). The GDS holds an abstract layout: qubits, couplers and launchers are obstacle blocks, and the routed file adds wire footprints.

There is no notebook for these chips yet (spec only). The spec below records the block sizes and layers read from the data.

## At a glance

| | |
|---|---|
| Notebook | none yet (spec only) |
| Builds today | not applicable |

## Build spec

The rest of this page is the spec the design would be built from.

> **Update 2026-11-03:** frame = **source**: build with `chip={"die_frame": False, ...}` so the replica keeps its own size and frame (the Quantcore PDK die frame is for Quantcore chips only). Tunable-coupler blocks can use `metal:TunableCoupler01` as a stand-in; the source chips are abstract blocks, so still **no** for a faithful rebuild.

Source: [cda-tum/planar-superconducting-pd](https://github.com/cda-tum/planar-superconducting-pd). Supplementary data
for Feldmeier, Walter, Huber, Bhattacharjee, Filipp, Wille, *Physical Design Automation for Planar Superconducting
Quantum Chips* (TCAD, under review). The tool is [MQT SCPD](https://github.com/munich-quantum-toolkit/scpd).
Licence MIT (© 2026 MQT, verified). Read 2026-11-02: README, `inputs/*/config.toml`, `inputs/4q/routing_config.json`,
and three small GDS files (4q unrouted and routed, 9q and 17q unrouted, ≤ 134 kB) parsed for block sizes.
What it is: eight benchmark chips for automatic routing. The GDS holds an **abstracted** layout: qubits, couplers and
launchers are obstacle blocks on 1/0. The routed GDS adds wire footprints on 2/0 (22 µm = 10 µm centre + 2 × 6 µm
gaps), 200 × 182 µm resonator–feedline coupler footprints on 3/0, airbridges on 4/0 and clearance zones on 5/0.
There is no qubit geometry, so a rebuild places catalog parts at the block centres.
Status: **no (missing: tunable coupler block / abstract placement only)**. Qubits can be `Xmon` stand-ins; couplers
are 814 × 1420 µm blocks with a flux port and bridge ports.

### Chip families (from README Table I)
| chip | topology | size (mm) | launchers | qubits = |W_r| resonators | feedlines | d_fix (µm) | drive/flux wires |W_p| | bridges |
|---|---|---|---|---|---|---|---|---|
| 4Q | 2 × 2 grid | 6.6 × 7 | 16 | 4 | 1 | 2500 | 8 | 5 |
| 9Q | 3 × 3 grid | 14.3 × 14.3 | 24 | 9 | 2 | 3000 | 21 | 15 |
| 17Q | 3 × 3 core + 8 boundary qubits | 14.3 × 14.3 | 48 | 17 | 4 | 3000 | 41 | 27 |
| 21Q | X-shaped, 1 three-qubit block per corner | 24 × 24 | 72 | 21 | 5 | 4000 | 49 | 33 |
| 33Q | X, 2 blocks per corner | 30 × 30 | 96 | 32* | 6 | 6000 | 78 | 57 |
| 45Q | X, 3 blocks | 35 × 35 | 120 | 45 | 8 | 6000 | 105 | 82 |
| 57Q | X, 4 blocks | 40 × 40 | 152 | 56* | 9 | 6000 | 134 | 101 |
| 69Q | X, 5 blocks | 54 × 54 | 192 | 69 | 12 | 6000 | 163 | 121 |

\* the table lists |W_r| = 32 and 56; the chip names say 33 and 57. Inner-region resonators are routed to d_fix + 3000 µm.
Design rules (all chips): wire clearance 185 µm, obstacle clearance 25 µm, bend radius ≥ 50 µm, straight ≥ 100 µm,
resonator length tolerance 100 µm, feedline capacity r_util 4–7 resonators.

### 4Q in detail (unrouted GDS, 1/0; Designer = source + (−401.5, +1974.8), box (0, 0, 6900, 6800))
| block | size (µm) | centre Designer | catalog stand-in | notes |
|---|---|---|---|---|
| Q_NW | 776 × 680 | (2322.7, 4764.9) | `Xmon` | ports in config: Qn.port0 (resonator), Qn.port1 (drive) |
| Q_SW | 680 × 776 | (2370.7, 2466.9) | `Xmon` | |
| Q_SE | 776 × 680 | (4668.7, 2514.9) | `Xmon` | |
| Q_NE | 776 × 680 | (4682.7, 4764.0) | `Xmon` | |
| C_W / C_E | 814 × 1420 | (2266.2, 3639.2) / (4830.7, 3615.5) | `MISSING: tunable coupler` | Cnm.port0 = flux line; port1/port2 = bridge pair (a wire may cross) |
| C_N / C_S | 1420 × 814 | (3520.0, 4958.9) / (3496.3, 2304.8) | same | |
| port stubs | 182 × 330 / 330 × 182 | 4, next to the qubits | — | resonator port blocks |
| L1…L16 | 500 × 500 | 4 per side, 1600 µm pitch (top x ≈ 1050…5850, y ≈ 6550) | `BondPad` | Chip.port0…15 |

Routed 4Q: one feedline (chain of 5 p2p segments) carrying 4 λ/4 resonators of 2500 µm (coupler footprint
200 × 182 µm on the feedline). 8 launcher-to-port wires (4 drive + 4 coupler flux). 5 airbridges. Total p2p
wirelength 10.32 mm. 2 of the feedline chain ends go to launchers (`launcher_target = 2`).

### LOM node structure (generic)
Each qubit couples to its NN tunable couplers (C, with flux line) and to one λ/4 readout resonator (d_fix). Each
resonator hangs on one of |W_f| feedlines. Each qubit has a drive line. No qubit parameters are given.

### Simplifications for a first rebuild
1. Reference/P3. Use as a routing benchmark: place `Xmon` at the block centres, replace the couplers by direct
   capacitive buses (`cpw` route between claws), then route feedlines and λ/4 hangers of d_fix by hand. Compare
   wirelength and bridge count with `qor/qor.csv`.
2. The larger chips (≥ 21Q) have the same block types. Read the block centres from `layouts/unrouted/gds/<n>q_unrouted.gds`
   (1/0); the files are 68–527 kB.
