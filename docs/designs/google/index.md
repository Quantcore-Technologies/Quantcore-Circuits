# Google designs

Two rebuilds of Google's tunable-coupler scheme (Sycamore): one qubit-coupler-qubit cell, and a 2 × 2 plaquette that tiles it. No Sycamore layout is public: the papers give the architecture and the targets, and the layouts are ours (GPL). Both use crossed Xmon-type qubits with Quantcore trilayer SQUIDs.

| Page | What it is | Qubits | Chip size | Builds |
|---|---|---|---|---|
| [Coupler cell](google_tc_cell.md) | two qubits joined by a tunable coupler | 2 (+ 1 coupler) | 7.5 × 7.5 mm | yes |
| [Coupler plaquette](google_tc_2x2.md) | four qubits, four couplers, closed square | 4 (+ 4 couplers) | 10 × 10 mm | yes |

```{toctree}
:maxdepth: 1
:hidden:

google_tc_2x2
google_tc_cell
```
