# KQC test chips

These are KQCircuits' own test structures: chips that test a process or a part, not a quantum device. Two of them (`simple`, `shaping`) carry a qubit. The rest test airbridges, junctions, lithography, flip-chip crossings, through-silicon vias and the sample holder. All are 10 × 10 mm and rebuilt on the Quantcore PDK (GPL-3.0, © IQM Finland Oy).

Build them to see how a whole KQC chip cell is placed in a `Designer`, and what each process test looks like. Each block below has the whole chip, a one-line purpose, and how the notebook builds it. Most have no qubit or resonator, so their LOM section has nothing to estimate.

## The notebooks

| Notebook | What it tests |
|---|---|
| `simple` | a minimal connected chip: one Swissmon coupled to a through line; the smoke test for KQC parity |
| `shaping` | a readout design: one Swissmon with two Purcell-filtered quarter-wave readout chains |
| `airbridge_crossings` | airbridge crossings of lines, and a mechanical array of 608 short bridge spans (19 lengths, 8 widths, 4 distances) |
| `airbridge_dc_test` | four-point DC resistance of airbridge chains (1 to 22 bridges per test) |
| `crossing_twoface` | flip-chip line crossings (bridges on the top chip) and a crosstalk pair |
| `quality_factor_twoface` | resonator quality factor with a flip-chip lid: six capped spiral quarter-wave resonators on one probe line |
| `sample_holder_test` | a 40-pad sample holder: every pad pair is joined by a line |
| `empty` | electron-beam lithography with the ground removed in a cross-shaped area |
| `junction_test` | electron-beam lithography and junction process: a cross opening filled with an array of 80 × 80 µm squares |
| `junction_test2` | SQUID junction arrays on test pads, with stepped junction widths |
| `lithography_test` | optical lithography resolution: stripe blocks with 1 to 15 µm lines, spaced 1 and 5 times the width, and crosses |
| `lithography_test_twoface` | the same lithography test on both faces of a flip chip |
| `stripes` | ground-grid and lithography stripes: 80 µm metal stripes at 200 µm pitch and 80 µm squares in a cross opening |
| `tsv_test` | the through-silicon-via process: a TSV fence pattern and three metrology arrays for cross-sections |

### simple

**Tests:** a minimal connected chip: one Swissmon coupled to a through line; the smoke test for KQC parity.

```{image} ../../images/designs/kqc/simple.png
:alt: The whole simple chip as the v2 notebook builds it
:width: 100%
```

| | |
|---|---|
| Notebook | `examples/designs/kqc/simple.ipynb` (the one-cell version before the rewrite: `simple.v1.ipynb`) |
| Source | KQCircuits `chips/simple.py`, © IQM Finland Oy, GPL-3.0 |
| On the chip | 3 SMA8 launchers (WN, EN, SE) · 1 Swissmon · 2 finger capacitors · 1 T · 1 flux line |
| Builds today | yes: layout run 2026-11-19, 7 s, the saved design is byte-identical to the one before the rewrite |

How it builds: Die, bond pads, signal line, qubit, qubit onto the line, flux line, whole chip.

```{image} ../../images/designs/kqc/simple_steps.png
:alt: The layout segments of Simple, one picture each
:width: 100%
```

Numbers are from a run of this notebook on 2026-11-19 (Setup, Design, Check and the LOM cells, 7 s): QuCat normal modes with QuTiP dressed values.

| mode | kind | f (GHz) | κ (MHz) | A (MHz) | participation |
|---|---|---|---|---|---|
| QB | qubit | 6.193 | 0.425 | 198 | J_QB 1.00 |

| parameter | LOM (QuTiP) | target |
|---|---|---|
| `QB.f_q_GHz` | 5.99 | – |
| `QB.alpha_MHz` | -214 | – |

```{image} ../../images/designs/kqc/simple_lom.png
:width: 80%
:alt: LOM plot of simple
```

These are lumped-model estimates (component formulas and calibration), not FEM results; see [the LOM page](../../library/lom.md) for how far to trust them.

### shaping

**Tests:** a readout design: one Swissmon with two Purcell-filtered quarter-wave readout chains.

```{image} ../../images/designs/kqc/shaping.png
:alt: The whole shaping chip as the v2 notebook builds it
:width: 100%
```

| | |
|---|---|
| Notebook | `examples/designs/kqc/test_chips/shaping.ipynb` (the one-cell version before the rewrite: `shaping.v1.ipynb`) |
| Source | KQCircuits `chips/shaping.py`, © IQM Finland Oy, GPL-3.0 |
| On the chip | 8 SMA8 launchers · 1 Swissmon · 2 readout chains (resonator, filter, capacitors) · charge and flux line |
| Builds today | yes: layout run 2026-11-19, 7 s, the saved design is byte-identical to the one before the rewrite |

How it builds: Die, bond pads, qubit, the two chains, control lines, whole chip.

```{image} ../../images/designs/kqc/shaping_steps.png
:alt: The layout segments of Shaping, one picture each
:width: 100%
```

Numbers are from a run of this notebook on 2026-11-19 (Setup, Design, Check and the LOM cells, 17 s): QuCat normal modes with QuTiP dressed values.

| parameter | LOM (QuTiP) | target |
|---|---|---|
| `QB.f_q_GHz` | 6.45 | – |
| `QB.alpha_MHz` | -242 | – |
| `PB2.chi_MHz` | -0.00569 | – |
| `PA2.chi_MHz` | -0.00847 | – |
| `PB2.f_GHz` | 7.48 | – |
| `PB2.kappa_MHz` | 27.5 | – |
| `PA2.f_GHz` | 7.72 | – |
| `PA2.kappa_MHz` | 27.9 | – |

| qubit | f_q (GHz) | A (MHz) | resonator | f_r (GHz) | κ_r (MHz) | χ (MHz) |
|---|---|---|---|---|---|---|
| QB | 6.68 | 222 | RA3 | 8.345 | 0.326 | -6.46 |

| resonator | LOM line (µm) | KQC target sum (µm) | T arms not in the LOM (µm) |
|---|---|---|---|
| RA3 | 2750 | 3060 | 306 |
| PA2 | 3790 | 3950 | 153 |
| RB3 | 2870 | 3170 | 306 |
| PB2 | 3910 | 4070 | 153 |

```{image} ../../images/designs/kqc/shaping_lom.png
:width: 80%
:alt: LOM plot of shaping
```

These are lumped-model estimates (component formulas and calibration), not FEM results; see [the LOM page](../../library/lom.md) for how far to trust them.

### airbridge_crossings

**Tests:** airbridge crossings of lines, and a mechanical array of 608 short bridge spans (19 lengths, 8 widths, 4 distances).

```{image} ../../images/designs/kqc/airbridge_crossings.png
:alt: The whole airbridge_crossings chip as the v2 notebook builds it
:width: 100%
```

| | |
|---|---|
| Notebook | `examples/designs/kqc/test_chips/airbridge_crossings.ipynb` (the one-cell version before the rewrite: `airbridge_crossings.v1.ipynb`) |
| Source | KQCircuits `chips/airbridge_crossings.py`, © IQM Finland Oy, GPL-3.0 |
| On the chip | 4 lines (PL-1 to PL-4) between SMA8 launchers · line crossings on airbridges · the mechanical array |
| Builds today | yes: layout run 2026-11-19, 73 s, the saved design is byte-identical to the one before the rewrite |

How it builds: Die, bond pads, the mechanical array, the four lines.

```{image} ../../images/designs/kqc/airbridge_crossings_steps.png
:alt: The layout segments of AirbridgeCrossings, one picture each
:width: 100%
```

This chip has no junction or resonator (four 50 Ω through lines), so there is no lumped-model estimate. What it measures, the transmission across the crossings and the PL-1 to PL-3 crosstalk, needs a driven FEM solve.

### airbridge_dc_test

**Tests:** four-point DC resistance of airbridge chains (1 to 22 bridges per test).

```{image} ../../images/designs/kqc/airbridge_dc_test.png
:alt: The whole airbridge_dc_test chip as the v2 notebook builds it
:width: 100%
```

| | |
|---|---|
| Notebook | `examples/designs/kqc/test_chips/airbridge_dc_test.ipynb` (the one-cell version before the rewrite: `airbridge_dc_test.v1.ipynb`) |
| Source | KQCircuits `chips/airbridge_dc_test.py`, © IQM Finland Oy, GPL-3.0 |
| On the chip | 22 `AirbridgeDC` tests in three bands, no launchers |
| Builds today | yes: layout run 2026-11-19, 4 s, the saved design is byte-identical to the one before the rewrite |

How it builds: Die, the chip cell, a view of the longest chain.

```{image} ../../images/designs/kqc/airbridge_dc_test_steps.png
:alt: The layout segments of AirbridgeDcTest, one picture each
:width: 100%
```

This chip has no junction, qubit or resonator, so there is no lumped-model estimate; the notebook's LOM section says nothing to simulate. The chip is measured in the process (optical or EBL inspection, DC probing), not with microwaves.

### crossing_twoface

**Tests:** flip-chip line crossings (bridges on the top chip) and a crosstalk pair.

```{image} ../../images/designs/kqc/crossing_twoface.png
:alt: The whole crossing_twoface chip as the v2 notebook builds it
:width: 100%
```

| | |
|---|---|
| Notebook | `examples/designs/kqc/test_chips/crossing_twoface.ipynb` (the one-cell version before the rewrite: `crossing_twoface.v1.ipynb`) |
| Source | KQCircuits `chips/crossing_twoface.py`, © IQM Finland Oy, GPL-3.0 |
| On the chip | 4 routes between SMA8 launchers · 6 flip-chip crossings of PL-1 by PL-3 |
| Builds today | yes: layout run 2026-11-19, 5 s, the saved design is byte-identical to the one before the rewrite |

How it builds: Die, bond pads, the two straight lines, the crossing lines.

```{image} ../../images/designs/kqc/crossing_twoface_steps.png
:alt: The layout segments of CrossingTwoface, one picture each
:width: 100%
```

This chip has no junction or resonator (four 50 Ω through lines), so there is no lumped-model estimate. What it measures, the transmission through the flip-chip crossings and the PL-1 to PL-3 and PL-2 to PL-4 crosstalk, needs a driven FEM solve.

### quality_factor_twoface

**Tests:** resonator quality factor with a flip-chip lid: six capped spiral quarter-wave resonators on one probe line.

```{image} ../../images/designs/kqc/quality_factor_twoface.png
:alt: The whole quality_factor_twoface chip as the v2 notebook builds it
:width: 100%
```

| | |
|---|---|
| Notebook | `examples/designs/kqc/test_chips/quality_factor_twoface.ipynb` (the one-cell version before the rewrite: `quality_factor_twoface.v1.ipynb`) |
| Source | KQCircuits `chips/quality_factor_twoface.py`, © IQM Finland Oy, GPL-3.0 |
| On the chip | 2 SMA8 launchers · 1 probe line · 6 spiral λ/4 resonators (5374 to 5589 µm) · 6 coupling capacitors |
| Builds today | yes: layout run 2026-11-19, 7 s, the saved design is byte-identical to the one before the rewrite |

How it builds: Die, bond pads, couplers, resonators, probe line.

```{image} ../../images/designs/kqc/quality_factor_twoface_steps.png
:alt: The layout segments of QualityFactorTwoface, one picture each
:width: 100%
```

Numbers are from a run of this notebook on 2026-11-19 (Setup, Design, Check and the LOM cells, 16 s): QuCat normal modes with QuTiP dressed values.

| mode | kind | f (GHz) | κ (MHz) | A (MHz) | participation |
|---|---|---|---|---|---|
| R5 | resonator | 5.578 | 0.0652 | 0 | R5 1.00 |
| R0 | resonator | 5.652 | 1.42 | 0 | R0 1.00 |
| R4 | resonator | 5.682 | 0.0456 | 0 | R4 1.00 |
| R1 | resonator | 5.688 | 0.739 | 0 | R1 1.00 |
| R3 | resonator | 5.773 | 0.124 | 0 | R3 1.00 |
| R2 | resonator | 5.795 | 0.226 | 0 | R2 1.00 |

| mode | Q_ext (LOM) |
|---|---|
| R0 | 3980 |
| R1 | 7700 |
| R2 | 25600 |
| R3 | 46500 |
| R4 | 125000 |
| R5 | 85600 |

```{image} ../../images/designs/kqc/quality_factor_twoface_lom.png
:width: 80%
:alt: LOM plot of quality_factor_twoface
```

These are lumped-model estimates (component formulas and calibration), not FEM results; see [the LOM page](../../library/lom.md) for how far to trust them.

### sample_holder_test

**Tests:** a 40-pad sample holder: every pad pair is joined by a line.

```{image} ../../images/designs/kqc/sample_holder_test.png
:alt: The whole sample_holder_test chip as the v2 notebook builds it
:width: 100%
```

| | |
|---|---|
| Notebook | `examples/designs/kqc/test_chips/sample_holder_test.ipynb` (the one-cell version before the rewrite: `sample_holder_test.v1.ipynb`) |
| Source | KQCircuits `chips/sample_holder_test.py`, © IQM Finland Oy, GPL-3.0 |
| On the chip | 40 RF launchers (10 per side) · 20 CPWs |
| Builds today | yes: layout run 2026-11-19, 6 s, the saved design is byte-identical to the one before the rewrite |

How it builds: Die, the 40 launchers, the 20 lines.

```{image} ../../images/designs/kqc/sample_holder_test_steps.png
:alt: The layout segments of SampleHolderTest, one picture each
:width: 100%
```

This chip has no junction or resonator (20 × 50 Ω through lines; the lengths are printed in Design 4), so there is no lumped-model estimate.

### empty

**Tests:** electron-beam lithography with the ground removed in a cross-shaped area.

```{image} ../../images/designs/kqc/empty.png
:alt: The whole empty chip as the v2 notebook builds it
:width: 100%
```

| | |
|---|---|
| Notebook | `examples/designs/kqc/test_chips/empty.ipynb` (the one-cell version before the rewrite: `empty.v1.ipynb`) |
| Source | KQCircuits `chips/empty.py`, © IQM Finland Oy, GPL-3.0 |
| On the chip | one chip-level cross-shaped opening, no components |
| Builds today | yes: layout run 2026-11-19, 4 s, the saved design is byte-identical to the one before the rewrite |

How it builds: Die, the chip cell, a view of the cross corner.

```{image} ../../images/designs/kqc/empty_steps.png
:alt: The layout segments of Empty, one picture each
:width: 100%
```

This chip has no junction, qubit or resonator, so there is no lumped-model estimate; the notebook's LOM section says nothing to simulate. The chip is measured in the process (optical or EBL inspection, DC probing), not with microwaves.

### junction_test

**Tests:** electron-beam lithography and junction process: a cross opening filled with an array of 80 × 80 µm squares.

```{image} ../../images/designs/kqc/junction_test.png
:alt: The whole junction_test chip as the v2 notebook builds it
:width: 100%
```

| | |
|---|---|
| Notebook | `examples/designs/kqc/test_chips/junction_test.ipynb` (the one-cell version before the rewrite: `junction_test.v1.ipynb`) |
| Source | KQCircuits `chips/junction_test.py`, © IQM Finland Oy, GPL-3.0 |
| On the chip | one chip-level cross opening with a square array, no components |
| Builds today | yes: layout run 2026-11-19, 3 s, the saved design is byte-identical to the one before the rewrite |

How it builds: Die, the chip cell, a view of the cross corner.

```{image} ../../images/designs/kqc/junction_test_steps.png
:alt: The layout segments of JunctionTest, one picture each
:width: 100%
```

This chip has no junction, qubit or resonator, so there is no lumped-model estimate; the notebook's LOM section says nothing to simulate. The chip is measured in the process (optical or EBL inspection, DC probing), not with microwaves.

### junction_test2

**Tests:** SQUID junction arrays on test pads, with stepped junction widths.

```{image} ../../images/designs/kqc/junction_test2.png
:alt: The whole junction_test2 chip as the v2 notebook builds it
:width: 100%
```

| | |
|---|---|
| Notebook | `examples/designs/kqc/test_chips/junction_test2.ipynb` (the one-cell version before the rewrite: `junction_test2.v1.ipynb`) |
| Source | KQCircuits `chips/junction_test2.py`, © IQM Finland Oy, GPL-3.0 |
| On the chip | 6 pad arrays, each with a Quantcore SQUID between its pad pairs |
| Builds today | yes: layout run 2026-11-19, 4 s, the saved design is byte-identical to the one before the rewrite |

How it builds: Die, the chip cell, the pad arrays, one test SQUID.

```{image} ../../images/designs/kqc/junction_test2_steps.png
:alt: The layout segments of JunctionTest2, one picture each
:width: 100%
```

This chip has no modes to simulate, so there are no qubit or resonator estimates. Numbers are from a run of this notebook on 2026-11-19 (4 s): what the chip measures is each test SQUID's R_n at room temperature, so the notebook lists the R_n and L_J the PDK junction rule gives each stepped finger (two junctions in parallel per SQUID; Nb Δ = 1.4 meV, R_n·A = 13.5 kΩ·µm² assumed).

| array | loop | SQUIDs | straight finger (µm) | R_n per SQUID (kΩ) | L_J per SQUID (nH) | in 40-50 kΩ |
|---|---|---|---|---|---|---|
| 1 | large (130 µm²) | 8 | 0.10 to 0.31 | 112.5 to 36.3 | 16.84 to 5.43 | 2 |
| 2 | large (130 µm²) | 13 | 0.34 to 0.70 | 33.1 to 16.1 | 4.95 to 2.41 | 0 |
| 3 | small (80 µm²) | 13 | 0.15 to 0.27 | 75.0 to 41.7 | 11.22 to 6.24 | 5 |
| 4 | small (80 µm²) | 13 | 0.28 to 0.40 | 40.2 to 28.1 | 6.01 to 4.21 | 1 |
| 5 | small (80 µm²) | 13 | 0.41 to 0.53 | 27.4 to 21.2 | 4.11 to 3.18 | 0 |
| 6 | large (130 µm²) | 8 | 0.73 to 0.94 | 15.4 to 12.0 | 2.31 to 1.79 | 0 |

8 SQUIDs fall inside the PDK's 40 to 50 kΩ window.

These are lumped-model estimates (component formulas and calibration), not FEM results; see [the LOM page](../../library/lom.md) for how far to trust them.

### lithography_test

**Tests:** optical lithography resolution: stripe blocks with 1 to 15 µm lines, spaced 1 and 5 times the width, and crosses.

```{image} ../../images/designs/kqc/lithography_test.png
:alt: The whole lithography_test chip as the v2 notebook builds it
:width: 100%
```

| | |
|---|---|
| Notebook | `examples/designs/kqc/test_chips/lithography_test.ipynb` (the one-cell version before the rewrite: `lithography_test.v1.ipynb`) |
| Source | KQCircuits `chips/lithography_test.py`, © IQM Finland Oy, GPL-3.0 |
| On the chip | horizontal, vertical and diagonal line blocks, no components |
| Builds today | yes: layout run 2026-11-19, 3 s, the saved design is byte-identical to the one before the rewrite |

How it builds: Die, the chip cell, horizontal, vertical and diagonal blocks.

```{image} ../../images/designs/kqc/lithography_test_steps.png
:alt: The layout segments of LithographyTest, one picture each
:width: 100%
```

This chip has no junction, qubit or resonator, so there is no lumped-model estimate; the notebook's LOM section says nothing to simulate. The chip is measured in the process (optical or EBL inspection, DC probing), not with microwaves.

### lithography_test_twoface

**Tests:** the same lithography test on both faces of a flip chip.

```{image} ../../images/designs/kqc/lithography_test_twoface.png
:alt: The whole lithography_test_twoface chip as the v2 notebook builds it
:width: 100%
```

| | |
|---|---|
| Notebook | `examples/designs/kqc/test_chips/lithography_test_twoface.ipynb` (the one-cell version before the rewrite: `lithography_test_twoface.v1.ipynb`) |
| Source | KQCircuits `chips/lithography_test_twoface.py`, © IQM Finland Oy, GPL-3.0 |
| On the chip | the line blocks of LithographyTest on the bottom chip, six mirrored blocks on the top chip |
| Builds today | yes: layout run 2026-11-19, 3 s, the saved design is byte-identical to the one before the rewrite |

How it builds: Die, the chip cell, horizontal, vertical and diagonal blocks, top chip.

```{image} ../../images/designs/kqc/lithography_test_twoface_steps.png
:alt: The layout segments of LithographyTestTwoface, one picture each
:width: 100%
```

This chip has no junction, qubit or resonator, so there is no lumped-model estimate; the notebook's LOM section says nothing to simulate. The chip is measured in the process (optical or EBL inspection, DC probing), not with microwaves.

### stripes

**Tests:** ground-grid and lithography stripes: 80 µm metal stripes at 200 µm pitch and 80 µm squares in a cross opening.

```{image} ../../images/designs/kqc/stripes.png
:alt: The whole stripes chip as the v2 notebook builds it
:width: 100%
```

| | |
|---|---|
| Notebook | `examples/designs/kqc/test_chips/stripes.ipynb` (the one-cell version before the rewrite: `stripes.v1.ipynb`) |
| Source | KQCircuits `chips/stripes.py`, © IQM Finland Oy, GPL-3.0 |
| On the chip | one chip-level cross opening with stripes, no components |
| Builds today | yes: layout run 2026-11-19, 3 s, the saved design is byte-identical to the one before the rewrite |

How it builds: Die, the chip cell, a view of the cross corner.

```{image} ../../images/designs/kqc/stripes_steps.png
:alt: The layout segments of Stripes, one picture each
:width: 100%
```

This chip has no junction, qubit or resonator, so there is no lumped-model estimate; the notebook's LOM section says nothing to simulate. The chip is measured in the process (optical or EBL inspection, DC probing), not with microwaves.

### tsv_test

**Tests:** the through-silicon-via process: a TSV fence pattern and three metrology arrays for cross-sections.

```{image} ../../images/designs/kqc/tsv_test.png
:alt: The whole tsv_test chip as the v2 notebook builds it
:width: 100%
```

| | |
|---|---|
| Notebook | `examples/designs/kqc/test_chips/tsv_test.ipynb` (the one-cell version before the rewrite: `tsv_test.v1.ipynb`) |
| Source | KQCircuits `chips/tsv_test.py`, © IQM Finland Oy, GPL-3.0 |
| On the chip | 1 `TsvTestPattern` · 3 arrays of single vias (10 × 10, 8 × 8, 6 × 6) |
| Builds today | yes: layout run 2026-11-19, 5 s, the saved design is byte-identical to the one before the rewrite |

How it builds: Die, the chip cell, the centre pattern, a metrology array.

```{image} ../../images/designs/kqc/tsv_test_steps.png
:alt: The layout segments of TsvTest, one picture each
:width: 100%
```

This chip has no junction, qubit or resonator, so there is no lumped-model estimate; the notebook's LOM section says nothing to simulate. The chip is measured in the process (optical or EBL inspection, DC probing), not with microwaves.

## Build spec

The rest of this page is the detailed spec the notebooks were built from: the sources, coordinates, routes and the status of each chip.

> **Update 2026-11-03:** frame = **source**: build with `chip={"die_frame": False, ...}` so the replica keeps its own size and frame (the Quantcore PDK die frame is for Quantcore chips only).

Sources `other-libs/KQCircuits-main/KQCircuits-main/klayout_package/python/kqcircuits/chips/<module>.py` · GPL-3.0
(IQM Finland). Rebuilt from extracted parameters. · All of them are 10 × 10 mm with box (0,0)–(10000,10000), and the
KQC frame = Designer frame. Coordinates come from a scratch build of each KQC chip on 2026-11-02. · Priority P3
(reference / process). "Buildable now" is per chip below. `launchers={"type": T, "assign": {pad: name}}` reproduces
KQC `launcher_assignments`. Plain `"SMA8"` gives pads NW, NE, EN, ES, SE, SW, WS, WN at (2800,9200), (7200,9200),
(9200,7200), (9200,2800), (7200,800), (2800,800), (800,2800), (800,7200).

### Components
| chip (module) | purpose | main elements (catalog ref, params, placement) | buildable now? |
|---|---|---|---|
| JunctionTest (`junction_test`) | EBL / junction process test | One chip-level polygon in `base_metal_gap_wo_grid`: a cross-shaped opening (arms 2000–8000, reaching 100 + dice_width from the edges) minus an array of 80 × 80 µm squares at 100 µm pitch (`edge_len=80, inter_space=20`). No elements. | **no** (missing: chip-level polygon/region primitive) |
| JunctionTest2 (`junction_test2`) | SQUID test-pad arrays | 6 × `JunctionTestPadsSimple`, `margin=20, pad_width=500, pad_spacing=200, area_width=1600`: #1 (300,2000) h 6000, loop_area 130, `junction_width_steps=[0.08,0.03]`; #2 (2000,300) h 9400, 130, [0.32,0.03]; #3 (3400,300) h 9400, 80, [0.15,0.01]; #4 (4800,300) 80, [0.28,0.01]; #5 (6200,300) 80, [0.41,0.01]; #6 (8000,2000) h 6000, 130, [0.71,0.03]. KQC also passes `only_arms=True`, which is not in the Simple schema and is ignored. | yes |
| AirbridgeCrossings (`airbridge_crossings`) | airbridge crossing + mechanical test | SMA8 assign {1:PL-1-IN, 2:PL-2-IN, 3:PL-4-IN, 4:PL-4-OUT, 5:PL-2-OUT, 6:PL-1-OUT, 7:PL-3-OUT, 8:PL-3-IN}. Mechanical array: 19 lengths × 8 widths × 4 distances = 608 straight CPWs, `WaveguideCoplanarStraight(l = 2·5·(dist+width)+4)`, centred at (3600,9650) + (0,−121)·i + (400,0)·j + (0,−2350)·k. On rows with (i+k) odd and 1000 < y < 9000 there are 5 `AirbridgeRectangular` (defaults) at x offsets 50·(n−2): 1280 bridges. | **built** element by element (`test_chips/airbridge_crossings.ipynb`): XOR 0 on all mask layers; LOM netlist test blocked on the airbridge ground-strap model (open request) |
| AirbridgeDcTest (`airbridge_dc_test`) | 4-point DC airbridge resistance | 22 × `AirbridgeDC(width=2000, n_ab=1…22)` at test_0…21: (3000,8850), (5000,8850), (7000,8850); rows y = 6875 / 5625 / 4375 / 3125 at x = 2000, 4000, 6000, 8000; then (3000,1150), (5000,1150), (7000,1150). `n_ab` = index+1. | yes |
| CrossingTwoface (`crossing_twoface`) | flip-chip crossing / crosstalk | `frames_enabled=[0,1]`, SMA8 with the same assign as AirbridgeCrossings. 4 routes only (see Routes). | **built** element by element (`test_chips/crossing_twoface.ipynb`): face-change waypoints, XOR 0 on both faces, DRC clean |
| LithographyTest (`lithography_test`) | optical-litho resolution | For each width w = 1…15 µm and spacing factor s ∈ {1, 5}: `StripesTest(num_stripes=20, stripe_width=w, stripe_length=100, stripe_spacing=s·w)` and `CrossTest(num_crosses=n, cross_spacing=100)`, grouped as horizontal / vertical (rot 90; crosses rot 90 + mirror) / diagonal (rot −45, no crosses) blocks. Placement: horizontal s=1 at (2000,6500), (3000,6500); s=5 at (4000,6500), (6000,6500); vertical s=1 at (1500,5700), (5500,5700); s=5 at (1500,3800), (5500,3800); diagonal s=1 at (400,1500), (1500,1500); s=5 at (3100,1500), (6100,1500). Inside a block, item i sits at (0, 200i+40) / (200i+140, 0) / (500+100i, 500+100i). | yes (script loops, ≈ 300 instances; KQC uses plain container cells) |
| LithographyTestTwoface (`lithography_test_twoface`) | same, both faces | The above on 1t1, plus 6 blocks on face 2b1 (`face_ids=["2b1"]`) mirrored with `DCplxTrans.M90` (= `mirror=True, rot=180`): h s=1 (5900,4000), h s=5 (8000,4000), v s=1 (5000,6200), v s=5 (5000,4000), d s=1 (7500,1800), d s=5 (6200,1800). `frames_enabled=[0,1]`. | yes (compose transforms per item) |
| TsvTest (`tsv_test`) | through-silicon-via process | `TsvTestPattern(tsv_array_form=[2,2,2,6,14,2,14,14,2,2,14,14,2,14,6,2,2,2], tsv_diameter=10, tsv_elliptical_width=10)` at (5000,5000). Metrology arrays of `TsvStandard(tsv_diameter=10)`: 10 × 10 from (950,950) pitch 60; 8 × 8 from (970,8470) pitch 70; 6 × 6 from (8525,1025) pitch 75. Use `d.array`. | yes |
| Stripes (`stripes`) | ground-grid / litho stripes | Chip-level polygon (cross opening 2000–8000) minus 80 µm-wide stripes at 200 µm pitch and 80 µm squares (`axis="Vertical"`). | **no** (missing: polygon primitive) |
| Shaping (`shaping`) | readout with Purcell filter (1 qubit) | `Swissmon` at (4000,5000) rot 270: `arm_width=[30,23,30,23], arm_length=[190,96,160,96], gap_width=[29.5,33,29.5,33], island_r=2, cpl_length=[235,0,205], cpl_width=[60,42,60], cpl_gap=[110,112,110], cl_offset=[150,150]`. Two mirrored chains, from cplr0 (4000,5296) up and from cplr2 (4000,4734) down. Each chain has 3 × `WaveguideCoplanarSplitter(lengths=[61,61,31])`, a J gap cap (`FingerCapacitorSquare` gap 37.5 / 36.8), a κ interdigital cap (4 × 67.9 / 71.5), a drive gap cap (36.2), a readout resonator (segments 611.586 / 1834.76 / 611.586 µm qubit → short) and a Purcell resonator (3158.32 / 789.581 µm output → short). `tunable=True` adds `Manhattan` SQUIDs at the shorted stubs. | **built** element by element (`test_chips/shaping.ipynb`): meanders as cpw routes on KQC's Meander centre line, XOR 0 on mask layers; LOM: one summed λ/4 per chain (see note) |
| DcTest (`dc_test`) | DC sample-holder pads | `launchers="DC24"`: 24 × `LauncherDC(width=500)`, gap 300, indent 680, pitch 850. These have no chip ports (DC pads have no corner refpoint). | yes |
| Empty (`empty`) | EBL test, ground removed | Chip-level polygon in `base_metal_gap_wo_grid` + `ground_grid_avoidance`: a cross from d1 = 300 (dice 200 + margin 100) to d2 = 2000 from the edges. | **no** (missing: polygon primitive) |
| Launchers (`launchers`) | bare sample-holder pads | `launchers=sampleholder_type` (default SMA8; ARD24/DC24 possible). | yes |
| Simple (`simple`) | minimal connected chip | SMA8 `enabled=["WN","EN","SE"]`. `Swissmon(cpl_length=[0,150,0])` at (2500,7200) rot 270 (flux W at (2254.67,7200), cplr1 E at (2719,7200)). C1 `FingerCapacitorSquare(finger_width=20, finger_length=100, finger_number=7)` at (5000,7200); C2 same at (7200,5000) rot 270; T `WaveguideCoplanarSplitter(lengths=[11,11,11], port_names=[right,left,bottom])` at (7200,7200). | yes (verified: 6 route lengths = KQC, LOM fully connected) |
| SampleHolderTest (`sample_holder_test`) | 40-pad holder test | 40 RF pads (width 160, gap 96, indent 520, pitch 635), 10 per side, paired by 20 CPWs. Designer `launchers=` only knows SMA8/ARD24/DC24, so place 40 × `Launcher(s=160, l=160, a_launcher=160, b_launcher=96, launcher_frame_gap=96)`: N (2142.5+635i, 9480) rot 90; E (9480, 7857.5−635i) rot 0; S (7857.5−635i, 520) rot 270; W (520, 2142.5+635i) rot 180. | **built** element by element (`test_chips/sample_holder_test.ipynb`): 40 `Launcher` instances, XOR 0 |
| QualityFactorTwoface (`quality_factor_twoface`) | flip-chip (capped) spiral λ/4 Q test | `frames_enabled=[0,1]`, SMA8 assign {8: PL-1-IN, 3: PL-1-OUT}. QualityFactor's lists (`res_lengths` 5434/5429/5374/5412/5493/5589, `n_fingers`, `l_fingers`, `type_coupler`) with `res_a=[10,10,10,20,10,5]`, `res_b=[6,6,6,12,6,3]`, `resonator_types=['capped']*6`, `resonator_faces=[0,1]` (all lines on 1t1, the top chip 2b1 is a lid with its frame only). 6 × `WaveguideCoplanarSplitter` (lengths 15/15/65, a = b = 10) at x = 2800 + (i+0.5)·816.67, y = 5000, side arm down (even) / up (odd); per T a `FingerCapacitorSquare` (KQC `cap_params`, a/b 10/10 → res a/b) aligned port a to the side arm, then a `SpiralResonatorPolygon` (box 2000 × 500, `cap_res_distance` 200, `bridge_spacing` 0, mirrored for odd i) at its port b. | **built** element by element (`test_chips/quality_factor_twoface.ipynb`): spirals as routes on KQC's spiral centre line (DPath params do not fit `design.json`), XOR < 1 nm slivers only |

### Routes
- **AirbridgeCrossings**: PL-1 chip.PL-1-IN → chip.PL-1-OUT, straight x = 2800. PL-2 is straight at x = 7200. PL-3
  runs chip.PL-3-IN (800,7200) → chip.PL-3-OUT (800,2800) and weaves across x = 2800 20 times, with step = 4400 / 9.5 /
  2 = 231.58 and wiggle 250. Per pair: (2550,y), wp((2800,y), airbridge=True), (3050,y); y −= step; (3050,y),
  wp((2800,y), airbridge=True), (2550,y); y −= step. PL-4 runs EN → ES weaving between x = 7500 and 8000 (no
  crossing).
- **CrossingTwoface** (a_capped = b_capped = 10 on the top-chip span): PL-1 NW → SW: (2800,8900), (4300,8900),
  wp((4300,8500), a=10, b=10), wp((4300,1600), a=10, b=6), (4300,1100), (2800,1100). PL-2 likewise at x = 5700 from NE
  → SE. PL-3 runs WN → WS: wp((1500,7200), a=10, b=10), then 3 × [(3850,y), wp((4100,y), face_id="2b1"),
  wp((4500,y), face_id="1t1"), (4750,y); y −= 880; mirrored back], then wp((1600,2800), a=10, b=6), (900,2800). This
  crosses PL-1 on the top chip. PL-4 runs EN → ES: (9100,7200), wp((8500,7200), a=10, b=10), 3 × wiggle 6000 ↔ 6900
  (step 880), wp((8400,2800), a=10, b=6), (9100,2800).
- **Simple**: WN → Swissmon.flux; Swissmon.cplr1 → C1.a; C1.b → T.left; T.right → EN; T.bottom → C2.a; C2.b → SE.
  All are straight cpw.
- **Shaping**: chargeline WN → drive via (900,7200), (900,5150), (3750,5150), `term2=6`. Fluxline WS → flux via
  (900,2800), (900,5000), (3687.67,5000). Per chain: qubit → T_a (meander 1681.76 to T_b) → T_b stub shorted (580.6)
  → J cap → T_c (stub shorted 758.6) → Purcell meander 2479.24 → κ cap → output to EN (top) / ES (bottom). The drive
  cap goes from T_a.bottom to NW / SW.
- **SampleHolderTest**: PL-i (i = 1…10) N pad (x_i = 2142.5+635(i−1)) → (x_i, 8180) → (8180, y_i = x_i) → E pad.
  PL-(11+k) (k = 0…9) S pad (x = 7857.5−635k) → (x, 1820) → (1820, 7857.5−635k) → W pad. The middle segments are
  diagonal and nested.
- **QualityFactorTwoface**: probe line PL-1-IN (800,7200) → taper to a/b = 10/10 at (1500,7200) → (2000,7200) →
  (2000,5000) → T0 … T5 → (8000,5000) → (8000,7200) → taper back to 10/6 at (8400,7200) → PL-1-OUT. KQC's face
  nodes at (2300,5000) and (7700,5000) go to face 0, i.e. no face change with the defaults. Each spiral: capacitor
  port b → KQC's polygon spiral (one and a half turns in the 2000 × 500 box) → shorted end (term 0).
- AirbridgeDcTest, JunctionTest2, TsvTest, LithographyTest*, DcTest, Launchers: no routes.

### Launchers, pads, test structures, markers, labels
Covered per chip above. Every chip gets the KQC chip frame and markers from the DesignChip base. DcTest/Launchers are
the pads themselves.

### LOM node structure (qubit ↔ resonator ↔ feedline ↔ bus ↔ control lines)
Only Shaping and Simple have a qubit. In Simple, the Swissmon flux port takes the WN line (a control), and cplr1
feeds C1 → T → EN with C2 to SE. Shaping's resonators are **tapped** (T's inside the λ/4). As built, every
piece of a chain is a cpw route (the meanders too, on KQC's Meander centre line), so the LOM builder makes each chain
one λ/4 `TLres` of the summed route length (the T arms, 306 / 153 µm, are not counted) with the drive and J capacitors
on its coupler-end node: right mode structure (qubit, 2 readouts, 2 Purcell filters), rough couplings. A `Meander`
instance or a `meander` route between two T's would instead become a λ/2 bus (wrong). QualityFactorTwoface: six λ/4
spiral routes behind finger/gap capacitors on one probe-line conductor between two 50 Ω launchers. The other chips
have no circuit LOM: transmission lines only, or DC/process structures (AirbridgeCrossings' 1280 mechanical-test
bridges are ground straps; the LOM `Airbridge` model is a wire, so their unconnected ports have no node yet).

### Targets (if stated)
Shaping: `segment_length_target_rr=[611.586, 1834.76, 611.586]`, `segment_length_target_pr=[3158.32, 789.581]`,
`caps_length=[37.5, 67.9, 36.2]` (J, κ, drive). The others give no targets.

### Simplifications for a first rebuild
Build Simple first: it is the smoke test for KQC parity. AirbridgeDcTest, JunctionTest2, TsvTest and DcTest are pure
placement. The polygon-only chips (JunctionTest, Stripes, Empty) wait for a polygon primitive, or for a `static:`
import of the KQC-built cell (which currently needs ≥ 1 dummy port).

### Quantcore PDK rebuild (2026-11-03)

The notebook is a **Quantcore-PDK rebuild**, not a replica (design rule, 2026-11-03): the netlist, LOM and imported components are kept, the process is Quantcore's.

**[`simple`](../../../examples/designs/kqc/simple.ipynb)**

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 10 × 10 mm chip (its launchers sit on the chip edges, so the design does not fit the 7.5 mm die); KQC's ChipFrame (dicing edge, corner markers, labels) is not drawn.
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); KQC's own simulation default is silicon (εr 11.45), so LOM capacitances and resonator frequencies here are for sapphire.
- **Junctions:** Quantcore Nb/AlOx/Nb trilayer junctions (`junction_type` from `layouts.registry.trilayer_junction`): fingers on 2/0 + 4/0, spacer 50/0 with the 51–53/0 gradient, sized on the PDK junction rule (Nb Δ = 1.4 meV, I_c·R_n = πΔ/2e, R_n·A 13.5 kΩ·µm² and C_J 50 fF/µm² assumed); the Swissmon's SQUID becomes a PDK SQUID of two 0.25 × 0.6 µm junctions → R_n = 45 kΩ in parallel, L_J = 6.73 nH at zero flux, C_J = 15 fF (in the 40–50 kΩ window) — KQC's `junction_width` sets the straight finger — in place of the assumed Lj 12 nH + 2 fF. Expected f_q ≈ 6.0 GHz (was 4.74 GHz) (estimate from the pre-rebuild LOM C_Σ).
- **Kept:** the topology and every KQC element with the source's parameters, positions and orientations, the launcher assignment, every route's path and length, the sim groups.

**[`shaping`](../../../examples/designs/kqc/test_chips/shaping.ipynb)**

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 10 × 10 mm chip (its launchers sit on the chip edges, so the design does not fit the 7.5 mm die); KQC's ChipFrame (dicing edge, corner markers, labels) is not drawn.
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); KQC's own simulation default is silicon (εr 11.45), so LOM capacitances and resonator frequencies here are for sapphire.
- **Junctions:** Quantcore Nb/AlOx/Nb trilayer junctions (`junction_type` from `layouts.registry.trilayer_junction`): fingers on 2/0 + 4/0, spacer 50/0 with the 51–53/0 gradient, sized on the PDK junction rule (Nb Δ = 1.4 meV, I_c·R_n = πΔ/2e, R_n·A 13.5 kΩ·µm² and C_J 50 fF/µm² assumed); the Swissmon's SQUID becomes a PDK SQUID of two 0.25 × 0.6 µm junctions → R_n = 45 kΩ in parallel, L_J = 6.73 nH at zero flux, C_J = 15 fF (in the 40–50 kΩ window) — KQC's `junction_width` sets the straight finger — in place of the assumed Lj 12 nH + 2 fF. Expected f_q ≈ 6.4 GHz (was 5.17 GHz), below the ≈ 8.5 GHz readout (estimate from the pre-rebuild LOM C_Σ).
- **Kept:** the topology and every KQC element with the source's parameters, positions and orientations, the launcher assignment, every route's path and length, the sim groups (KQC's `cap_params` capacitors, every straight with KQC's length formula).

**[`airbridge_crossings`](../../../examples/designs/kqc/test_chips/airbridge_crossings.ipynb)**

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 10 × 10 mm chip (its launchers sit on the chip edges, so the design does not fit the 7.5 mm die); KQC's ChipFrame (dicing edge, corner markers, labels) is not drawn.
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); KQC's own simulation default is silicon (εr 11.45), so LOM capacitances and resonator frequencies here are for sapphire.
- **Junctions:** none on this chip (no qubits or junctions).
- **Kept:** the topology and every KQC element with the source's parameters, positions and orientations, the launcher assignment, every route's path and length, the sim groups (the 20 crossings, the 608-CPW / 1280-bridge array; airbridges on 300/0 + 301/0).

**[`crossing_twoface`](../../../examples/designs/kqc/test_chips/crossing_twoface.ipynb)**

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 10 × 10 mm chip (its launchers sit on the chip edges, so the design does not fit the 7.5 mm die); KQC's ChipFrame (dicing edge, corner markers, labels) is not drawn; the top chip (face 2b1) gets no frame: PDK v3 defines none for the flip-chip top chip (its layers export to 800–804/0).
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); KQC's own simulation default is silicon (εr 11.45), so LOM capacitances and resonator frequencies here are for sapphire.
- **Junctions:** none on this chip (no qubits or junctions).
- **Kept:** the topology and every KQC element with the source's parameters, positions and orientations, the launcher assignment, every route's path and length, the sim groups (both faces, the face changes and flip-chip connectors).

**[`quality_factor_twoface`](../../../examples/designs/kqc/test_chips/quality_factor_twoface.ipynb)**

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 10 × 10 mm chip (its launchers sit on the chip edges, so the design does not fit the 7.5 mm die); KQC's ChipFrame (dicing edge, corner markers, labels) is not drawn; the top chip (face 2b1) gets no frame: PDK v3 defines none for the flip-chip top chip (its layers export to 800–804/0).
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); KQC's own simulation default is silicon (εr 11.45), so LOM capacitances and resonator frequencies here are for sapphire.
- **Junctions:** none on this chip (no qubits or junctions).
- **Kept:** the topology and every KQC element with the source's parameters, positions and orientations, the launcher assignment, every route's path and length, the sim groups (resonator lengths 5374–5589 µm, the capped-CPW probe line, the top-chip lid).

**[`sample_holder_test`](../../../examples/designs/kqc/test_chips/sample_holder_test.ipynb)**

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 10 × 10 mm chip (its launchers sit on the chip edges, so the design does not fit the 7.5 mm die); KQC's ChipFrame (dicing edge, corner markers, labels) is not drawn.
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); KQC's own simulation default is silicon (εr 11.45), so LOM capacitances and resonator frequencies here are for sapphire.
- **Junctions:** none on this chip (no qubits or junctions).
- **Kept:** the topology and every KQC element with the source's parameters, positions and orientations, the launcher assignment, every route's path and length, the sim groups (KQC's `produce_n_launchers(40, …)` and the 20 lines).

**[`airbridge_dc_test`](../../../examples/designs/kqc/test_chips/airbridge_dc_test.ipynb)**

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 10 × 10 mm chip; the KQC chip PCell is placed with `frames_enabled=[]`, so its own ChipFrame (dicing edge, markers, labels) is not drawn.
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); KQC's own simulation default is silicon (εr 11.45), so LOM capacitances and resonator frequencies here are for sapphire.
- **Junctions:** none on this chip (no qubits or junctions).
- **Kept:** the whole KQC chip PCell with the source's parameters (KQC's own `build()`).

**[`empty`](../../../examples/designs/kqc/test_chips/empty.ipynb)**

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 10 × 10 mm chip; the KQC chip PCell is placed with `frames_enabled=[]`, so its own ChipFrame (dicing edge, markers, labels) is not drawn.
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); KQC's own simulation default is silicon (εr 11.45), so LOM capacitances and resonator frequencies here are for sapphire.
- **Junctions:** none on this chip (no qubits or junctions).
- **Kept:** the whole KQC chip PCell with the source's parameters (KQC's own `build()`).

**[`junction_test`](../../../examples/designs/kqc/test_chips/junction_test.ipynb)**

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 10 × 10 mm chip; the KQC chip PCell is placed with `frames_enabled=[]`, so its own ChipFrame (dicing edge, markers, labels) is not drawn.
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); KQC's own simulation default is silicon (εr 11.45), so LOM capacitances and resonator frequencies here are for sapphire.
- **Junctions:** none on this chip (the KQC cell draws EBL test squares, no junctions).
- **Kept:** the whole KQC chip PCell with the source's parameters (KQC's own `build()`).

**[`lithography_test`](../../../examples/designs/kqc/test_chips/lithography_test.ipynb)**

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 10 × 10 mm chip; the KQC chip PCell is placed with `frames_enabled=[]`, so its own ChipFrame (dicing edge, markers, labels) is not drawn.
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); KQC's own simulation default is silicon (εr 11.45), so LOM capacitances and resonator frequencies here are for sapphire.
- **Junctions:** none on this chip (no qubits or junctions).
- **Kept:** the whole KQC chip PCell with the source's parameters (KQC's own `build()`).

**[`lithography_test_twoface`](../../../examples/designs/kqc/test_chips/lithography_test_twoface.ipynb)**

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 10 × 10 mm chip; the KQC chip PCell is placed with `frames_enabled=[]`, so its own ChipFrame (dicing edge, markers, labels) is not drawn; the top chip (face 2b1) gets no frame: PDK v3 defines none for the flip-chip top chip (its layers export to 800–804/0).
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); KQC's own simulation default is silicon (εr 11.45), so LOM capacitances and resonator frequencies here are for sapphire.
- **Junctions:** none on this chip (no qubits or junctions).
- **Kept:** the whole KQC chip PCell with the source's parameters (KQC's own `build()`).

**[`stripes`](../../../examples/designs/kqc/test_chips/stripes.ipynb)**

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 10 × 10 mm chip; the KQC chip PCell is placed with `frames_enabled=[]`, so its own ChipFrame (dicing edge, markers, labels) is not drawn.
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); KQC's own simulation default is silicon (εr 11.45), so LOM capacitances and resonator frequencies here are for sapphire.
- **Junctions:** none on this chip (no qubits or junctions).
- **Kept:** the whole KQC chip PCell with the source's parameters (KQC's own `build()`).

**[`tsv_test`](../../../examples/designs/kqc/test_chips/tsv_test.ipynb)**

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 10 × 10 mm chip; the KQC chip PCell is placed with `frames_enabled=[]`, so its own ChipFrame (dicing edge, markers, labels) is not drawn; the top chip (face 2b1) gets no frame: PDK v3 defines none for the flip-chip top chip (its layers export to 800–804/0).
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); KQC's own simulation default is silicon (εr 11.45), so LOM capacitances and resonator frequencies here are for sapphire.
- **Junctions:** none on this chip (no qubits or junctions).
- **Kept:** the whole KQC chip PCell with the source's parameters (KQC's own `build()`).

**[`junction_test2`](../../../examples/designs/kqc/test_chips/junction_test2.ipynb)**

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 10 × 10 mm chip; the KQC chip PCell is placed with `frames_enabled=[]`, so its own ChipFrame (dicing edge, markers, labels) is not drawn.
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); KQC's own simulation default is silicon (εr 11.45), so LOM capacitances and resonator frequencies here are for sapphire.
- **Junctions:** Quantcore Nb/AlOx/Nb trilayer junctions (`junction_type` from `layouts.registry.trilayer_junction`): fingers on 2/0 + 4/0, spacer 50/0 with the 51–53/0 gradient, sized on the PDK junction rule (Nb Δ = 1.4 meV, I_c·R_n = πΔ/2e, R_n·A 13.5 kΩ·µm² and C_J 50 fF/µm² assumed); every test SQUID is a Quantcore SQUID (`junction_type="Quantcore Squid"` on the chip cell): KQC's stepped `junction_width` is the straight finger, the bent finger stays 0.6 µm. KQC's large-loop sweep starts at 0.08 µm, below the PDK minimum finger (0.1 µm), so it starts at 0.10 µm here (step 0.03 µm kept); the small-loop sweep keeps 0.15 µm + 0.01 µm steps. Per SQUID, R_n then spans ≈ 75 → 21 kΩ (small loops, 0.15–0.53 µm) and ≈ 113 → 12 kΩ (large loops, 0.10–0.94 µm), across the 40–50 kΩ window (section 4).
- **Kept:** the whole KQC chip PCell with the source's parameters (KQC's own `build()`) (the six arrays, pad sizes, loop areas, the step sizes).
