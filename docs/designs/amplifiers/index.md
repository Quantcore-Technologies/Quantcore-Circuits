# Amplifier designs

Six parametric amplifier chips: two travelling-wave amplifiers (Josephson and kinetic-inductance), three JPAs and a kinetic-inductance amplifier from UNSW. They come from the QPDK and twpa-sim projects (MIT) and from a UNSW dataset (CC BY 4.0), rebuilt on the Quantcore PDK. They share the same six-step build: die, pads, feed, nonlinear element, routing, whole chip. They hold no qubits, so their LOM section reports amplifier figures where the notebook's model gives them.

| Page | What it is | Qubits | Chip size | Builds |
|---|---|---|---|---|
| [Josephson TWPA](jtwpa_4wm.md) | 4WM travelling-wave amplifier, 64-junction chain | 0 | 7.5 × 7.5 mm | yes |
| [Kinetic-inductance TWPA](ki_twpa_serpentine.md) | 16-row serpentine travelling-wave amplifier | 0 | 7.5 × 7.5 mm | yes |
| [Flux-pumped CPW JPA](qpdk_cpw_jpa.md) | λ/4 resonator ending in a SQUID, with pump line | 0 | 7.5 × 7.5 mm | yes |
| [Lumped JPAs](twpa_sim_jpa.md) | capacitively and inductively coupled lumped JPAs | 0 | 7.5 × 7.5 mm | yes |
| [Flux-pumped SQUID JPA](twpa_sim_squid_jpa.md) | lumped SQUID JPA with coupling capacitor and flux line | 0 | 7.5 × 7.5 mm | yes |
| [UNSW KIPA](unsw_kipa.md) | kinetic-inductance amplifier with a stepped-impedance filter | 0 | 4 × 11 mm | yes |

```{toctree}
:maxdepth: 1
:hidden:

jtwpa_4wm
ki_twpa_serpentine
qpdk_cpw_jpa
twpa_sim_jpa
twpa_sim_squid_jpa
unsw_kipa
```
