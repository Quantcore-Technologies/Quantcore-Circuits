# Community designs

These chips and tools come from public repositories and data sets (licences differ and are named on each page). Five notebooks rebuild a chip on the Quantcore PDK, distributed under GPL-3.0. Three pages are spec only: there is no notebook yet.

| Design | What it is | Qubits | Chip size | Builds |
|---|---|---|---|---|
| [Six-Xmon chip (Litho)](qm2litho_6xmon.md) | Six Xmons with hanger readouts on one feedline | 6 | 5 × 5 mm | yes |
| [12-qubit flux processor (Litho)](qm2litho_12q_flux_processor.md) | Twelve flux-tunable Xmons with flux lines | 12 | 11 × 11 mm | yes |
| [Seven-qubit processor](seven_qubit_processor.md) | A chain of seven transmons with λ/2 buses | 7 | 10 × 10 mm | yes |
| [One-qubit template (SQChip-EM)](sqchip_em.md) | One pocket transmon, a tee and a λ/2 readout | 1 | 7.5 mm die | yes |
| [Near-ms transmon sample (Tuokkola)](tuokkola_near_ms_transmon.md) | Four transmons behind a Purcell filter | 4 | 10 × 10 mm | yes |
| [MQT DASQA mapper](mqt_dasqa.md) | Circuit to square-lattice Metal layout generator (spec only) | 5 | spec | no notebook |
| [MQT SCPD benchmark chips](planar_superconducting_pd.md) | Eight chips for placement and routing (spec only) | 4 to 69 | spec | no notebook |
| [Qartographer wire routing](qartographer.md) | Drive and readout wire optimiser, 7 × 7 map (spec only) | 49 | spec | no notebook |

```{toctree}
:maxdepth: 1
:hidden:

mqt_dasqa
planar_superconducting_pd
qartographer
qm2litho_12q_flux_processor
qm2litho_6xmon
seven_qubit_processor
sqchip_em
tuokkola_near_ms_transmon
```
