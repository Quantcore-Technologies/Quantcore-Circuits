# Resonator-length sweep (chip_02)

A 7.5 mm die with five Xmon qubits on one feedline, like `chip_01_creator`, but each quarter-wave resonator has a
different length (5050, 4850, 4660, 4330 and 4000 µm), so the five qubit-resonator pairs read out at five different
frequencies. It also carries nine junction test pads on the edges. It is a Quantcore internal chip from the QWri
legacy script `chip_02_creator.py`, made to see how the resonator frequency follows its length.

The rebuild draws it from Quantcore PDK parts: each resonator tail runs into its Xmon claw, the pads sit 100 µm from
the die edge, and the PDK frame and cheese are added. Build this one to see how one feedline serves several
resonators of different lengths.

```{figure} ../../images/designs/legacy/chip_02.png
:width: 100%
:alt: chip_02 as rebuilt on the Quantcore PDK

chip_02 as rebuilt on the Quantcore PDK
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/legacy/chip_02.ipynb` (JS = 1.0) |
| Source script | `components/python/chip_02_creator.py` (QWri legacy, Quantcore internal) |
| Chip | 7.5 × 7.5 mm die, 10/6 µm CPW |
| On the chip | 5 Xmons (4 with a junction) · 5 λ/4 resonators, 4000 to 5050 µm · 9 junction test pads |
| Builds today | yes, rebuilt from its JSON on 2026-11-19 in 3.4 s (the notebook itself was not re-run) |

## Pictures

```{figure} ../../images/designs/legacy/chip_02_legacy.png
:width: 70%
:alt: chip_02: the original legacy layout (render of the legacy GDS)

chip_02: the original legacy layout (render of the legacy GDS)
```

```{figure} ../../images/designs/legacy/chip_02.png
:width: 70%
:alt: chip_02: the Quantcore rebuild

chip_02: the Quantcore rebuild
```

```{figure} ../../images/designs/legacy/chip_02_qubit.png
:width: 45%
:alt: An Xmon: the claw at the bottom takes the resonator tail, the junction sits at the tip of the north arm

An Xmon: the claw at the bottom takes the resonator tail, the junction sits at the tip of the north arm
```

```{figure} ../../images/designs/legacy/chip_02_tp1.png
:width: 45%
:alt: One of the nine junction test pads, with its finger-width label

One of the nine junction test pads, with its finger-width label
```

```{figure} ../../images/designs/legacy/chip_02_jj.png
:width: 45%
:alt: The test-pad junction (30 µm box): the two fingers and their overlap

The test-pad junction (30 µm box): the two fingers and their overlap
```

## LOM estimates

The notebook's saved outputs hold no LOM run (its LOM cells were not executed), so there are no estimates to show here and none were computed for this page.

## Build spec

The rest of this page is the detailed spec the notebook was built from: components, positions, parameters and what changed from the legacy script.

Source: `components/python/chip_02_creator.py` (`create_chip(size)`, writes `chip_02_<size>.gds`; no caller in
the library, script default `SCALE` = 1.0). Legacy QWri library, Quantcore internal. Notebook
`examples/designs/legacy/chip_02.ipynb` (JS = 1.0).

### Changes made in the rebuild

- Claws, corrected: every qubit resonator now ends without a gap cap (`ground=False`, the legacy `Coupled Resonator`'s "xmon connector" mode) and its Xmon is snapped with the claw-tail tip onto that end (`snap="claw_n", to="Ri.end"`): galvanic, the claw is the λ/4's open end (as in chips 05/10a). Each Xmon keeps x and rotation and moves along the tail axis (table after the notebook's layout cell). `claw_tail_gap` = legacy `cap_spacing` (6 µm) via `L.xmon`.
- Pads: moved 345 µm inwards of the legacy tips (∓2975 → ∓2630, feedline 5950 → 5260 µm): the rounded pad end on the design-area edge, 100 µm inside the 7.5 mm die, clear of the dicing lane and corner markers.
- Junctions: `Quantcore Junction` sized by the PDK junction rule (Nb trilayer, Δ = 1.4 meV, I_c·R_n = πΔ/2e = 2.20 mV, R_n 40–50 kΩ, qubits 4–8 GHz; PDK process `get_pdk().junction`: R_n·A 13.5 kΩ·µm², C_J 50 fF/µm², both assumed by the PDK) (JS 1.0 → 45 kΩ); AVA test pads keep legacy fingers (PDK process). LOM: f_q ≈ 6.52 GHz, f_r 5.71–7.05 GHz; Q4/R4 (6.60 / 6.48 GHz) hybridised (this depends on R_n per qubit and the lengths).
- The notebook's JSON was rebuilt from its layout cell. The notebook has not been re-run, so its outputs are cleared and its PNGs may be out of date.

What it is: chip_01_creator (spec `chip_01.md`: frame, layers, cell mapping, pads, CLEARER, labels, LOM structure
are the same) with five different resonator lengths at a common 500 µm neck, re-positioned Xmons and nine AVA test
pads. 7.5 × 7.5 mm die centred on (0, 0) → Designer (x + 3750, y + 3750); PDK v2 die frame. Unlike
chip_01_creator, the layer-10 outline and the four 500 µm pad boxes at (±3350, ±3350) are drawn (replaced by the
PDK frame's 100/0 boundary).

Builds: yes (all cells ported, LOM models present). Open: the DRC netlist check reports the five `wire`
couplings as `open` (request); the junction windows are not cleared (components request); labels MISSING.

### Components (legacy frame)

| instance | legacy cell → catalog ref | params (µm) | at (x, y) | rot / mirror |
|---|---|---|---|---|
| FL | Coplanar Waveguide → `CpwSegment` | 5950 → 5460, a/b 10/6, lc/rc 2 | (0, 0) | 0 |
| PL, PR | Connector Pad → `ConnectorPad` | 275 × 300, taper 300, trace 10/6, round; `sim` default True (legacy bug, fab used) | (∓2975, 0) → (∓2730, 0), snapped to FL | 270° / 90° |
| R1 … R5 | Coupled Resonator → `CoupledResonator` | cpw_len 5050 / 4850 / 4660 / 4330 / 4000; neck 500; clength 300, cgap 2, width 300, flip False | (−2000, 26), (−1000, −26), (0, 26), (1000, −26), (2000, 26) | mirror True above / False below |
| Q1 … Q5 | Xmon Cross → `Xmon` | handle 1, thickness 30, width 300, spacing 18, da 3, cap_spacing 6 (see chip_01) | (−2000, 2270), (−1000, −2100), (0, 1910), (1000, −1990), (2000, 1660) | 180° above / 0° below |
| junctions Q1, Q2, Q4, Q5 | `JUNC` (`junction_creator.create_junction`, missing) → `Xmon(junction_type="Trilayer Junction")` | default fingers; LOM: 0.26 × 0.2 (AVA pad, assumed) | (x, y_q ± 159) | mirror below |
| Q3 | no junction (`res_fixed`) → `junction_type="No Squid"` | — | (0, 1910) | 180° |
| CLEARER | 30 × 18 µm cut from 1/0 at (x, y_q ± 159) | MISSING (Xmon keeps the gap etched; requested) | | |
| TP1 | `testPad_AVAQUS` (`TESTAVA`) → `JunctionTestPads(**legacy_test_pad_params("testPad_AVAQUS", 1.0))` | 200 × 300 pads, label "200NM" | (3000, −1500) | 0 |
| TP2 … TP9 | same | same | (∓2500, 3250) r0; (∓2500, −3250) mirror; (−3250, ±2500) r90; (3250, ∓2500) r270 | as listed |
| labels | text "JS=1.0" (−200, 3300), inverted digits 1–5 | MISSING (no text cell) | | |

### Resonator end ↔ claw (as drawn)

| pair | resonator end \|y\| | claw tail tip \|y\| | as drawn |
|---|---|---|---|
| R1/Q1 | 1853.9 | 2018 | 164 µm short (claw tail open into ground → claw grounded) |
| R2/Q2 | 2062.9 | 1848 | overlaps 215 µm (tail gaps cut through the claw) |
| R3/Q3 | 1872.9 | 1658 | overlaps 215 µm |
| R4/Q4 | 1542.9 | 1738 | 195 µm short |
| R5/Q5 | 1621.9 | 1408 | overlaps 214 µm |

Rebuild: geometry as drawn; LOM joins each tail to its claw (`d.couple("W_Qi", "Qi.claw_n", "Ri.end", wire=True)`),
the intended circuit. To be confirmed.

### LOM node structure

As chip_01: `FL.line` (both 50 Ω pads) ─ HANGER κ (`K_Ri`, 300 µm, 2 µm strip) ─ `Ri.res` λ/4 `TLres` (shorted at
the coupler) = `Qi.claw_n` ─ C_g ─ `Qi` island (C, JJ to ground; Q3 without JJ). Bare λ/4 frequencies 6.34, 6.60,
6.87, 7.39, 8.00 GHz (CPW estimate), lowered by the claw load.

### Targets

None stated (the length sweep spans ≈ 6.3–8 GHz bare). Junctions: assumed Jc (to be confirmed).

### Simplifications

As chip_01_creator: pads moved 245 µm inwards (feedline 5460 µm) and drawn in fab mode; Xmon junction at the
cell's default finger widths; CLEARER windows and labels not drawn. Keep-outs: TP2–TP9 reach into the 100 µm die
margin (`frame_margin`, legacy positions kept).
