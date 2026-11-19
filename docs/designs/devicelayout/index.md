# DeviceLayout designs

Two chips from AWS's DeviceLayout.jl examples (MIT): a single transmon with a clawed readout, and the 17-qubit surface-code demo. The rebuilds on the Quantcore PDK are distributed under GPL-3.0. The surface-17 chip is plan-driven: a shared generator plans every part first and the notebook places them kind by kind.

| Page | What it is | Qubits | Chip size | Builds |
|---|---|---|---|---|
| [SingleTransmon](singletransmon.md) | one transmon with a clawed λ/4 readout | 1 | 7.5 × 7.5 mm | yes |
| [DemoQPU17](demoqpu17.md) | 17-qubit surface-code demo with Purcell-filtered readout | 17 | 15 × 15 mm | yes |

```{toctree}
:maxdepth: 1
:hidden:

demoqpu17
singletransmon
```
