# Legacy designs

These are Quantcore's own earlier chips: test chips, resonator chips and small qubit chips from the in-house QWri library and from Qiskit Metal design notebooks. Each page is a spec rebuilt on the Quantcore PDK (junctions follow the PDK rule). It opens with what the chip is, a whole-chip picture, an at-a-glance table, zooms and the saved LOM estimates, and keeps the full spec below. "Builds" says whether the saved design JSON rebuilt without error on 2026-11-19 (the notebooks were not re-run). Chip 01 also exists as a 4 × 4 wafer tiling (30 × 30 mm).

| Page | What it is | Qubits | Resonators | Chip size | Builds |
|---|---|---|---|---|---|
| [chip_01](chip_01.md) | five Xmons and five λ/4 resonators on one feedline | 5 | 5 | 7.5 × 7.5 mm | yes |
| [chip_02](chip_02.md) | chip_01 with a resonator-length sweep | 5 | 5 | 7.5 × 7.5 mm | yes |
| [chip_03](chip_03_trilayer.md) | nine Xmons and ten resonators, Nb trilayer | 9 | 10 | 7.5 × 7.5 mm | yes |
| [chip_04](chip_04_test_chip_tl.md) | 45 trilayer junction test pads | 0 | 0 | 7.5 × 7.5 mm | yes |
| [chip_05](chip_05_flux_tlqubits.md) | seven Xmons (two flux-tunable), eight resonators | 7 | 8 | 7.5 × 7.5 mm | yes |
| [chip_06](chip_06_test_cyro_tlq.md) | 24 HSQ junction test pads with bond rings | 0 | 0 | 7.5 × 7.5 mm | yes |
| [chip_07](chip_07_resonators.md) | six hanger resonators on one feedline | 0 | 6 | 7.5 × 7.5 mm | yes |
| [chip_08](chip_08_tl_hsq_testpads.md) | 45 HSQ trilayer junction test pads | 0 | 0 | 7.5 × 7.5 mm | yes |
| [chip_09](chip_09_resonators_expt.md) | six resonators on a serpentine feedline | 0 | 6 | 7.5 × 7.5 mm | yes |
| [chip_10a](chip_10a_3x_squid.md) | the 3X SQUID junction cell | 0 | 0 | 7.5 × 7.5 mm | yes |
| [chip_10a](chip_10a_flux_tlqubits.md) | chip_05 revision, seven Xmons, eight resonators | 7 | 8 | 7.5 × 7.5 mm | yes |
| [chip_11f](chip_11f_jjplacer.md) | junction cell on 16 probe-pad pairs | 0 | 0 | 7.5 × 7.5 mm | yes |
| [chip_11m](chip_11m_testjj16x_pads.md) | the compact junction cell `JX_500` | 0 | 0 | 7.5 × 7.5 mm | yes |
| [Design 12](d12_coupled_chip.md) | nine Xmons, direct pair, tunable-coupler triple | 9 | 9 | 7.5 × 7.5 mm | yes |
| [Design 14](d14_two_feedline_resonator.md) | two feedlines, twelve resonators, six Xmons | 6 | 12 | 10 × 10 mm | yes |
| [KI spirals and a finger-loaded TWPA-style line](ki_twpa_structures.md) | KI spirals and a finger-loaded TWPA-style line | 0 | 0 | 7.5 × 7.5 mm | yes |
| [resonator_chip_01](resonator_chip_01.md) | five resonators, no Xmons | 0 | 5 | 7.5 × 7.5 mm | yes |

```{toctree}
:maxdepth: 1
:hidden:

chip_01
chip_02
chip_03_trilayer
chip_04_test_chip_tl
chip_05_flux_tlqubits
chip_06_test_cyro_tlq
chip_07_resonators
chip_08_tl_hsq_testpads
chip_09_resonators_expt
chip_10a_3x_squid
chip_10a_flux_tlqubits
chip_11f_jjplacer
chip_11m_testjj16x_pads
d12_coupled_chip
d14_two_feedline_resonator
ki_twpa_structures
resonator_chip_01
```
