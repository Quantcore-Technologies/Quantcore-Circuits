# Flux-tunable qubit chip (chip_05)

A 7.5 mm die with seven Xmon qubits and eight quarter-wave resonators on one feedline. Two of the qubits (Q4 and Q5)
have a SQUID instead of a single junction and a flux line from a small pad at the top or bottom edge, so their
frequency can be tuned with a current. The chip also has flux-trap hole arrays, two HSQ junction test pads and HSQ
corner markers. It is Quantcore's own chip from the QWri legacy script `chip_05_flux_TLQubits.py` (May 2024), the one
that tests flux tuning.

The rebuild draws it from Quantcore PDK parts: the flux lines are routed with the PDK router and the resonator tails
run into the claws. Build this one to learn flux lines and SQUID qubits next to a readout feedline.

```{figure} ../../images/designs/legacy/chip_05_flux_tlqubits.png
:width: 100%
:alt: chip_05_flux_tlqubits as rebuilt on the Quantcore PDK

chip_05_flux_tlqubits as rebuilt on the Quantcore PDK
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/legacy/chip_05_flux_tlqubits.ipynb` |
| Source script | `components/python/chip_05_flux_TLQubits.py` (QWri legacy, Quantcore internal) |
| Chip | 7.5 × 7.5 mm die, 10/6 µm CPW |
| On the chip | 7 Xmons (Q4, Q5 SQUIDs) · 8 λ/4 resonators · 2 flux lines (4/6 µm) · 8 hole arrays · 2 HSQ test pads · 4 HSQ corner markers |
| Builds today | yes, rebuilt from its JSON on 2026-11-19 in 2.5 s (the notebook itself was not re-run) |

## Pictures

```{figure} ../../images/designs/legacy/chip_05_flux_tlqubits_legacy.png
:width: 70%
:alt: chip_05_flux_tlqubits: the original legacy layout (render of the legacy GDS)

chip_05_flux_tlqubits: the original legacy layout (render of the legacy GDS)
```

```{figure} ../../images/designs/legacy/chip_05_flux_tlqubits.png
:width: 70%
:alt: chip_05_flux_tlqubits: the Quantcore rebuild

chip_05_flux_tlqubits: the Quantcore rebuild
```

```{figure} ../../images/designs/legacy/chip_05_flux_tlqubits_q4.png
:width: 45%
:alt: Q4, a qubit with a flux line: the line arrives at the top, the resonator tail at the claw

Q4, a qubit with a flux line: the line arrives at the top, the resonator tail at the claw
```

```{figure} ../../images/designs/legacy/chip_05_flux_tlqubits_q1.png
:width: 45%
:alt: Q1, a single-junction qubit, for comparison

Q1, a single-junction qubit, for comparison
```

```{figure} ../../images/designs/legacy/chip_05_flux_tlqubits_tp1.png
:width: 45%
:alt: An HSQ junction test pad

An HSQ junction test pad
```

## LOM estimates

The notebook's saved outputs hold no LOM run (its LOM cells were not executed), so there are no estimates to show here and none were computed for this page.

## Build spec

The rest of this page is the detailed spec the notebook was built from: components, positions, parameters and what changed from the legacy script.

**Source:** `components/python/chip_05_flux_TLQubits.py` (`create_test_chip()`, May 2024; writes
`chip_05_flux_TLQubits_1.0.gds`). Legacy QWri library, Quantcore internal. Notebook
`examples/designs/legacy/chip_05_flux_tlqubits.ipynb`.

### Changes after design decisions (legacy-fix, 2026-11-03)

- **#11 junction indexing fixed:** `bot[i]` (Q1–Q5 js 5, Q6 js 8); the junction-layer reference uses the same sizes.
- **#11 flux-line corners:** the largest radius that fits each line — FLUX4 r = 75 µm (its 155 µm pad lead cannot hold 100), FLUX5 the legacy 100 µm; no break or overlap (checked in a render).
- **R8:** the PCell's own open end (`ground=True`, as chip_10a does) instead of the `resonatorGnd` box: CUT8 and `W_R8` removed (the rule for #13/#26).
- **#16 device ID:** `CHIP05` kept, placed by the frame rule. `claw_tail_gap` = 10 µm (legacy `cap_spacing`).
- **#1 junctions:** legacy HSQ cells at the legacy fingers on the PDK junction rule (design rule #1: Nb trilayer, Δ = 1.4 meV, I_c·R_n = πΔ/2e = 2.20 mV, R_n 40–50 kΩ, qubits 4–8 GHz; PDK process `get_pdk().junction`: R_n·A 13.5 kΩ·µm², C_J 50 fF/µm², both assumed by the PDK): Q1–Q3 45 kΩ, Q6 28 kΩ, SQUIDs 22.5 kΩ parallel. LOM: f_q 5.8–6.1 GHz (SQUIDs 7.8 at zero flux); **Q1/R1 and Q2/R2 hybridised** (design rule).
- Notebook edited and its JSON rebuilt from the layout cell; **not executed** (verification policy): outputs cleared, PNGs stale until the notebook is run.

**What it is.** A 7.5 × 7.5 mm die centred on (0, 0) → Designer (x + 3750, y + 3750); PDK v2 die frame replaces the
base-metal corner `Marker`s and the layer-10 outline; the HSQ corner markers are kept. Feedline + two rounded pads
(as chip_03), eight `Coupled Resonator`s (`ground=False`: tails without an end cap, joining the claws), seven Xmons
(Q4, Q5 SQUIDs with flux lines from two small pads at the top/bottom edge centres), flux-trap holes, two HSQ test
pads, labels "500nm", "800nm", "QCG_Nb05_W".

**Buildable now?** Yes. Not reproduced: labels, the legacy flux-line end geometry (thin 1 µm section + ground
boxes). Junction windows (CLEARER) as `Xmon.junction_window`; junctions from `junction_creator_HSQ` /
`squid_creator_HSQ` (the scripts the source imports) as `TrilayerJunctionHSQ` / `TrilayerSquidHSQ`, XOR 0 on the
junction layers (legacy-c, 2026-11-03).

### Components (legacy frame, µm)

| instance | legacy → catalog ref | params | at | rot / mirror |
|---|---|---|---|---|
| FL | Coplanar Waveguide → `CpwSegment` | 5460 → 5360 (pads snapped, same etch), a/b 10/6 | (0, 0) | 0 |
| PL, PR | Connector Pad → `ConnectorPad` | 600 × 200, taper 500, 10/6, round, sim False | (∓2680, 0) | 270° / 90° |
| PFT, PFB | Connector Pad (`cpadB` / `cpadT`) → `ConnectorPad` | 400 × 150, taper 100, trace 4/6, round | (0, ±3155) | 180°; PFB mirrored |
| R1 … R8 | Coupled Resonator → `CoupledResonator` | common gap 10, clength 200, cgap 7, width 300, neck 400, **ground False**; cpw_len 4740 / 4920 / 5590 / 6200 / 5200 / 4250 / 5840 / 4500; flip R2, R3, R7, R8; clength 400 (R3, R7, R8), 250 (R5); width 400 (R4) | x = −2000, −1430, −850, −280, 280, 850, 1430, 2000; y = −38, 33, −33, 33, −38, 33, −38, 33 | mirror True at +33 |
| Q1 … Q7 | Xmon Cross → `Xmon` | as chip_03 (width 400; Q6 600) | (−1950, −2218), (−1480, 2391), (−800, −2237), (−180, 2492), (305, −2219), (900, 2203), (1480, −2503) | 0° / 180° alternating |
| junctions | `junction_creator_HSQ.create_junction(bot[i−1], top[i−1])` / `squid_creator_HSQ.create_squid` (Q4, Q5) → `junction_type="Trilayer Junction HSQ"` / `"Trilayer Squid HSQ"`, `junction_params={"finger_width": 0.1·bot, "second_finger_width": 0.6}` | as built (`bot[i−1]` indexing bug): Q1 0.8 µm, Q2–Q6 0.5 µm straight; 0.6 µm second finger; Q7 none | (x, y ± 210) (Q6 ± 310) | `Trans(0, flag)`, flag toggling per qubit: Q2, Q4, Q6 mirrored about x → `mirror_squid` on these 180° Xmons (junction-layer XOR 0) |
| CLEARER | 30 × 27 µm boxes cut from 1/0 and 3/0 at (x, y ± 207) (Q6 ± 307): from 6.5 µm inside the arm to 0.5 µm into the ground | `Xmon(junction_window=[30, 27, -3])` (metal on `base_metal_addition`, removed from M1 at export; dropped in the FEM export) | | |
| FLUX4, FLUX5 | raw path polygons (4 µm centre, 6 µm gaps, corners rounded at 100 µm) + 50 µm thin tip (1 µm) + ground boxes | Designer routes `PFT.a → Q4.flux`, `PFB.a → Q5.flux` (nodes (0, 3000), (−175, 3000) / (0, −2795), (300, −2795); a/b 4/6, r 50); Xmon `flux_port`, `flux_x −5`, `flux_tip_depth 7.5` → tip at (−175, 2719.5) / (300, −2446.5) as drawn | | |
| H0 … H7 | `flux_holes` 30 µm squares, 3 × 15 at 100 µm | `FluxHoleArray(30, 100, 100, 3, 15)` | (x − 50, y): x = −2050, −1430, −850, −280, 360, 850, 1430, 2000; y = 300 / −1800 alternating | 0 |
| CUT8 | `resonatorGnd` box (2035, 1660)–(2055, 1670): etches R8's centre conductor over its last 10 µm (the tail, uncapped, ends at y = 1669.9) | `CpweOpenEnd(length=10, a=10, b=5)` + `d.couple("W_R8", "R8.end", "CUT8.a", wire=True)` | (2045, 1660) | 90° |
| TP1, TP2 | `testPad_Nb_TL_HSQ.create_testPad(bf / 0.2, 0.6)` (inserted 6× by an indentation bug: identical copies) | `JunctionTestPads(**legacy_test_pad_params("testPad_Nb_TL_HSQ", bf / 0.2, 0.6))`, bf 0.5 / 0.8 | (−2850, 2000), (2850, −2000) | 0 |
| HSQ0 … HSQ3 | `Marker` on 500/0 (HSQ), width 150 | `CornerMarker(hsq=True, thickness=50, width=150)` | corners | 1/2/3/0 |

### Resonator tail ↔ claw

Tails without end caps run 0.9 / 2.9 / 17.9 / 22.9 / 0.9 / 29.9 / 6.9 µm into the claw tails of Q1 … Q7: the strip and
the claw are one conductor (checked on the rebuilt metal). LOM: `d.couple("W_Qi", "Qi.claw_n", "Ri.end", wire=True)`.

### LOM node structure

`FL.line` (50 Ω at each pad) ─ HANGER (`K_Ri`) ─ `Ri.res` (λ/4, shorted at the coupler) = `Qi.claw_n` ─ C_g ─ `Qi`
island (C, JJ or SQUID to ground; Q7 no junction). FLUX4/FLUX5 → `control:flux` of Q4/Q5. R8: the uncapped tail
would run into the ground (λ/2), but CUT8 opens it, so R8 is an open λ/4 (`W_R8` → the CUT8 termination): 7.085 GHz
bare, 7.048 GHz on the feedline (target 7.0). A simulation selection of R8 must include CUT8.

### Targets

Source comments: R1 6.5, R2 6.25, R3 5.5, R4 5, R5 6, R6 7.2, R7 5.25, R8 7 GHz.

### Keep-outs / frame

Pads sit at all four edge centres, so the frame's device ID (`CHIP05`) slides along the bottom edge to the first
free spot, (4600, 100)–(5300, 400), clear of PFB. HSQ markers in the corner marker areas (legacy positions kept).
