# Two coupled transmons (SQDMetal)

Two floating pocket transmons 1 mm apart, joined by a straight CPW between their facing connection pads. There is no resonator: the coupling is a direct capacitive link. It is SQDMetal's two-transmon eigenmode example (Apache-2.0), rebuilt on the Quantcore PDK with the `metal:TransmonPocket` wrapper.

Build this one to learn the smallest two-qubit chip and how a Qiskit Metal component is used through the `metal:` wrapper.

```{image} ../../images/designs/sqdmetal/two_transmon.png
:alt: The whole two_transmon chip as the v2 notebook builds it
:width: 100%
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/sqdmetal/two_transmon.ipynb` (the one-cell version before the rewrite: `two_transmon.v1.ipynb`) |
| Source | SQDMetal example `two_transmon.ipynb`, Apache-2.0 |
| Chip | 7.5 × 7.5 mm Quantcore die, the source's 2.2 × 1.8 mm area in its middle, CPW 10 / 6 µm |
| On the chip | 2 Metal pocket transmons · 1 straight CPW coupler |
| Builds today | yes: layout run 2026-11-19, 7 s, the saved design is byte-identical to the one before the rewrite |

## How the notebook builds it

```{image} ../../images/designs/sqdmetal/two_transmon_steps.png
:alt: The layout segments of two_transmon, one picture each
:width: 100%
```

1. **Die.** The Quantcore die with the frame and the device ID.
2. **Bond pads.** None.
3. **Readout line.** None.
4. **Qubits.** Two `metal:TransmonPocket` cells.
5. **Readouts.** None.
6. **Coupling.** One straight CPW between the two `readout` pins.
7. **Control lines.** None.
8. **Whole chip.** One sim group, centring, save.

## LOM estimates

Numbers are from a run of this notebook on 2026-11-19 (Setup, Design, Check and the LOM cells, 6 s): QuCat normal modes with QuTiP dressed values.

| parameter | LOM (QuTiP) | target |
|---|---|---|
| `Q1.f_q_GHz` | 7.07 | – |
| `Q1.alpha_MHz` | -349 | – |
| `Q2.f_q_GHz` | 7.73 | – |
| `Q2.alpha_MHz` | -324 | – |

| group | pair | ZZ (kHz) | neighbours | hybridised |
|---|---|---|---|---|
|  | Q1-Q2 | -3880 | yes | no |

```{image} ../../images/designs/sqdmetal/two_transmon_lom.png
:width: 80%
:alt: LOM plot of two_transmon
```

These are lumped-model estimates (component formulas and calibration), not FEM results; see [the LOM page](../../library/lom.md) for how far to trust them.

## Build spec

The rest of this page is the detailed spec the notebook was built from: every component, port, route and length.

> **Update 2026-11-03:** frame = **source**: build with `chip={"die_frame": False, ...}` so the replica keeps its own size and frame (the Quantcore PDK die frame is for Quantcore chips only). `metal:<Class>` wrappers are READY (ports = Metal pin names, params = Metal options), so the `metal:` refs in this spec build as written; the Quantcore/KQC substitutions stay optional. Buildable now: **yes** (`metal:TransmonPocket`).

Source: [doc-sphinx/source/examples/two_transmon.ipynb](https://github.com/sqdlab/SQDMetal/blob/main/doc-sphinx/source/examples/two_transmon.ipynb) · licence **Apache-2.0** (`LICENSE`, verified) · read 2026-11-02. The notebook
has no stored outputs. Quantum Metal design, SQDMetal Palace eigenmode (2 modes from 5 GHz), silicon.
What it is: two floating pocket transmons 1 mm apart. Their facing connection pads are joined by a straight CPW, so
the coupling is a direct capacitive link with no resonator. This is a minimal 2-qubit EPR / eigenmode test.
Frame: Metal chip 2.2 × 1.8 mm centred at (0.5, 0) mm, substrate 500 µm (size_z −500 µm). **Box (0, 0, 2200, 1800)**,
**Designer = source + (600, 900)**. CPW: Metal defaults (cpw_width 10, cpw_gap 6).
Status: **metal (`metal:TransmonPocket`)**. Geometry-only stand-in today: KQC `DoublePads`.

### Components
| instance | catalog ref | key params (units) | at (x, y) Designer | rot | notes |
|---|---|---|---|---|---|
| Q1 | `metal:TransmonPocket` · stand-in `DoublePads` | pad_width 425, pocket_height 650; other Metal defaults: pad_height 90, pad_gap 30, pocket_width 650. Connection pad `readout`: loc_W +1, loc_H +1 (top-right, facing Q2), pad_width 200 | (600, 900) | 0 | source (0, 0) |
| Q2 | same | same, `readout` loc_W −1, loc_H +1 (top-left, facing Q1) | (1600, 900) | 0 | source (1000, 0) |

Junctions (Palace lumped ports): Q1 **L_J 13 nH**, Q2 **L_J 9 nH**, C_J 0, so `junction={"Lj_nH": 13, "Cj_fF": 0}` and
`{"Lj_nH": 9, "Cj_fF": 0}`.

### Routes
| route | from → to | type, length | notes |
|---|---|---|---|
| COUPLER | Q1.readout → Q2.readout | cpw straight (`RouteStraight`, hfss_wire_bonds) | ≈ 1000 − 2·(325 + cpw_extend) µm. Galvanically joins the two connector pads |

With the DoublePads stand-in, `cplr` sits at the top centre, not at the top corner. Route Q1.cplr → Q2.cplr with
nodes above the pockets, or rotate the qubits ±90° so the couplers face each other.

### Launchers, pads, test structures, markers, labels
None (eigenmode model only).

### LOM node structure
Q1, Q2: floating two-island transmons (two pad nodes each, JJ between them). Each has one connector pad with C to one
island. The connector pads plus the CPW form one shared coupler node, giving Q1–Q2 coupling through C_c1 and C_c2 in
series via that node. No resonators, feedlines or control lines.

### Targets
None stated. The detuning comes from Lj 13 vs 9 nH (eigenmodes searched from 5 GHz).

### Simplifications for a first rebuild
1. `DoublePads` (island extents [425, 90], island_island_gap 30, ground_gap [650, 650]) with rot 90/270 so `cplr`
   faces the other qubit. The LOM for DoublePads is not implemented yet.

### Build (2026-11-03)
Built with `metal:TransmonPocket` (the Metal cell itself, not the DoublePads stand-in); coupler route r = 20 µm (the two pins are 150 µm apart).

### Quantcore PDK rebuild (2026-11-03)

The notebook is a **Quantcore-PDK rebuild**, not a replica (design rule, 2026-11-03): the netlist, LOM and imported components are kept, the process is Quantcore's.

Notebook: [`examples/designs/sqdmetal/two_transmon.ipynb`](../../../examples/designs/sqdmetal/two_transmon.ipynb).

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), on the 7.5 × 7.5 mm Quantcore die; the source's 2.2 × 1.8 mm chip area is centred in it (`box=(-2650, -2850, 4850, 4650)`), so every coordinate stays the source's.
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); the SQDMetal examples are on silicon (280–500 µm), so frequencies differ from the source's.
- **Junctions:** Quantcore Nb/AlOx/Nb trilayer junctions (`junction_type` from `layouts.registry.trilayer_junction`): fingers on 2/0 + 4/0, spacer 50/0 with the 51–53/0 gradient, sized on the PDK junction rule (Nb Δ = 1.4 meV, I_c·R_n = πΔ/2e, R_n·A 13.5 kΩ·µm² and C_J 50 fF/µm² assumed). The source detunes the pair with its Palace junctions (13 / 9 nH); the rebuild keeps that order at the two ends of the 40–50 kΩ window: Q1 R_n 50 kΩ (L_J ≈ 7.5 nH, C_J ≈ 13.5 fF), Q2 40 kΩ (≈ 6.0 nH, ≈ 16.8 fF). Expected f_q ≈ 7.0 / 7.8 GHz (estimates; were 5.92 / 7.21 GHz).
- **Kept:** the topology (two floating pockets, a straight coupler), the Metal components with the source's options and positions, the sim group.
