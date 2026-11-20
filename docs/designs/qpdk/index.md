# QPDK designs

These chips come from gdsfactory's quantum-rf-pdk (QPDK, MIT licence): small test chips for qubits, resonators and interconnect. Each notebook rebuilds one on the Quantcore PDK (sapphire, Quantcore junctions, the QCT die frame, bond pads 100 µm from the edge). The rebuilds are distributed under GPL-3.0.

| Design | What it is | Qubits | Chip size | Builds |
|---|---|---|---|---|
| [Qubit test chip](qubit_test_chip.md) | Four double-pad transmons on a U-shaped probeline | 4 | 7.5 mm die | yes |
| [Filled qubit test chip](filled_qubit_test_chip.md) | The qubit test chip with a vortex-trap fill | 4 | 7.5 mm die | yes |
| [Flipmon test chip](flipmon_test_chip.md) | Four flip-chip circular transmons on a probeline | 4 | 7.5 mm die | yes |
| [Gatemon test chip](gatemon_test_chip.md) | Two nanotube gatemons on λ/2 transmission resonators | 2 | 10 × 10 mm | yes |
| [Resonator test chip](resonator_test_chip.md) | Sixteen λ/4 resonators on two probelines | 0 | 9.2 × 4.3 mm | yes |
| [Vortex neck test chip](vortex_neck_test_chip.md) | Four λ/4 resonators shorted through narrow necks | 0 | 7.5 mm die | yes |
| [Hyperbolic lattice chip](hyperbolic_lattice_chip.md) | {7,3} lattice of 42 CPW resonators joined by three-pin couplers | 0 | 14 × 14 mm | yes |
| [TSV flip-chip test chip](tsv_flip_chip_test_chip.md) | Two lines through all four metal faces, with TSVs and bumps | 0 | 10 × 10 mm | yes |

```{toctree}
:maxdepth: 1
:hidden:

filled_qubit_test_chip
flipmon_test_chip
gatemon_test_chip
hyperbolic_lattice_chip
qubit_test_chip
resonator_test_chip
tsv_flip_chip_test_chip
vortex_neck_test_chip
```
