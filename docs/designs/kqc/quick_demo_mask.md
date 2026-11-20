# Quick demo mask (KQC)

KQCircuits' fast demo mask: a 6-inch wafer with 36 Demo chips in a ring and 17 empty KQC chips for the eyes and the mouth, a smiley drawn on a 15 × 15 chip map. The notebook rebuilds it with the library's wafer assembly on the Quantcore PDK: the Demo chip as rebuilt on [its own page](demo.md), an empty 10 mm Quantcore die for the empty chips, and the PDK's die names, wafer outline, notch and dicing streets. The rebuild is GPL-3.0, like the source.

Read it as an example of wafer assembly from a source's chip map: two chips on 53 of 137 dies, each chip stored once in the wafer file however many dies carry it.

```{image} ../../images/designs/kqc/quick_demo_mask.png
:alt: The whole Quick demo mask wafer as the notebook builds it
:width: 100%
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/kqc/quick_demo_mask.ipynb`; it saves the empty chip as `examples/designs/kqc/quick_demo_mask/ch1.json` |
| Source | KQCircuits `scripts/masks/quick_demo.py` (`MaskSet` "Quick", version 1), © IQM Finland Oy, GPL-3.0 |
| Wafer | 152.4 mm (KQC's 6 in, radius 76.2 mm) with a notch at the bottom; 10 mm dies, 200 µm streets, 3 mm edge exclusion: 137 dies in rows A to M |
| On the wafer | 36 Demo chips (DE1) · 17 empty chips (CH1) · 84 empty dies · the mask name |
| Builds today | yes (layout built on 2026-11-19 in 6 s) |

## How the notebook builds it

```{image} ../../images/designs/kqc/quick_demo_mask_steps.png
:alt: The five layout segments of the Quick demo mask, one picture each
:width: 100%
```

1. **Wafer and die grid.** `Wafer(diameter_mm=152.4, die_mm=10, street_mm=0.2, align="centre")` gives 137 dies, with die G7 on the wafer centre where KQC's map has its middle cell.
2. **Chip map.** KQC's 15 × 15 map read onto the dies by position: 36 DE1, 17 CH1 and 84 empty dies.
3. **DE1.** The Demo chip, built once from `examples/designs/kqc/demo.json` (only read) and written once as a chip file.
4. **CH1.** KQC's base `Chip` cell with its own frame off, in a 10 mm Quantcore die with the frame, the alignment grids and the device ID "CH1". This is the design the notebook saves.
5. **Whole wafer.** Both chips on their dies, the mask name "QUICK V1" on 501/0, and zooms on one die and on a street crossing.

## The chip map and the dies

```{image} ../../images/designs/kqc/quick_demo_mask_map.png
:alt: Die map of the wafer with the Demo dies in blue and the empty KQC chips in orange
:width: 70%
```

The die map with DE1 in blue and CH1 in orange. In the layout a CH1 die is almost blank (a frame and a device ID), so the smiley's eyes and mouth show on this map rather than in the whole-wafer picture.

```{image} ../../images/designs/kqc/quick_demo_mask_die.png
:alt: One Demo die on the wafer with the dicing streets around it
:width: 60%
```

Die G1, a Demo chip on the left of the ring, with the 200 µm streets round it. Above and below are the Demo dies F1 and H1, to the right the empty die G2.

```{image} ../../images/designs/kqc/quick_demo_mask_street.png
:alt: The street crossing at the top-right corner of die G1
:width: 60%
```

The street crossing at G1's top-right corner: the Demo dies F1 (above) and G1 (below) on the left, the empty dies F2 and G2 on the right. The hatched frames are the 30 µm die outlines on 501/0, the orange L's are the PDK dicing markers in the Demo chip's corners, the small squares its alignment grids and the blue dots its cheese.

## Check and fab files

A full run of the notebook (2026-11-19) gives:

- The chip counts and the 15 × 15 map equal the source's, cell by cell. None of the 53 mapped dies falls off the wafer.
- Both chips are 10 × 10 mm (their 100/0 boundary) and draw nothing outside it, so neighbouring chips are one 200 µm street apart. The wafer layout holds one DE1 cell placed 36 times and one CH1 cell placed 17 times.
- The CH1 design has no DRC errors and one `frame_margin` warning: the KQC `Chip` cell's bounding box is the whole die, so it reaches into the 100 µm die margin, where it draws nothing.
- `build/wafer/quick_demo_mask.oas` is 86 kB, with its die table `quick_demo_mask.csv` (137 rows: die, row, column, size, centre, chip). The Demo chip file alone is 63 kB: the chip carries the PDK cheese over its whole die (124 282 holes) but is stored once. The fab-layer wafer `build/wafer/quick_demo_mask_fab.oas`, built from each chip's PDK fab mask without corner rounding, is 38 kB.

## LOM estimates

The mask has no LOM of its own because it adds no circuit. Each DE1 die is the Demo chip, whose LOM estimates are on [its page](demo.md#lom-estimates), and CH1 has no junctions or resonators.

## Build spec

The rest of this page is the spec the notebook was built from: the chip map, the two chips and what the rebuild changes.

Source `other-libs/KQCircuits-main/KQCircuits-main/klayout_package/python/scripts/masks/quick_demo.py` · GPL-3.0
(IQM Finland). What it is: a KQC `MaskSet(name="Quick", version=1, with_grid=False)` with one mask layout on face
`1t1`. It is a 15 × 15 chip map on the default 6-inch wafer (wafer_rad 76200 µm, chip_size 10000 µm, dice_width 200
µm; the default chips_map_offset of (−1200, 1200) µm centres the map on the wafer). Chips form a smiley: a ring of
36 × `DE1` (= `Demo`, spec [demo](demo.md)) and 17 × `CH1` (= empty KQC `Chip`) for eyes and mouth; the rest are
"---" (empty). Mask export layers: base_metal_gap → "1", underbump_metallization → "2", indium_bump → "3". Two
alternative netlists are defined for DE1 (`breakdown_list: ["Meander"]` and none). The notebook writes the map and
these numbers into its own cells and assembles the wafer with the library's `Wafer` class; no KQC mask code is used
or copied.

### Components
| instance | catalog ref | key params (units) | at (x, y) | rot | notes |
|---|---|---|---|---|---|
| DE1 × 36 | `examples/designs/kqc/demo.json`, the [Demo](demo.md) rebuild of KQC `Demo` | as saved there (only read); KQC's `alt_netlists` only affect KQC's netlist export | the DE1 map cells, die centres on a 10.2 mm grid | 0 | one chip cell placed 36 times |
| CH1 × 17 | `examples/designs/kqc/quick_demo_mask/ch1.json`: KQC `Chip` | `frames_enabled=[]` in a 10 × 10 mm Quantcore die, device ID "CH1" | the CH1 map cells | 0 | frame and markers only |

Map (rows top to bottom, 15 columns; D = DE1, C = CH1, . = empty):
```
...............   ...............   ...DDDDDDDDD...   ..D.........D..   ..D.CC...CC.D..
.D..CC...CC..D.   .D...........D.   .D...........D.   .D.C.......C.D.   .D..C.....C..D.
..D..CCCCC..D..   ..D.........D..   ...DD.....DD...   .....DDDDD.....   ...............
```
(read row-major: rows 1–5 on the first line, rows 6–10 on the second, rows 11–15 on the third).

On the rebuilt wafer, map row 2 is die row A and map column c is die column c − 1, so the top-left Demo chip (map row
3, column 4) is die B3 and the map's middle cell is die G7.

### Routes
None at wafer level.

### Launchers, pads, test structures, markers, labels
In the source: KQC's mask markers and labels (MaskSet defaults), the 200 µm dicing width and the mask name "Quick"
v1. In the rebuild: the wafer outline on 500/0 (a 200 µm ring with a 1 mm V-notch at the bottom); die names, 30 µm
die outlines and alignment crosses (top, left and right, in the edge band) on 501/0; the mask name "QUICK V1" on
501/0 above the top row of dies; and in each chip the PDK die frame (L dicing markers on 1000/0, alignment grids on
1001/0, the boundary on 100/0, the device ID).

### LOM node structure (qubit ↔ resonator ↔ feedline ↔ bus ↔ control lines)
Per DE1 chip, as in [demo](demo.md). No inter-chip connections. CH1 has no circuit.

### Targets (if stated)
None.

### What the rebuild changes
- **Pitch.** KQC's chips are 10 mm on a 10 mm pitch, with the dicing edge inside each chip's frame. The rebuild keeps
  10 mm dies and puts a 200 µm street between them, so the pitch is 10.2 mm and the far corners of the ring's corner
  dies sit 72.34 mm from the centre. They fit on the source's 152.4 mm wafer with the PDK's 3 mm edge exclusion
  (73.2 mm usable radius). On the PDK's 150 mm "6 in" preset (72 mm usable) the eight dies B3, B11, C2, C12, K2, K12,
  L3 and L11 would not fit, which is why the notebook keeps the source's diameter.
- **Wafer.** The PDK's V-notch at the bottom; KQC's default wafer is a plain circle.
- **DE1.** The source's mask set builds its chips with `with_grid=False` (no ground grid). The rebuild places the Demo
  design as it is saved, with the PDK cheese over its whole die.
- **CH1.** The Quantcore die frame replaces KQC's ChipFrame, as on every KQC rebuild.
- **Empty positions.** The 84 grid positions without a chip are drawn as empty dies (outline and name on 501/0); KQC
  draws nothing there. The wafer class can switch the outlines and names off only for all dies at once.
- **Labels and markers.** Die names follow the PDK wafer rule (rows A to M from the top, columns from 1 on the left)
  instead of KQC's position labels. KQC's mask markers are not drawn; the wafer class draws its alignment crosses.
- **Mask name.** The wafer class has no mask label, so the notebook writes "QUICK V1" on 501/0 with KLayout's text
  generator.
- **Mask layers.** KQC exports base_metal_gap, underbump_metallization and indium_bump as the mask layers "1" to "3".
  The rebuild writes one wafer with the chips' build layers (`quick_demo_mask.oas`) and one with each chip's PDK fab
  layers (`quick_demo_mask_fab.oas`: 1/0 base etch with the cheese, 3/0 keep-out, the junction, spacer and airbridge
  layers, the frame).
