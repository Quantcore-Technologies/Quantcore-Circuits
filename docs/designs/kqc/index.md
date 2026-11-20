# KQC designs

These designs come from KQCircuits (KQC), IQM Finland's open-source chip library (GPL-3.0). Each notebook rebuilds one KQC chip on the Quantcore PDK: sapphire, the Quantcore die frame, the 100 µm bond-pad rule and Quantcore trilayer junctions. The topology and every KQC element keep the source's parameters. All chips are 10 × 10 mm.

| Page | What it is | Qubits | Chip size | Builds |
|---|---|---|---|---|
| [Demo chip](demo.md) | KQC's four-qubit ring with two probe lines | 4 | 10 × 10 mm | yes |
| [Demo chip, two faces](demo_twoface.md) | the Demo chip split over a flip chip | 4 | 10 × 10 mm | yes |
| [MunchQubits](munch_qubits.md) | circular transmons, resonant coupler, double-pad qubit | 3 | 10 × 10 mm | yes |
| [QualityFactor](quality_factor.md) | six quarter-wave resonators on one feedline | 0 | 10 × 10 mm | yes |
| [SingleXmons](single_xmons.md) | six Swissmons on one feedline | 6 | 10 × 10 mm | yes |
| [XMonsDirectCoupling](xmons_direct_coupling.md) | three directly coupled Swissmons | 3 | 10 × 10 mm | yes |
| [DaisyWoven bump test](daisy_woven.md) | flip-chip indium-bump daisy chains | 0 | 10 × 10 mm | yes |
| [KQC test chips](test_chips.md) | 14 process and part tests (airbridges, lithography, TSVs, `simple`, `shaping` ...) | 0 to 1 | 10 × 10 mm | yes (all 14) |
| [Quick demo mask](quick_demo_mask.md) | a 6-inch wafer of 36 Demo chips and 17 empty chips in a smiley | 4 per Demo chip | 6-inch wafer | yes |

```{toctree}
:maxdepth: 1
:hidden:

daisy_woven
demo
demo_twoface
munch_qubits
quality_factor
quick_demo_mask
single_xmons
test_chips
xmons_direct_coupling
```
