# Resonator-only chip (resonator_chip_01)

The resonator-only twin of `chip_01`: one feedline and five quarter-wave resonators (5000 µm each), alternating above
and below, but no qubits. Without a qubit, the resonators can be measured alone to see their frequency, coupling and
quality factor. It is a Quantcore internal chip from the QWri legacy script `resonator_chip_01.py`, with the labels
"RES" and "1" to "5".

The rebuild draws it from Quantcore PDK parts. The legacy script cut each resonator short with a small box; the
rebuild drops those cuts, so all five resonators have the same full length and share one frequency. Build this one to
learn the feedline plus hanger-resonator pattern on its own.

```{figure} ../../images/designs/legacy/resonator_chip_01.png
:width: 100%
:alt: resonator_chip_01 as rebuilt on the Quantcore PDK

resonator_chip_01 as rebuilt on the Quantcore PDK
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/legacy/resonator_chip_01.ipynb` |
| Source script | `components/python/resonator_chip_01.py` (QWri legacy, Quantcore internal) |
| Chip | 7.5 × 7.5 mm die, 10/6 µm CPW |
| On the chip | 5 λ/4 `Coupled Resonator`s (300 µm couplers) · feedline with 2 bond pads · 6 text labels |
| Builds today | yes, rebuilt from its JSON on 2026-11-19 in 3.8 s (the notebook itself was not re-run) |

## Pictures

```{figure} ../../images/designs/legacy/resonator_chip_01_legacy.png
:width: 70%
:alt: resonator_chip_01: the original legacy layout (render of the legacy GDS)

resonator_chip_01: the original legacy layout (render of the legacy GDS)
```

```{figure} ../../images/designs/legacy/resonator_chip_01.png
:width: 70%
:alt: resonator_chip_01: the Quantcore rebuild

resonator_chip_01: the Quantcore rebuild
```

```{figure} ../../images/designs/legacy/resonator_chip_01_coupler.png
:width: 45%
:alt: The first resonator where it runs along the feedline (the coupler) and its open end

The first resonator where it runs along the feedline (the coupler) and its open end
```

```{figure} ../../images/designs/legacy/resonator_chip_01_label.png
:width: 45%
:alt: A numbered label with its cheese keep-out

A numbered label with its cheese keep-out
```

## LOM estimates

The notebook's saved outputs hold no LOM run (its LOM cells were not executed), so there are no estimates to show here and none were computed for this page. The build spec quotes about 6.37 GHz (loaded) for the five resonators from an earlier run.

## Build spec

The rest of this page is the detailed spec the notebook was built from: components, positions, parameters and what changed from the legacy script.

**Source:** `components/python/resonator_chip_01.py` (`create_chip`, output `res_01.gds`), Quantcore internal.
Legacy PCells: `Coplanar Waveguide`, `Connector Pad` (`connector_pad.lym`), `Coupled Resonator`, `Marker`. (It
imports `junction_creator`, which is not in the library, but never calls it.) **Rebuild:**
`examples/designs/legacy/resonator_chip_01.ipynb` (+ `.json`, PNGs); tables and the legacy reference in
`examples/designs/legacy/_legacy_b.py` (`RC1_*`, `resonator_chip01_reference`).

### Changes after design decisions (legacy-fix, 2026-11-03)

- **#13 grounder boxes — removed** (not intended; the later PCell has dedicated open and short ends): each resonator ends with its own gap cap (`ground=True`), full 5000 µm, no floating stubs. All five now share one frequency (≈ 6.37 GHz loaded): degenerate on one feedline — give lengths if they should be spread.
- **#9 pads — repositioned:** 345 µm inwards of the legacy tips (∓2975 → ∓2630, feedline 5950 → 5260 µm): the rounded pad end on the design-area edge, 100 µm inside the 7.5 mm die, clear of the dicing lane and corner markers.
- Notebook edited and its JSON rebuilt from the layout cell; **not executed** (verification policy): outputs cleared, PNGs stale until the notebook is run.

**What it is:** the resonator-only twin of chip_01 (`docs/designs/legacy/chip_01.md`, legacy-a): the same 5950 µm
feedline with `lc/rc_thickness` 2, the same two rounded `Connector Pad`s and the same five `Coupled Resonator`s
(cpw_len 5000, clength 300, cgap 2 µm, width 300, necks 600 / 550 / 500 / 400 / 300 µm), alternating above and below
at x = −2000 … 2000, with no Xmons. Instead, a 22 × 10 µm etched box (the "grounder", the full CPW width) sits on or
beyond each resonator tail, at about the y where chip_01's claw tails are (1850, 1930, 2000, 1740, 1895 µm vs
claw tips 1848, 1898, 1998, 1738, 1848). Labels "RES" and "1" … "5". No frequency targets in the source.

**Die:** 7.5 × 7.5 mm, centred on (0, 0) → (+3750, +3750). PDK v2 die frame instead of the legacy `Marker` corners
and 10/0 boundary boxes.

**Status:** built; XOR 0.0 µm² against the legacy PCells on every resonator, grounder and label, and on the pads
and feedline at the moved pad position (see below).

### Components

| instance | legacy cell | catalog ref | key params | at (x, y) µm | rot | legacy (x, y), notes |
|---|---|---|---|---|---|---|
| `FL` | `Coplanar Waveguide` | `CpwSegment` | length **5460** (legacy 5950), 10/6, lc/rc_thickness 2 | (3750, 3750) | 0 | (0, 0) |
| `PL` | `Connector Pad` | `ConnectorPad` | pad 275 × 300, taper (conn_height) 300, trace 10/6, rounded | (1020, 3750), snapped to `FL.a` | 270 | legacy (−2975, 0) rot 3 → **(−2730, 0)** |
| `PR` | `Connector Pad` | `ConnectorPad` | as PL | (6480, 3750), snapped to `FL.b` | 90 | (2975, 0) rot 1 → **(2730, 0)** |
| `R1` | `Coupled Resonator` (`res1`) | `CoupledResonator` | neck 600 | (1750, 3776) | 0, mirror | (−2000, 26); tail end y = 2162.9 |
| `R2` | `Coupled Resonator` (`res2`) | `CoupledResonator` | neck 550 | (2750, 3724) | 0 | (−1000, −26); end −1778.9 |
| `R3` | `Coupled Resonator` (`res_fixed`) | `CoupledResonator` | neck 500 | (3750, 3776) | 0, mirror | (0, 26); end 1803.9 |
| `R4` | `Coupled Resonator` (`res3`) | `CoupledResonator` | neck 400 | (4750, 3724) | 0 | (1000, −26); end −1853.9 |
| `R5` | `Coupled Resonator` (`res4`) | `CoupledResonator` | neck 300 | (5750, 3776) | 0, mirror | (2000, 26); end 1903.9 |
| `G1`…`G5` | etched `Box` 22 × 10 on 1/0 | `metal:Rectangle` (22 × 10 µm, `subtract=True`) | – | legacy (−2000, 1850), (−1000, −1930), (0, 2000), (1000, −1740), (2000, 1895) + (3750, 3750) | 0 | see "grounders" |
| `LBL_RES` | `TextGenerator` "RES", mag 200 | `TextLabel` | – | (3550, 7050) | 0 | (−200, 3300) |
| `LBL_1`…`LBL_5` | `TextGenerator`, mag 300, inv | `TextLabel` | inverted | legacy (−2020, −600), (−1020, 600), (−20, −600), (980, 600), (1980, −600) | 0 | resonator numbers |
| – | `Marker` ×4, 10/0 boxes | PDK die frame | – | – | – | replaced |

Resonator common (`resParams_common`): cpw_len 5000, clength 300, cgap 2, width 300, flip False, neck 500
(overridden), legacy defaults otherwise (gap 6, arc_length 300, ground True → shorted at the coupler, open tail).

**Pads (deviation, forced):** at the legacy tips (∓2975, 0) the rounded pads reach 245 µm past the die edge, which
the DRC reports as an *error* (`outside_chip`). As legacy-a did for chip_01 (same pads), both pads move 245 µm
inwards and the feedline shrinks to 5460 µm. The legacy script also leaves the pads' `sim` at its default True
(pad metal + ground ring on 1/0, a simulation drawing); the rebuild uses the fab geometry (legacy bug not
reproduced).

**Grounders:** an etched box across the full CPW width cuts the trace. On R1, R4 and R5 it lies on the tail, so the
resonator's open end moves to the box and the rest of the tail is a floating stub; on R2 and R3 it lies beyond the
tail end (just a hole in the ground plane):

| resonator | tail end y | grounder y (±5) | cut | effective λ/4 length (µm) | floating stub (µm) |
|---|---|---|---|---|---|
| R1 | 2162.9 | 1850 | yes | 4682.1 | 307.9 |
| R2 | −1778.9 | −1930 | no (146 µm past the end) | 5000 | – |
| R3 | 1803.9 | 2000 | no (191 µm past) | 5000 | – |
| R4 | −1853.9 | −1740 | yes | 4881.1 | 108.9 |
| R5 | 1903.9 | 1895 | yes | 4986.1 | 3.9 |

### Routes

None (pads snap to the feedline; resonators couple by proximity).

### LOM node structure

- `FL.line`: feedline + both pads, 50 Ω at each pad.
- Each `Ri`: λ/4 `TLres` (drawn length 5000 µm) to ground + HANGER κ to the feedline (`d.couple("K_Ri", "Ri",
  "FL")`, 300 µm at 2 µm). The LOM does not see the grounder cut: the notebook corrects R1, R4, R5 by the effective
  length (table above).

### Targets

None in the source.

### Simplifications for a first rebuild

- Pads moved inwards 245 µm (DRC error otherwise); pad `sim` geometry not reproduced.
- PDK die frame instead of the legacy markers.
