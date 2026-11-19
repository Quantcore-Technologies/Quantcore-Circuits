# TSV flip-chip test chip (QPDK)

A QPDK interconnect test chip (MIT): two mirrored CPW lines that pass through all four metal faces of a two-chip stack, using through-silicon vias (TSVs) and indium-bump transitions between the bottom and top chip. It has no resonators and no qubits.

There is no notebook for this chip yet (spec only). The spec below is what a Quantcore rebuild would follow.

## At a glance

| | |
|---|---|
| Notebook | none yet (spec only) |
| Builds today | not applicable |

## Build spec

The rest of this page is the spec the design would be built from.

> **Update 2026-11-03:** frame = **source**: build with `chip={"die_frame": False, ...}` so the replica keeps its own size and frame (the Quantcore PDK die frame is for Quantcore chips only).

Source: [qpdk/samples/tsv_flip_chip_test_chip.pic.yml](https://github.com/gdsfactory/quantum-rf-pdk/blob/main/qpdk/samples/tsv_flip_chip_test_chip.pic.yml)
· cells `qpdk/cells/tsv.py`, `bump.py`, `chip.py` · licence MIT (verified) · read 2026-11-02.
Image: `docs/_static/images/tsv_flip_chip_test_chip.png`.
What it is: two mirrored through lines, a (north) and b (south). Each one leaves a launcher on M1 and drops through a
TSV pair to a backside (MB) underpass, then comes back up to M1. It crosses an indium-bump transition to the top chip (M2),
goes through a top-chip TSV to a meander on the top chip's backside (MB2), then returns the same way to a second
launcher. Three 29 × 7 indium-bump arrays tie the two ground planes together. There are no resonators or qubits; this
chip tests the interconnect.
Frame: bottom chip edge 10000 × 10000 at (−5000, −5000), top chip 6000 × 6000 at (−3000, −3000) (both 100 µm etched
frames). **Box (0, 0, 10000, 10000)**, **Designer = source + (5000, 5000)**, top chip over (2000…8000)².
Faces: M1 = bottom-chip front (KQC `1t1`), MB = bottom-chip back (`1b1`), M2 = top-chip front facing down (`2b1`),
MB2 = top-chip back (`2t1`). CPW 10/6 µm on every face (`cpw`, `cpw_backside`, `cpw_top`, `cpw_top_backside`).
Status: **no (missing: multi-face routing in Designer)**. KQC has `TsvStandard`, `FlipChipConnectorRf` and bump
grids (`Chip.with_gnd_bumps`), but our routes are single-face.

### Components (line a at Designer y 6000; line b mirrored at y 4000)
| instance | catalog ref | key params (units) | at (x, y) Designer | rot | notes |
|---|---|---|---|---|---|
| PIN_A / PIN_B | `BondPad` | default | (100, 6000) / (100, 4000) | 270 (faces east) | launcher_in (−4900, ±1000) |
| POUT_A / POUT_B | `BondPad` | default | (9900, 6000) / (9900, 4000) | 90 (faces west) | launcher_out (4900, ±1000) rot 180 |
| TDN_IN_x | `TsvStandard` (≈ QPDK `tsv_transition_double_sided`) | taper 100, pad 40 × 30, pad_gap 24, via 10 × 20, 2 signal vias @ 20, 4 ground vias/side @ 30, 15 from line | (900, y) | 0 | M1 → MB |
| TUP_IN_x | `TsvStandard` | same | (1700, y) | 180 | MB → M1 |
| B_IN_x | `FlipChipConnectorRf` (≈ QPDK `bump_transition`) | pad 30 × 30, pad_gap 6, taper 10, bump ⌀ 15, no ground bumps | (2250, y) | 0 | M1 → M2 |
| TT_IN_x | `TsvStandard` (chip top) | same as TSV | (2800, y) | 0 | M2 → MB2 |
| TT_OUT_x | `TsvStandard` (chip top) | same | (7200, y) | 180 | MB2 → M2 |
| B_OUT_x | `FlipChipConnectorRf` | same | (7750, y) | 180 | M2 → M1 |
| TDN_OUT_x | `TsvStandard` | same | (8300, y) | 0 | M1 → MB |
| TUP_OUT_x | `TsvStandard` | same | (9100, y) | 180 | MB → M1 |
| BUMPS_C / _N / _S | `Chip(with_gnd_bumps=True)` or explicit array | 29 cols × 7 rows, pitch 200, ⌀ 15 | centres (5000, 5000), (5000, 7100), (5000, 2900) | — | each 5600 × 1200 µm |

### Routes (line a; b mirrors y about 5000)
| route | face | from → to | waypoints (Designer) |
|---|---|---|---|
| FEED_IN | M1 | PIN.a → TDN_IN.o1 | straight |
| UNDER_IN | MB | TDN_IN.o2 → TUP_IN.o2 | (1200, 6000), (1200, 6400), (1400, 6400), (1400, 6000) (b: 3600) |
| BOT_IN | M1 | TUP_IN.o1 → B_IN.o1 | straight |
| TOP_IN | M2 | B_IN.o2 → TT_IN.o1 | straight |
| TOP_BACK | MB2 | TT_IN.o2 → TT_OUT.o2 | serpentine x 3200 → 6800 in 400 µm steps between y 6000 and 6600 (10 legs; b: 4000/3400) |
| TOP_OUT | M2 | TT_OUT.o1 → B_OUT.o2 | straight |
| BOT_OUT | M1 | B_OUT.o1 → TDN_OUT.o1 | straight |
| UNDER_OUT | MB | TDN_OUT.o2 → TUP_OUT.o2 | (8600, 6000), (8600, 6400), (8800, 6400), (8800, 6000) |
| FEED_OUT | M1 | TUP_OUT.o1 → POUT.a | straight |

### Launchers, pads, test structures, markers, labels
4 launchers, two chip-edge frames (M1 and M2 etch), 609 ground bumps (3 × 203).

### LOM node structure
Two independent 2-port through lines. Each is a chain of CPW segments with lumped transitions: TSV pairs (series L plus
pad C), bump transitions (series L plus pad C). Four 50 Ω ports, no resonant elements. In an S-parameter model the
MB2 serpentine sets the delay.

### Targets
None. The test checks continuity and return loss of every face transition.

### Simplifications for a first rebuild
1. Only after multi-face routes exist. Until then, a single-face rebuild is just two straight CPW lines (trivial).
2. Requested capability: per-route `face` (1t1 / 1b1 / 2b1 / 2t1), plus a TSV and a bump transition with ports on
   both faces.
