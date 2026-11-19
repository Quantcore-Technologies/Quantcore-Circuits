# MQT DASQA mapper

MQT DASQA (MIT) is a generator, not a fixed chip: a QASM circuit gives a qubit-connectivity profile, which gives a square-lattice placement with yield-optimised frequencies, which is mapped to a Qiskit Metal layout. Its shipped example has five pocket qubits in a plus.

There is no notebook for this design yet (spec only). The spec below records what the mapper produces and what a Quantcore rebuild would need.

## At a glance

| | |
|---|---|
| Notebook | none yet (spec only) |
| Builds today | not applicable |

## Build spec

The rest of this page is the spec the design would be built from.

> **Update 2026-11-03:** frame = **source**: build with `chip={"die_frame": False, ...}` so the replica keeps its own size and frame (the Quantcore PDK die frame is for Quantcore chips only). `metal:<Class>` wrappers are READY (ports = Metal pin names, params = Metal options), so the `metal:` refs in this spec build as written; the Quantcore/KQC substitutions stay optional. Buildable now: **yes** (`metal:TransmonPocket6`, `metal:CapNInterdigital`).

Source: [cda-tum/mqt-dasqa](https://github.com/cda-tum/mqt-dasqa) (arXiv:2305.07052) · licence MIT (© 2023 Jagatheesan
Jack, verified) · read 2026-11-02: README, mapper code (`src/mapper/qubit/metal/transmon_pocket_6_qubit.py`,
`capacitor/metal/capacitor.py`, `launchpad/metal/launchpad.py`), example image `docs/images/4_qubit_2D_square_lattice.png`.
No stored layout or GDS (the output is a live Metal design).
What it is: a generator. A QASM circuit gives a qubit-connectivity profile, which gives a square-lattice placement
with yield-optimised frequencies, which is mapped to Metal: `TransmonPocket6` qubits, `RouteMeander` buses, and per
qubit an interdigital `CapNInterdigital` readout capacitor plus a meander to a `LaunchpadWirebond`. The shipped image
(titled "4 qubit 2D square lattice") shows **5 qubits** in a plus: Q_4 in the centre with Q_0, Q_1, Q_2, Q_3 around it.
Generator: qubit at grid (x, y) is placed at (3500·x, 3000·y) µm, orientation −90. Connection pads B0 (−1, −1, 75 µm),
B1 (−1, +1, 120), B2 (+1, −1, 120), B3 (+1, +1, 90), plus B4 (0, −1, 90) on inner rows. Unused pads are removed.
Frame (example): qubits at (0, 3), (3.5, 0), (3.5, 3), (3.5, 6), (7, 3) mm, launchpads ≈ 2 mm outside the plus. Use
**box (0, 0, 11000, 12000)**, **Designer = source + (2500, 2500)** (estimated from the image).
Status: **metal (`metal:TransmonPocket6`, `metal:CapNInterdigital`)**. Reference/P3.

### Components / routes (example)
| item | catalog ref | notes |
|---|---|---|
| Q_0…Q_4 | `metal:TransmonPocket6` · stand-in `Xmon` (claws n/w/e) | pocket defaults. f_Q from the yield simulator, with EJ/EC 50 (config.yml) |
| CS_3_4, CU_2_4, CU_4_1, CS_4_0 | meander buses centre ↔ neighbour | `RouteMeander`, lengths from the optimiser |
| C_k + readout meander + Launch_Readout_k | `metal:CapNInterdigital` · stand-in `FingerCapacitorSquare`, then route, then `BondPad` | each qubit: capacitor → meander resonator → pad |

### LOM node structure
Star: Q_4 bus-coupled to 4 neighbours. Each qubit has a resonator capacitively coupled to its own launcher (no shared feedline).

### Simplifications for a first rebuild
Not a rebuild target. Its value is the flow: placement on a 3.5 × 3.0 mm grid from a circuit profile. A Quantcore
analogue is `lom.synthesize` driving `Designer.array`.
