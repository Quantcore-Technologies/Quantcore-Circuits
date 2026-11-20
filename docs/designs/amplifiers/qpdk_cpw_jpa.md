# Flux-pumped CPW JPA

A Josephson parametric amplifier used in reflection: a λ/4 CPW resonator that couples to the signal line through a finger capacitor and ends in a DC SQUID to ground. The SQUID's flux-dependent inductance tunes the resonance, and a pump line next to it drives the amplification. The design is QPDK's `cpw_jpa` chip (MIT), rebuilt on the Quantcore PDK.

This notebook shows how a reflection amplifier is wired: a signal feed with a coupling capacitor, a meander resonator and a shorted pump line, with a SQUID termination at the end of the resonator.

```{image} ../../images/designs/amplifiers/qpdk_cpw_jpa.png
:alt: The whole qpdk_cpw_jpa chip as the v2 notebook builds it
:width: 100%
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/amplifiers/qpdk_cpw_jpa.ipynb` (an older one-cell version is kept as `qpdk_cpw_jpa.v1.ipynb`) |
| Source | QPDK `cpw_jpa` / `cpw_jpa_chip` (MIT) |
| Chip | 7.5 × 7.5 mm Quantcore die, sapphire 650 µm, CPW 10 / 6 µm |
| On the chip | 1 `SquidTermination` · 1 finger capacitor · 1 λ/4 meander (4664 µm) · signal and pump pads |
| Builds today | yes (layout built on 2026-11-19 in 5 s) |

## How the notebook builds it

The amplifier notebooks use six Design segments (die, pads, feed, nonlinear element, routing, whole chip); see [the notebook template](../notebook-template.md).

```{image} ../../images/designs/amplifiers/qpdk_cpw_jpa_steps.png
:alt: The six layout segments of qpdk_cpw_jpa
:width: 100%
```

1. **Die.** The empty die with the QCT frame.
2. **Bond pads.** A signal pad on the west edge and a pump pad on the east edge, slid to the 100 µm rule.
3. **Signal feed.** The coupling capacitor (8 fingers × 50 µm) and its 50 Ω line from the signal pad.
4. **Nonlinear element.** The SQUID termination, with the largest SQUID the PDK allows.
5. **Routing.** The λ/4 resonator meander from the capacitor to the termination, and the pump line to its pad.
6. **Whole chip.** The target (6.07 GHz at zero flux), the sim groups and the saved design.

## LOM estimates

Numbers are from a run of this notebook on 2026-11-19 (Setup, Design, Check and the LOM cells, 10 s). This is an amplifier, so the LOM section gives gain and phase matching, not qubit frequencies. The readout line has Z0 = 55.1 Ω, v_p = 1.260e8 m/s and C_c = 28.2 fF. The resonance (JPA mode at 5.736 GHz, κ = 19.8 MHz in QuCat) moves with the SQUID inductance and flux:

| SQUID | L_s(0) (nH) | f0 (GHz) | κ/2π (MHz) | Q_ext |
|---|---|---|---|---|
| drawn PDK SQUID | 0.253 | 5.784 | 21.2 | 272 |
| QPDK source SQUID | 0.0686 | 6.262 | 26.9 | 233 |
| no SQUID | 0 | 6.463 | 29.5 | 219 |

| SQUID | f0 at 0.3 Φ0 (GHz) | κ/2π (MHz) | df0/dΦ (GHz/Φ0) | threshold Φ_p (mΦ0) |
|---|---|---|---|---|
| drawn PDK SQUID | 5.399 | 17.4 | -3.72 | 4.67 |
| QPDK source SQUID | 6.129 | 25.2 | -1.38 | 18.3 |

Flux-pumped gain of the drawn SQUID against the pump strength r:

| r | peak gain (dB) | pump flux Φ_p (mΦ0) | -3 dB bandwidth (MHz) |
|---|---|---|---|
| 0.5 | 4.44 | 2.34 | 13.6 |
| 0.7 | 9.31 | 3.27 | 5.56 |
| 0.8 | 13.2 | 3.74 | 3.48 |
| 0.9 | 19.6 | 4.21 | 1.74 |

```{image} ../../images/designs/amplifiers/qpdk_cpw_jpa_lom.png
:width: 80%
:alt: Flux-pumped gain of the JPA
```

These are lumped-model estimates (component formulas and calibration), not FEM results. [The LOM page](../../library/lom.md) says how far to trust them.

## Build spec

The rest of this page is the detailed spec the notebook was built from, with every component, port, route and length.

Source · licence: gdsfactory/quantum-rf-pdk (MIT): `qpdk/cells/parametric_amplifier.py`, `qpdk/samples/cpw_jpa_chip.py`, notebook `vacask_cpw_parametric_amplifier` (Yamamoto 2008; Pogorzalek 2017). Die: 7.5 × 7.5 mm PDK die, PDK frame, sapphire 650 µm, Nb trilayer junctions. Notebook and design: `examples/designs/amplifiers/qpdk_cpw_jpa.ipynb` / `.json`.

### Components

| instance | catalog ref | key params | notes |
|---|---|---|---|
| P_SIG, P_PUMP | `BondPad` | west / east edge, `edge="auto"` | |
| CC | `FingerCapacitorSquare` | 8 fingers × 50 µm, 5 µm wide, 2 µm gap (≈ 28 fF) | |
| ST | `SquidTermination` | lead 10 µm + 6 × 28 µm head, 20 × 34 µm pocket, largest PDK SQUID (2 × 2.0 × 2.0 µm), pump 200 µm / 2 µm strip / 20 µm offset | |

### Routes

| route | from → to | type |
|---|---|---|
| L_SIG | P_SIG.a → CC.a | CPW 10/6 |
| JPA | CC.b → ST.a | meander 4664 µm, 6 meanders at r = 30 µm (6 turns need 2·r·7 ≤ the 478 µm straight; λ/4 = 4680 µm with the lead + head) |
| L_PUMP | ST.pump → P_PUMP.a | CPW, one waypoint |

### LOM node structure

pad (50 Ω), then C_c, then a λ/4 TLres (route plus a termination at its equivalent length lead + L_s/L'); the pump is a flux control

### Targets (from the source)

QPDK: 6.07 GHz at Φ = 0, Q_ext ≈ 290 (its stack, I_c 4.8 µA)

### Simplifications / PDK differences

SQUID I_c 1.3 µA instead of 4.8 µA (PDK junction rule); sapphire + Nb kinetic inductance; bond pads instead of launchers; junctions are flagged `pdk_rn` where present (amplifier junctions are far below the qubit R_n window).
