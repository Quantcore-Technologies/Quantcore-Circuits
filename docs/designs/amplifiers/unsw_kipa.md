# UNSW KIPA

A kinetic-inductance parametric amplifier: a λ/4 resonator on a high-kinetic-inductance film, closed at one end by a stepped-impedance filter (a Bragg mirror that still passes DC). In the source device the shorted end is a 1 µm wire that sits over bismuth donor spins. The source is the UNSW device BA13 GDS (Zenodo 7600250, CC BY 4.0); the rebuild draws the same section sequence with Quantcore routes.

This notebook shows how a chip made of many line sections of different widths is assembled: tapers at every section boundary, one route per section, and positions solved so each section keeps its source length.

```{image} ../../images/designs/amplifiers/unsw_kipa.png
:alt: The whole unsw_kipa chip as the v2 notebook builds it
:width: 100%
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/amplifiers/unsw_kipa.ipynb` (an older one-cell version is kept as `unsw_kipa.v1.ipynb`) |
| Source | Zenodo 7600250, `BA13_device_gds.GDS` (CC BY 4.0; Vine et al., arXiv:2211.11333) |
| Chip | 4 × 11 mm (the source die), Quantcore frame, sapphire |
| On the chip | 9 `CpweTaper`s · 1 bond pad · 9 routes (feed, 7 filter sections, resonator) and the 1 µm wire |
| Builds today | yes (layout built on 2026-11-19 in 5 s) |

## How the notebook builds it

The amplifier notebooks use six Design segments (die, pads, feed, nonlinear element, routing, whole chip); see [the notebook template](../notebook-template.md).

```{image} ../../images/designs/amplifiers/unsw_kipa_steps.png
:alt: The six layout segments of unsw_kipa
:width: 100%
```

1. **Die.** The source's 4 × 11 mm die with the QCT frame and the device ID `KIPA`.
2. **Bond pad.** One pad on the south edge, ending in the 100 / 45 µm feed (the device's only port).
3. **Feed.** The section plan, the first taper and the wide feed.
4. **Nonlinear element.** The tapers at each section boundary of the filter and the resonator.
5. **Routing.** The filter sections S0 to S6, the resonator, and the spin wire (shorted at its end).
6. **Whole chip.** The `resonator` sim group and the saved design.

## LOM estimates

Numbers are from a run of this notebook on 2026-11-19 (Setup, Design, Check and the LOM cells, 5 s). This is an amplifier, so the LOM section gives gain and phase matching, not qubit frequencies. The notebook models the KIPA as a cascade of transmission-line sections (Nb kinetic inductance included). The SIF stop band (attenuation above 0.5 Np per period) spans 5.84 to 12.61 GHz, and the resonance inside it sits at 11.72 GHz with κ/2π of about 2.82 MHz (Q_ext about 4160). There is no gain figure in this section.

| section | a/b (µm) | Z0 (Ω) | length (µm) |
|---|---|---|---|
| S0, S2, S4 | 138/6 | 27.6 | 3400 |
| S1, S3, S5 | 10/70 | 105 | 3460 |
| S6 | 138/6 | 27.6 | 3390 |
| RES | 5/15 | 86.3 | 2980 |
| WIRE | 1/10 | 120 | 1750 |

```{image} ../../images/designs/amplifiers/unsw_kipa_lom.png
:width: 80%
:alt: Reflection phase and stop band of the KIPA
```

These are lumped-model estimates (component formulas and calibration), not FEM results. [The LOM page](../../library/lom.md) says how far to trust them.

## Build spec

The rest of this page is the detailed spec the notebook was built from, with every component, port, route and length.

Source · licence: Zenodo 7600250 (Vine et al., arXiv:2211.11333), CC BY 4.0, `BA13_device_gds.GDS` (read only from `build/external/kipa_zenodo_7600250/`). Die 4 × 11 mm (source die), PDK frame, sapphire, Nb. Notebook and design: `examples/designs/amplifiers/unsw_kipa.ipynb` / `.json`.

### Components

| instance | catalog ref | key params | notes |
|---|---|---|---|
| P_IN | `BondPad` | a/b 100/45, south edge | the source bonds onto the feed |
| T0 … T8 | `CpweTaper` | 20 µm, section a/b → next a/b | section boundaries, positions solved for the section lengths |

### Routes

| route | from → to | type |
|---|---|---|
| FEED | P_IN.a → T0.a | 100/45 µm |
| S0, S2, S4, S6 | T(k).b → T(k+1).a | 138/6 µm, 3400 / 3400 / 3400 / 3394 µm, U-turn r 300 µm |
| S1, S3, S5 | T(k).b → T(k+1).a | 10/70 µm, 3455 µm |
| RES | T7.b → T8.a | 5/15 µm, 2981 µm |
| WIRE | T8.b → free end (term 0, short) | 1/10 µm, 1750 µm |

### LOM node structure

One chain of lines from the pad to the short (the builder's one-Z0 line: a wire on the pad node); the stepped-impedance
filter and the resonator are simulated as a TL cascade of the drawn sections in the notebook.

### Targets (from the source)

None stated in the GDS (the paper's NbTiN film and frequencies are not in the record).

### Simplifications / PDK differences

Our serpentine (300 µm U-turns) and tapers at the section boundaries; Quantcore BondPad on the feed; PDK Nb instead of
the source's kinetic film (resonance and nonlinearity differ). No junctions.
