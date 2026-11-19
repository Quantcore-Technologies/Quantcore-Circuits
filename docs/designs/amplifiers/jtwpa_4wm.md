# Josephson TWPA (4WM)

A Josephson travelling-wave parametric amplifier: a transmission line made of a long chain of junctions with a capacitor to ground at every cell. A strong pump and the signal mix into an idler (four-wave mixing) and the signal grows along the line. Small resonators on every few cells keep the three waves in phase. The circuit comes from the QPDK `josephsoncircuits_twpa` notebook and the layout family from twpa-sim `jtwpa4wm` (both MIT), rebuilt on the Quantcore PDK.

Build this one to see how a chain amplifier is laid out: two pads, two plain feeds and one chain component between them. The drawn chain is shortened to 64 cells (the source circuit has 2047), and the junction is the largest the PDK allows.

```{image} ../../images/designs/amplifiers/jtwpa_4wm.png
:alt: The whole jtwpa_4wm chip as the v2 notebook builds it
:width: 100%
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/amplifiers/jtwpa_4wm.ipynb` (the one-cell version before the rewrite: `jtwpa_4wm.v1.ipynb`) |
| Source | QPDK notebook `josephsoncircuits_twpa` (MIT) and twpa-sim `jtwpa4wm` (MIT) |
| Chip | 7.5 × 7.5 mm Quantcore die, sapphire 650 µm, CPW 10 / 6 µm |
| On the chip | 1 `JtwpaChain` (64 junctions, 60 µm pitch, a resonator every 4th node) · 2 bond pads · 2 feeds |
| Builds today | yes: layout run 2026-11-19, 5 s, the saved design is byte-identical to the one before the rewrite |

## How the notebook builds it

The amplifier notebooks use six Design segments (die, pads, feed, nonlinear element, routing, whole chip); see [the notebook template](../notebook-template.md).

```{image} ../../images/designs/amplifiers/jtwpa_4wm_steps.png
:alt: The six layout segments of jtwpa_4wm
:width: 100%
```

1. **Die.** The empty 7.5 × 7.5 mm die with the QCT frame and the device ID `JTWPA`.
2. **Bond pads.** An input pad on the west edge and an output pad on the east edge, slid to the 100 µm pad-edge rule.
3. **Feed lines.** No cell: the pump and signal share the chain's own line, and the feeds are drawn in segment 5.
4. **Nonlinear element.** The 64-junction chain, with the junction sized to the PDK limit and the drawn values tabulated against the source.
5. **Routing.** Two straight 50 Ω feeds, pad to chain and chain to pad.
6. **Whole chip.** The chain's sim group (for a Q3D job) and the saved design.

## LOM estimates

Numbers are from a run of this notebook on 2026-11-19 (Setup, Design, Check and the LOM cells, 6 s). This is an amplifier, so the LOM section gives gain and phase matching, not qubit frequencies. The 4WM coupled-mode gain of the source circuit (2047 cells, pump at 7.12 GHz, I_p = 1.85 µA) is compared with the source's harmonic-balance result at 5 GHz:

| chain | G at 5 GHz (dB) | Δβ at 5 GHz (rad/junction) | QPDK harmonic balance (dB) |
|---|---|---|---|
| uniform | 6.174 | -0.003777 | about 5 |
| loaded | 21.32 | 0.001488 | about 25 |

The drawn 4-cell unit, extended to 2047 cells at the same (I_p/I_c)², is not phase matched: q_p = 0.206 rad/junction at 7.12 GHz (the source has 0.096) and G at 5 GHz is about 0.1 dB (Δβ = -0.0428 rad/junction). The numbers say what the PDK cell would need (larger C_g and resonator C) rather than predict a device.

```{image} ../../images/designs/amplifiers/jtwpa_4wm_lom.png
:width: 80%
:alt: 4WM gain of the uniform and the loaded chain
```

These are lumped-model estimates (component formulas and calibration), not FEM results; see [the LOM page](../../library/lom.md) for how far to trust them.

## Build spec

The rest of this page is the detailed spec the notebook was built from: every component, port, route and length.

Source · licence: gdsfactory/quantum-rf-pdk (MIT) notebook `josephsoncircuits_twpa` (O'Brien 2014; Peng 2022); twpa-sim (MIT) `jtwpa4wm`. Group `amplifiers` (design decision #45). Die: 7.5 × 7.5 mm PDK die, PDK frame, sapphire 650 µm, Nb trilayer junctions. Status: built — `examples/designs/amplifiers/jtwpa_4wm.ipynb` / `.json`.

### Components

| instance | catalog ref | key params | notes |
|---|---|---|---|
| P_IN, P_OUT | `BondPad` | west / east edge | |
| JT | `JtwpaChain` | 64 junctions (PDK max), 60 µm pitch, 4 shunt fingers/side, resonator every 4th node (offset 2), alternating sides | |

### Routes

| route | from → to | type |
|---|---|---|
| L_IN | P_IN.a → JT.a | CPW |
| L_OUT | JT.b → P_OUT.a | CPW |

### LOM node structure

65 island nodes, 64 JJ, C_g per node, 16 resonators (C_c, C_r, L_r); linear AC via nodal analysis, gain via coupled modes

### Targets (from the source)

QPDK: ≈ 25 dB (loaded) / ≈ 5 dB (uniform) at 5 GHz, 2047 cells, I_c 3.4 µA, C_J 55 fF, C_g 45 fF, 2.8153 pF ∥ 170 pH every 4th cell

### Simplifications / PDK differences

64-cell chain on the die (the 2047-cell circuit in the analysis); PDK junction; drawn C_g / C_r far below the source's
; junctions are flagged `pdk_rn` where present (amplifier junctions are far below the qubit R_n window).
