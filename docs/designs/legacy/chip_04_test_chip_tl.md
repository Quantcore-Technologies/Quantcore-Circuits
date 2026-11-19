# Junction test chip (chip_04)

A test chip with no qubits: 45 pairs of probe pads in a 9 × 5 array, each pair joined by a small trilayer Josephson
junction. The bottom finger width changes along the columns (0.4 to 1.0 µm) and the top finger down the rows (0.4 to
0.8 µm), so probing the 45 resistances shows how junction resistance follows finger width. It is Quantcore's own test
chip from the QWri legacy script `chip_04_test_chip_TL.py`.

The rebuild draws it from Quantcore PDK parts and values each junction on the PDK trilayer process; the fingers are
never resized. Build this one to learn the `JunctionTestPads` part and how a sweep is laid out as a grid.

```{figure} ../../images/designs/legacy/chip_04_test_chip_tl.png
:width: 100%
:alt: chip_04_test_chip_tl as rebuilt on the Quantcore PDK

chip_04_test_chip_tl as rebuilt on the Quantcore PDK
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/legacy/chip_04_test_chip_tl.ipynb` |
| Source script | `components/python/chip_04_test_chip_TL.py` (QWri legacy, Quantcore internal) |
| Chip | 7.5 × 7.5 mm die |
| On the chip | 45 `testPad_Nb_TL` probe structures (9 columns × 5 rows) with column and row labels in nm |
| Builds today | yes, rebuilt from its JSON on 2026-11-19 in 1.0 s (the notebook itself was not re-run) |

## Pictures

```{figure} ../../images/designs/legacy/chip_04_test_chip_tl_legacy.png
:width: 70%
:alt: chip_04_test_chip_tl: the original legacy layout (render of the legacy GDS)

chip_04_test_chip_tl: the original legacy layout (render of the legacy GDS)
```

```{figure} ../../images/designs/legacy/chip_04_test_chip_tl.png
:width: 70%
:alt: chip_04_test_chip_tl: the Quantcore rebuild

chip_04_test_chip_tl: the Quantcore rebuild
```

```{figure} ../../images/designs/legacy/chip_04_test_chip_tl_sweep.png
:width: 45%
:alt: Three test pads in a row: each has two probe pads and a junction between the tips

Three test pads in a row: each has two probe pads and a junction between the tips
```

```{figure} ../../images/designs/legacy/chip_04_test_chip_tl_tp_4_2.png
:width: 45%
:alt: One test pad: the two probe pads meet at a notch where the junction sits

One test pad: the two probe pads meet at a notch where the junction sits
```

```{figure} ../../images/designs/legacy/chip_04_test_chip_tl_jj.png
:width: 45%
:alt: The junction (20 µm box): bottom finger (magenta), top bent finger (grey) and their overlap (white)

The junction (20 µm box): bottom finger (magenta), top bent finger (grey) and their overlap (white)
```

## LOM estimates

The notebook's saved outputs hold no LOM run (its LOM cells were not executed), so there are no estimates to show here and none were computed for this page. It is a test chip, so the build spec gives junction values from the PDK process instead.

## Build spec

The rest of this page is the detailed spec the notebook was built from: components, positions, parameters and what changed from the legacy script.

**Source:** `components/python/chip_04_test_chip_TL.py` (`create_test_chip()`, writes `chip_04_TL_testJJ_1.0.gds`).
Legacy QWri library, Quantcore internal. Notebook `examples/designs/legacy/chip_04_test_chip_tl.ipynb`.

### Changes after design decisions (legacy-fix, 2026-11-03)

- **#1 junctions:** the drawn test-pad sweep valued on the PDK junction rule (design rule #1: Nb trilayer, Δ = 1.4 meV, I_c·R_n = πΔ/2e = 2.20 mV, R_n 40–50 kΩ, qubits 4–8 GHz; PDK process `get_pdk().junction`: R_n·A 13.5 kΩ·µm², C_J 50 fF/µm², both assumed by the PDK).
- Notebook edited and its JSON rebuilt from the layout cell; **not executed** (verification policy): outputs cleared, PNGs stale until the notebook is run.

**What it is.** A junction-size calibration chip: a 9 × 5 array of `testPad_Nb_TL` probe structures on a 7.5 × 7.5
mm die centred on (0, 0) → Designer (x + 3750, y + 3750). PDK v2 die frame (replaces the corner `Marker`s, rot
1/2/3/0, and the layer-10 outline with its 500 µm boxes at (±3350, ±3350)). No qubits, resonators or feedline.
Imports `junction_creator` (missing from the library) but never calls it.

**Buildable now?** Yes. MISSING: the text labels.

### Components (legacy frame)

| instance | legacy cell → catalog ref | params | at | notes |
|---|---|---|---|---|
| TP_i_j (45) | `testPad_Nb_TL.create_testPad(bf / 0.2, tf)` (`TEST_TL`) → `JunctionTestPads(**legacy_test_pad_params("testPad_Nb_TL", bf / 0.2, tf))` | pads 500 × 300, middle 300, window 600 × 900; straight finger `0.2·size + 0.06` = bf + 0.06 µm, bent finger tf; no HSQ | x = −2800 … 2800 (700 pitch, `np.arange(−box/2 + 950, box/2 − 800, 700)`), y = 2400 … −2400 (−1200 pitch) | `d.array("TP", ..., shape=(9, 5), vary=...)`; column i: bf = 0.4, 0.5, 0.55, 0.6, 0.7, 0.75, 0.8, 0.9, 1.0; row j: tf = 0.4, 0.5, 0.6, 0.7, 0.8 |
| labels | `TextGenerator`: "BOT" (200 µm) at (−200, 3400); inverted bf·1000 at (x − 190, 3050); inverted tf·1000 rot 90° at (−3300, y − 190) | MISSING (text cell) | | |

### Routes, test pads, LOM

No routes. The test pads have no ports, so the LOM netlist is empty. "LOM simulation" = the junction table
(area = (bf + 0.06) × tf; L_J, R_n from an assumed Jc, to confirm). No sim groups / FEM jobs.

### Keep-outs

None: the outermost windows end at |x| = 3100, |y| = 2850, inside the design area and clear of the corner marker
areas.
