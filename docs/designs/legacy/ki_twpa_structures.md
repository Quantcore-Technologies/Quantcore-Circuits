# KI spirals and a TWPA line

A structure sheet for kinetic-inductance (KI) devices, not a measured chip. A travelling-wave parametric amplifier (TWPA) style line runs from one bond pad to the other: a finger-loaded section, a meandered section and a second finger-loaded section, all 10/6 µm CPW. The fingers (2 µm wide, reaching into both grounds) add shunt capacitance per unit length, as a KI TWPA's artificial line does. Above it sit six spiral inductors (double-Fermat and Fermat spirals), the compact high-inductance elements KI circuits use.

No KI or TWPA chip script exists in Quantcore's library. The cells here are ported building blocks from the legacy files `spiral.lym`, `draw.py` and `cpwe.py` (internal; the finger line is from G. Long, Glasgow 2021), laid out as a sheet on the PDK die with the device ID `KI TWPA`. Build it to see the spiral and finger-line components side by side and learn how a snapped chain of CPW cells forms one continuous line.

```{image} ../../images/designs/legacy/ki_twpa_structures.png
:alt: The whole ki_twpa_structures sheet rebuilt on the Quantcore PDK
:width: 100%
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/legacy/ki_twpa_structures.ipynb` (design JSON `ki_twpa_structures.json`) |
| Source | Legacy building blocks `spiral.lym`, `draw.py`, `cpwe.py` in Quantcore's library (internal); no KI / TWPA chip script exists |
| Chip | 7.5 × 7.5 mm Quantcore die, sapphire, CPW 10 / 6 µm |
| On the chip | 2 `CpweBondPad` · 2 `CpweFingerLine` (150 fingers each) · 1 `CpweMeanderLine` · 6 `SpiralLine` |
| Builds today | yes, rebuilt from its JSON on 2026-11-19 in 2.2 s (the notebook itself was not re-run) |

## Pictures

```{figure} ../../images/designs/legacy/ki_twpa_structures.png
:alt: Rebuilt ki_twpa_structures
:width: 100%

The sheet: the TWPA-style line at the bottom, six spiral inductors in their square pockets above.
```
```{figure} ../../images/designs/legacy/ki_twpa_structures_spiralzoom.png
:alt: Zoom on the centre of a spiral
:width: 45%

The centre of spiral S3, a double-Fermat inductor: the metal line (white, 3 µm wide) winds out of the middle (an 80 µm view).
```
```{figure} ../../images/designs/legacy/ki_twpa_structures_fingerzoom.png
:alt: Zoom on the finger-loaded line
:width: 45%

The finger-loaded line: 2 µm fingers reach into the grounds on both sides of the centre line (an 80 µm view).
```
```{figure} ../../images/designs/legacy/ki_twpa_structures_pl.png
:alt: Zoom on the left bond pad
:width: 45%

The left bond pad, an exponential taper into the 10 / 6 µm line.
```

## LOM estimates

The notebook has no saved LOM output. The chip has no qubit and no resonator whose frequency the LOM estimates (it is a structure sheet).

## Build spec

The rest of this page is the detailed spec the notebook was built from: every component, the changes made while rebuilding, and the notes.

**Request:** design rule #7 ("import the kinetic-inductance and TWPA design chips to render, especially the
spirals"). **Notebook:** `examples/designs/legacy/ki_twpa_structures.ipynb` (+ `.json`), legacy-fix, 2026-11-03.
Quantcore internal.

### What the library holds

No KI or TWPA **chip** script exists in `components/` (or the sibling project folders): no `chip_*` script, notebook
or GDS uses spirals, KI lines or a TWPA. The building blocks:

| legacy source | draws | Quantcore cell |
|---|---|---|
| `components/pymacros/spiral.lym` (library "MyLib", PCell `Spiral`) | Archimedean spiral path `inner_r` → `outer_r`, pitch `width + spacing` per turn, `n` points per turn | `SpiralPath` |
| `components/python/draw.py::spiral(x, y, w, start_ang, end_ang, spiral_r, spiral_type, npoints, layer)` | spiral by angle: 0 Archimedean, 1 Fermat, 2 double Fermat in/out (the double-Fermat branch has a typo, `y_bls` / `y1s`) | `SpiralLine` (archimedean / fermat / double_fermat; golden XOR in `tests/test_spirals.py`) |
| `components/python/cpwe.py::finger_line` (G. Long, Glasgow 2021) | CPW with interdigital fingers into both grounds: the shunt-C-loaded artificial line of a KI TWPA | `CpweFingerLine` |
| `cpwe.py::meander_line`, `b_pad`, `tapper`, `term_open` | meandered CPW, bond pad, taper, open end | `CpweMeanderLine`, `CpweBondPad`, `CpweTaper`, `CpweOpenEnd` |
| `ustrip.py`, `pymacros/Cong/bondpad_ustrip.lym` | microstrip versions | not ported (decision: ignore microstrip) |

### The chip (Designer frame, 7.5 × 7.5 mm PDK die, ID `KI TWPA`)

| instance | cell | params | at |
|---|---|---|---|
| PL | `CpweBondPad` | pad 500 / gap 300, end 10, pad 50, taper 500 (exponential, weight 25), CPW 10/6 | (250, 2600) |
| F1, F2 | `CpweFingerLine` | 150 fingers, 2 µm wide, 10 µm long, 2 µm apart, CPW 10/6 | snapped: PL.a → F1, M1.b → F2 |
| M1 | `CpweMeanderLine` | r 50, straight 600, bias 0.5, 18 periods, CPW 10/6 | snapped to F1.b |
| PR | `CpweBondPad(mirror=True)` | as PL | snapped to F2.b |
| S1–S4 | `SpiralLine` (double Fermat, `pocket_margin=20`; S5 Fermat, S6 double Fermat 8 turns, added) | legacy sizes kept where they map (`spiral_r`, `width` in µm, angles in rad); exact parameters and the 1100 µm pitch from x = 1000 µm: see the notebook layout cell | (1000 + 1100 k, see notebook) |
| PS1–PS4 | `metal:Rectangle(subtract=True)` | square pocket 2 r_out + 40 µm | same centres |

### LOM

The line: one conductor PL → PR (50 Ω ports), finger sections with their shunt C (`CpweFingerLine` model). Spirals:
shapes without ports; the notebook tabulates N turns, wire length, geometric L (modified Wheeler, circular) and
kinetic L_k = L_□ ℓ / w for example sheet inductances (0.1 / 10 / 50 pH/□ — the KI film is not in the PDK: assumed
values). No sim groups.

### Open

- The actual KI / TWPA chip sources (if they exist elsewhere): add them to `components/` to rebuild them as chips.
- ~~`draw.spiral` Fermat / double-Fermat spirals~~: done, `SpiralLine` (the notebook uses it since the cell switch).
- The KI film (material, thickness, sheet kinetic inductance) for the PDK.
