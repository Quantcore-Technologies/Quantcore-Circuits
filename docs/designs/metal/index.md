# Metal designs

These designs are Qiskit Metal examples and tutorials (Apache-2.0, © IBM and the Qiskit Metal contributors), rebuilt
with the Quantcore library and PDK and distributed under GPL-3.0. Each notebook keeps the source's components and
routes, but puts them on the Quantcore stack (sapphire), junctions and die frame, and moves bond pads to the PDK's
100 µm edge rule. Metal components are drawn through the `metal:<Class>` wrapper.

Every notebook builds the layout in segments (die, pads, readout, qubits, coupling, control lines, whole chip). All 19
build today (layout run 2026-11-19, design byte-identical to the one before the notebook rewrite). Start with
[Transmon with readout](A1_transmon_readout.md) for the smallest complete chip.

| Design | What it is | Qubits | Chip size | Builds |
|---|---|---|---|---|
| [Four-qubit ring (Metal 51)](51_four_qubit_chip.md) | Four pocket transmons, ring of buses, coupled-pad readouts | 4 | 9 × 6.5 mm | yes |
| [Barends five-qubit (Metal 52)](52_barends_5q.md) | Five Xmons in a line, shared feedline, XY and Z lines | 5 | 7.5 mm die | yes |
| [Wallraff 17-qubit (Metal 53)](53_wallraff_17q.md) | ETH surface-code device: 17 star qubits, 4 feedlines | 17 | 14.4 × 14.4 mm | yes |
| [Wallraff two-qubit cell (Metal 54)](54_wallraff_cell.md) | Two star qubits and their coupler, cut out for meshing | 2 | cut-out on 7.5 mm die | yes |
| [Transmon with readout (Metal A.1)](A1_transmon_readout.md) | One transmon, λ/4 readout, coupled-line tee, feedline | 1 | 9 × 6 mm | yes |
| [Two coupled transmons (Metal A.2)](A2_two_coupled.md) | Two transmons, 8 mm bus, readouts on one feedline | 2 | 14 × 9 mm | yes |
| [Four-qubit mux (Metal A.3)](A3_four_qubit_mux.md) | Four uncoupled transmons, multiplexed readout on one feedline | 4 | 16 × 9 mm | yes |
| [Full chip (Metal A.4)](A4_full_chip.md) | Hub qubit, tunable coupler, flux lines, multiplexed feedline | 6 | 12.2 × 9.2 mm | yes |
| [Launch-video chip (Metal A.5)](A5_launch_video.md) | Four-qubit ring, charge lines, 15/9 µm CPW | 4 | 10.2 × 7.4 mm | yes |
| [Hackathon chip (Metal A.6)](A6_hackathon_2q.md) | Two charge-line transmons, direct coupling, capacitor readout | 2 | 9 × 6 mm | yes |
| [IMS 2022 workshop chip (Metal A.7)](A7_ims2022_3q.md) | Three all-to-all coupled transmons with stated targets | 3 | 7.5 mm die | yes |
| [Component examples (Metal A–E)](component_examples.md) | Catalogue board of 19 single-component examples | tiles | 35 × 28 mm | yes |
| [Flip-chip qubit and resonator](flipchip_qubit_resonator.md) | Crossmon on the top chip over a resonator on the bottom | 1 | 7.5 mm die, two faces | yes |
| [iSWAP 1: concentric transmons](iswap1_concentric_direct.md) | Two mm-scale concentric transmons, direct coupling | 2 | 32 × 25 mm | yes |
| [iSWAP 2: pockets and coupler](iswap2_pocket_tc.md) | Two pocket transmons with a tunable coupler | 2 | 16 × 6 mm | yes |
| [iSWAP 3: crossmons and coupler](iswap3_xmon_tc.md) | Two crossmons, tunable coupler, open meanders | 2 | 7.5 mm die | yes |
| [Four-qubit ring (tutorial 1.3)](tut13_four_qubit_ring.md) | Four pocket transmons in a ring of buses, nothing else | 4 | 7.5 mm die | yes |
| [100-qubit grid (tutorial 2.22)](tut222_100q_grid.md) | 10 × 10 brick lattice of pocket transmons and buses | 100 | 33 × 33 mm | yes |
| [10 × 10 package array (tutorial 4.43)](tut443_10x10_package.md) | 100 bare two-paddle transmons for a package-mode study | 100 | 30 × 30 mm | yes |

```{toctree}
:maxdepth: 1
:hidden:

51_four_qubit_chip
52_barends_5q
53_wallraff_17q
54_wallraff_cell
A1_transmon_readout
A2_two_coupled
A3_four_qubit_mux
A4_full_chip
A5_launch_video
A6_hackathon_2q
A7_ims2022_3q
component_examples
flipchip_qubit_resonator
iswap1_concentric_direct
iswap2_pocket_tc
iswap3_xmon_tc
tut13_four_qubit_ring
tut222_100q_grid
tut443_10x10_package
```
