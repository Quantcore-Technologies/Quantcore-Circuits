# Quick demo mask (KQC)

This page describes the KQC "Quick" mask: a wafer layout of Demo chips arranged as a smiley. There is no notebook for it yet, so the page is the spec only. It needs wafer and mask-set assembly that the library does not have.

Read it to see how KQC lays out a wafer. The chip it repeats is [the Demo chip](demo.md).

## Build spec

The rest of this page is the detailed spec: the chip map, the mask layers and the netlists.

> **Update 2026-11-03:** frame = **source**: build with `chip={"die_frame": False, ...}` so the replica keeps its own size and frame (the Quantcore PDK die frame is for Quantcore chips only).

Source `other-libs/KQCircuits-main/KQCircuits-main/klayout_package/python/scripts/masks/quick_demo.py` · GPL-3.0
(IQM Finland). · What it is: a KQC `MaskSet(name="Quick", version=1, with_grid=False)` with one mask layout on face
`1t1`. It is a 15 × 15 chip map on the default 6-inch wafer (wafer_rad 76200 µm, chip_size 10000 µm, dice_width 200
µm). Chips form a smiley: a ring of 36 × `DE1` (= `Demo`, spec [demo](demo.md)) and 17 × `CH1` (= empty KQC `Chip`)
for eyes and mouth; the rest are "---" (empty). Mask export layers: base_metal_gap → "1", underbump_metallization →
"2", indium_bump → "3". Two alternative netlists are defined for DE1 (`breakdown_list: ["Meander"]` and none). ·
**Buildable now: no** (missing: wafer/MaskSet assembly; see `layouts/wafers/fab_export.py`, "next step for
wafers/").

### Components
| instance | catalog ref | key params (units) | at (x, y) | rot | notes |
|---|---|---|---|---|---|
| DE1 × 36 | `Demo` (KQC chip class) or our `kqc_demo` design | defaults (`alt_netlists` only affects the netlist export) | map cells, see below | 0 | each chip is the [demo](demo.md) spec |
| CH1 × 17 | `Chip` (KQC base) | defaults | map cells | 0 | frame and markers only |

Map (rows top to bottom, 15 columns; D = DE1, C = CH1, . = empty):
```
...............   ...............   ...DDDDDDDDD...   ..D.........D..   ..D.CC...CC.D..
.D..CC...CC..D.   .D...........D.   .D...........D.   .D.C.......C.D.   .D..C.....C..D.
..D..CCCCC..D..   ..D.........D..   ...DD.....DD...   .....DDDDD.....   ...............
```
(read row-major: rows 1–5 on the first line, rows 6–10 on the second, rows 11–15 on the third).

### Routes
None at wafer level.

### Launchers, pads, test structures, markers, labels
KQC mask markers and labels (MaskSet defaults), dicing grid 200 µm, mask name "Quick" v1.

### LOM node structure (qubit ↔ resonator ↔ feedline ↔ bus ↔ control lines)
Per DE1 chip, as in [demo](demo.md). No inter-chip connections.

### Targets (if stated)
None.

### Simplifications for a first rebuild
Build `demo` first. A wafer step can tile the written `build/kqc_demo.oas` with KQC `MaskSet.add_chip` / `mask_export`
on the static chip files, which is what `fab_export.py` plans. Until then the mask is reference only.
