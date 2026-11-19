# Filled qubit test chip (QPDK)

The qubit test chip from gdsfactory's quantum-rf-pdk (QPDK), with a vortex-trap fill added to the ground plane: four double-pad transmons, each read out through its own λ/2 line hanging on a U-shaped probeline. The layout comes from QPDK's `filled_test_chip.py` (MIT) and is rebuilt on the Quantcore PDK: sapphire, Quantcore junctions and the QCT die frame. The rebuild is distributed under GPL-3.0.

Build this one to learn how a notebook loads another design read-only, and how a foreign fill pattern becomes a PDK cheese rule (the original fill wins over the PDK band).

```{image} ../../images/designs/qpdk/filled_qubit_test_chip.png
:alt: The whole filled_qubit_test_chip chip as the v2 notebook builds it
:width: 100%
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/qpdk/filled_qubit_test_chip.ipynb` (the one-cell version before the rewrite: `filled_qubit_test_chip.v1.ipynb`) |
| Source | gdsfactory `quantum-rf-pdk` `qpdk/samples/filled_test_chip.py`, MIT (© 2024 gdsfactory) |
| Chip | 7.5 × 7.5 mm Quantcore die, the source's 4250 × 6200 µm circuit centred in it, CPW 10 / 6 µm |
| On the chip | 4 launchers · 4 double-pad transmons with trilayer SQUIDs · 4 λ/2 readouts · 1 probeline with 2 series IDCs · 2 flux lines · vortex-trap fill |
| Builds today | yes: layout run 2026-11-19, 5 s, the saved design is byte-identical to the one before the rewrite |

## How the notebook builds it

```{image} ../../images/designs/qpdk/filled_qubit_test_chip_steps.png
:alt: The layout segments of filled_qubit_test_chip, one picture each
:width: 100%
```

1. **Load.** The qubit test chip's saved design is loaded read-only; only the name, the device ID and the cheese mode change.
2. **Pads.** The four launchers, 100 µm from the die edge (zoomed on the input pad).
3. **Probeline.** The two series IDCs and the U-shaped probeline between them.
4. **Qubits.** The double-pad transmons Q1 and Q2 with their SQUIDs (Q3 and Q4 mirror them).
5. **Readouts.** The λ/2 readouts that end in a coupled section on the probeline.
6. **Coupling.** None: the qubits only talk to their own readouts.
7. **Flux lines.** The open end of a flux line between two qubits, and the nine route lengths.
8. **Fill.** QPDK's 15 µm vortex holes on an 85 µm pitch, written as the chip's `cheese` rule; the design is saved.

## LOM estimates

Numbers are from a run of this notebook on 2026-11-19 (Setup, Design, Check and the LOM cells, 7 s): QuCat normal modes with QuTiP dressed values.

| group | qubit | f_q (GHz) | α (MHz) | resonator | f_r (GHz) | κ (MHz) | χ (MHz) |
|---|---|---|---|---|---|---|---|
| Q1R1 | Q1 | 5.763 | -196 | R1 | 11.87 | 0.638 | -1.36 |
| Q2R2 | Q2 | 5.763 | -197 | R2 | 12.86 | 0.206 | -1.27 |
| Q3R3 | Q3 | 5.764 | -197 | R3 | 16.16 | 0.4 | 1.61 |
| Q4R4 | Q4 | 5.763 | -197 | R4 | 12.33 | 0.713 | -1.31 |

```{image} ../../images/designs/qpdk/filled_qubit_test_chip_lom.png
:width: 80%
:alt: LOM plot of filled_qubit_test_chip
```

These are lumped-model estimates (component formulas and calibration), not FEM results; see [the LOM page](../../library/lom.md) for how far to trust them.

## Build spec

The rest of this page is the detailed spec the notebook was built from: every component, port, route and length.

> **Update 2026-11-03:** frame = **source**: build with `chip={"die_frame": False, ...}` so the replica keeps its own size and frame (the Quantcore PDK die frame is for Quantcore chips only). The KQC `DoublePads` LOM model is done (`lom/kqc_models.py`).

Source: [qpdk/samples/filled_test_chip.py](https://github.com/gdsfactory/quantum-rf-pdk/blob/main/qpdk/samples/filled_test_chip.py)
(`filled_qubit_test_chip`) · licence MIT (gdsfactory 2024, verified) · read 2026-11-02.
What it is: the [qubit_test_chip](qubit_test_chip.md) YAML loaded unchanged. A vortex-trapping hole fill is added to
the ground plane, then a 100 µm etched chip-edge frame, and the result is converted to a negative (`apply_additive_metals`).
The sample says it "roughly corresponds" to Tuokkola et al., *Methods to achieve near-millisecond coherence times in
superconducting quantum circuits* (Nat. Commun. 2025). That paper's fab GDS is the Zenodo record noted in
[community/tuokkola_near_ms_transmon](../community/tuokkola_near_ms_transmon.md). Image: `docs/_static/images/filled_qubit_test_chip.png`.
Frame: `chip_edge(size=(xsize + 230, ysize + 200), width=100)` at (xmin − 100, ymin − 100) gives
**box (0, 0, 4245, 6200)** (spec uses 4250). **Designer = source + (100, 3100)**, the same frame as qubit_test_chip.
Status: **yes**. Same components as qubit_test_chip, and the fill maps to the KQC ground grid.

The same file also defines `filled_flipmon_test_chip` and `filled_gatemon_test_chip` (same fill on those YAMLs). For a
flip-chip YAML it also adds an M2 edge and an M2 fill (80 µm keep-out).

### Components
Identical to [qubit_test_chip → Components](qubit_test_chip.md#components): PAD_IN, PAD_OUT, PAD_FT, PAD_FB,
C_IN, C_OUT, Q1–Q4 (`DoublePads`), same positions in the same Designer frame.

| instance | catalog ref | key params (units) | at (x, y) | rot | notes |
|---|---|---|---|---|---|
| (chip) | `Designer(..., chip={"with_grid": True})` | KQC ground grid | box (0, 0, 4250, 6200) | — | stands in for `fill_magnetic_vortices(rectangle_size=(15, 15), gap=70, stagger=2)` |
| EDGE | chip frame | 100 µm etched border | box edge | — | QPDK `chip_edge(width=100, layer=M1_ETCH)`; the KQC chip frame/dicing edge covers it |

QPDK fill: 15 × 15 µm etched squares on a 70 µm gap grid, every second row staggered. Squares are kept clear of
all drawn metal and etch by the fill routine's default keep-out. If our grid parameters can be set, match them:
hole 15 µm, pitch 85 µm, staggered rows.

### Routes
Identical to [qubit_test_chip → Routes](qubit_test_chip.md#routes) (FL_IN, FL, FL_OUT, R1–R4 hangers, FLUX_T, FLUX_B).

### Launchers, pads, test structures, markers, labels
4 launchers, chip edge, ground fill. No markers or labels.

### LOM node structure
Same as qubit_test_chip. The fill does not change the netlist. It only lowers ground-plane capacitance slightly,
so FEM extraction should run on the filled geometry.

### Targets
None stated. The reference device (Tuokkola 2025) is a single fixed-frequency transmon chip. This sample keeps
the 4-qubit QPDK layout and only borrows the fill and edge treatment.

### Simplifications for a first rebuild
1. Build qubit_test_chip first, then switch `chip={"with_grid": True}`.
2. Exact QPDK fill geometry (15 µm squares, 70 µm gaps, stagger 2) is optional. The KQC grid is close enough for
   layout review, but use the exact fill for FEM loss studies.

### Build (2026-11-03)
Built: `examples/designs/qpdk/filled_qubit_test_chip.ipynb`, loads `qubit_test_chip.json` read-only. Fill = KQC ground grid (5 µm holes, 10 µm pitch; QPDK's 15 µm / 70 µm gap / stagger cannot be set: request for lead). Edge = KQC frame with dice_width 100, markers and labels off.

### Quantcore PDK rebuild (2026-11-03)

The notebook is a **Quantcore-PDK rebuild**, not a replica (design rule, 2026-11-03): the netlist, LOM and imported components are kept, the process is Quantcore's.

Notebook: [`examples/designs/qpdk/filled_qubit_test_chip.ipynb`](../../../examples/designs/qpdk/filled_qubit_test_chip.ipynb).

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), on the 7.5 × 7.5 mm Quantcore die; the source's 4.25 × 6.2 mm chip area is centred in it (the box comes with the loaded qubit test chip), so every coordinate stays the source's; QPDK's 100 µm etched `chip_edge` is replaced by the frame.
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); QPDK's process is Al on Si (εr 11.45), so frequencies are not the QPDK ones.
- **Junctions:** as in the [qubit test chip](qubit_test_chip.md) (loaded with it): Quantcore trilayer SQUIDs on the PDK rule (`_qpdk.JJ_PARAMS`): two 0.25 × 0.6 µm junctions (KQC's `junction_width` = the straight finger) → R_n 45 kΩ in parallel, L_J 6.73 nH at zero flux, C_J 15 fF; fingers on 2/0 + 4/0, spacer 50/0 with the 51–53/0 gradient (Nb Δ = 1.4 meV, R_n·A 13.5 kΩ·µm² and C_J 50 fF/µm² assumed).
- **Kept:** the topology and every component with the source's parameters and positions, the readout / resonator lengths and coupled sections, the sim groups (the whole qubit test chip, loaded from its JSON).
