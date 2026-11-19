# Qartographer wire routing

Qartographer (MIT) is an optimiser that places drive and readout wire paths from fixed perimeter points to the qubits of a device map, penalising short spacing and long length. Its shipped example is a 7 × 7 (49-qubit) grid, given as JSON.

There is no notebook for this design yet (spec only). The spec below records the data format and the example.

## At a glance

| | |
|---|---|
| Notebook | none yet (spec only) |
| Builds today | not applicable |

## Build spec

The rest of this page is the spec the design would be built from.

> **Update 2026-11-03:** frame = **source**: build with `chip={"die_frame": False, ...}` so the replica keeps its own size and frame (the Quantcore PDK die frame is for Quantcore chips only).

Source: [AYDOSUL/Qartographer](https://github.com/AYDOSUL/Qartographer) (A. Sural) · licence MIT (© 2025, verified) ·
read 2026-11-02: README, INFO.md, `Documentation/JSONguide.md`, `Documentation/7x7 Qubit Placement.json`,
`7x7 Wiring Data.json`. Code (`Code/Qartographer.py`, SciPy optimiser) was not run.
What it is: a cost-function optimiser that places control/readout wire paths from fixed perimeter "drive points" to
qubits, penalising short spacing and long length. JSON in and out (qubit placement, wiring data, merged device map).
The shipped example is a **7 × 7 (49-qubit)** grid. The survey list mentioned 3 × 3 / 5 × 5, but only 7 × 7 data is
in the repo.
Data: coordinates in metres. Qubits are on a **58 µm pitch** (x 677…1025 µm, y −95 µm upward), so this is an
abstract map, not a fab layout. `optimized_couplings` lists NN pairs. Fixed drive points sit on a frame
(x 450…1250 µm, y −700…−200 µm and so on).
Status: **no (abstract map; no component geometry)**. Reference/P3.

### Components / routes
| item | content |
|---|---|
| qubits | Qubit_0…Qubit_48, 7 × 7, 58 µm pitch (scale up ×~25 for a real 1.5 mm pitch) |
| couplings | NN pairs (`qubit1_index`, `qubit2_index`) |
| wiring | one optimised polyline per qubit from a fixed drive point |

### LOM node structure
49-site NN lattice, one control line per qubit. No resonator or feedline information.

### Simplifications for a first rebuild
Use only as a stress test of `Designer.array` plus automatic fan-out. Scale coordinates to a physical pitch first.
