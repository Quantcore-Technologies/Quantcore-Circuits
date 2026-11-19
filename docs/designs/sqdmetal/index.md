# SQDMetal designs

These chips come from the example notebooks of SQDMetal (Apache-2.0), which drive Qiskit Metal designs through Palace simulations. Each notebook rebuilds one on the Quantcore PDK, with Quantcore versions of the SQDMetal cells (`TransmonTaperedInsets`, the smooth capacitor) or the `metal:` wrappers. They are small one- and two-qubit chips for capacitance and eigenmode runs.

| Design | What it is | Qubits | Chip size | Builds |
|---|---|---|---|---|
| [Two transmons and a bus](2_transmons_wres_comp.md) | Two tapered-inset transmons joined by a λ/2 bus | 2 | 5 × 2 mm area | yes |
| [Floating transmon](floating_transmon.md) | One tapered-inset transmon with a λ/2 readout | 1 | 4 × 4 mm area | yes |
| [Two coupled transmons](two_transmon.md) | Two pocket transmons joined by a straight CPW | 2 | 2.2 × 1.8 mm area | yes |
| [Xmon capacitance](xmon_cap_sim.md) | A cross transmon with an open-ended readout | 1 | 4.6 × 2.4 mm area | yes |

```{toctree}
:maxdepth: 1
:hidden:

2_transmons_wres_comp
floating_transmon
two_transmon
xmon_cap_sim
```
