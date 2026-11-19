# XMonsDirectCoupling (KQC)

A KQCircuits chip with three Swissmon qubits in a row. Neighbouring qubits are coupled directly: their arm tips face each other across a small gap. Each qubit has a T-tapped quarter-wave readout into one probe line. It is rebuilt on the Quantcore PDK.

Build it to learn direct qubit-to-qubit coupling (declared in the netlist with `d.couple`) and T-tapped readouts.

```{image} ../../images/designs/kqc/xmonsdirectcoupling.png
:alt: The whole xmonsdirectcoupling chip as the v2 notebook builds it
:width: 100%
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/kqc/xmonsdirectcoupling.ipynb` (the one-cell version before the rewrite: `xmonsdirectcoupling.v1.ipynb`) |
| Source | KQCircuits `chips/xmons_direct_coupling.py` (`XMonsDirectCoupling`), © IQM Finland Oy, GPL-3.0 |
| Chip | 10 × 10 mm, SMA8 launchers, chip name "XMDC" |
| On the chip | 3 Swissmons 350 µm apart · 3 T-tapped λ/4 readouts · 1 probe line · 3 charge and 3 flux lines · 4 junction-test arrays |
| Builds today | yes: layout run 2026-11-19, 8 s, the saved design is byte-identical to the one before the rewrite |

## How the notebook builds it

```{image} ../../images/designs/kqc/xmonsdirectcoupling_steps.png
:alt: The layout segments of XMonsDirectCoupling, one picture each
:width: 100%
```

1. **Die.** The empty 10 × 10 mm chip with the Quantcore frame (dicing marks, alignment grids, chip boundary, device ID) and the eight launchers.
2. **Bond pads.** The launchers moved so their outer etch edge sits 100 µm from the die edge (the pad rule).
3. **Qubits.** Three Swissmons in a row with Quantcore SQUIDs.
4. **Readout line.** A T, capacitor and tail per qubit, then the probe line.
5. **Readouts.** The T-tapped λ/4 resonators.
6. **Direct coupling.** Declared with `d.couple` (no part of the layout joins the qubits).
7. **Control lines.** Charge and flux lines.
8. **Whole chip.** Sim groups, centring, design saved.

## LOM estimates

Numbers are from a run of this notebook on 2026-11-19 (Setup, Design, Check and the LOM cells, 10 s): QuCat normal modes with QuTiP dressed values.

| group | pair | ZZ (kHz) | neighbours | hybridised |
|---|---|---|---|---|
| QB1–QB2–QB3 | QB1-QB3 | – | no | yes |
| QB1–QB2–QB3 | QB1-QB2 | – | yes | yes |
| QB1–QB2–QB3 | QB2-QB3 | – | yes | yes |

| group | qubit | f_q (GHz) | α (MHz) | resonator | f_r (GHz) | κ (MHz) | χ (MHz) |
|---|---|---|---|---|---|---|---|
| QB1+RR1 | QB1 | 6.521 | -255 | RR1 | 5.204 | 10.2 | -2.3 |
| QB2+RR2 | QB2 | 6.543 | -256 | RR2 | 5.418 | 11.6 | -2.93 |
| QB3+RR3 | QB3 | 6.522 | -254 | RR3 | 5.376 | 10.4 | -3.46 |

```{image} ../../images/designs/kqc/xmonsdirectcoupling_lom.png
:width: 80%
:alt: LOM plot of xmonsdirectcoupling
```

These are lumped-model estimates (component formulas and calibration), not FEM results; see [the LOM page](../../library/lom.md) for how far to trust them.

## Build spec

The rest of this page is the detailed spec the notebook was built from: every component, port, route and length.

> **Update 2026-11-03:** frame = **source**: build with `chip={"die_frame": False, ...}` so the replica keeps its own size and frame (the Quantcore PDK die frame is for Quantcore chips only).

Source `other-libs/KQCircuits-main/KQCircuits-main/klayout_package/python/kqcircuits/chips/xmons_direct_coupling.py`
(`XMonsDirectCoupling`) · GPL-3.0 (IQM Finland). Rebuilt from extracted parameters. · What it is: 3 flux-tunable
Swissmons ("Finnmons") in a row, 350 µm apart, so neighbouring arm tips face each other across 10 µm and couple
directly. Each qubit has a T-tapped λ/4 readout resonator (86 Ω, a=5 b=20) coupled through a finger capacitor to one
probeline, which has a series input capacitor. There is a drive line and a flux line per qubit, plus the standard
junction-test arrays. · 10 × 10 mm, KQC frame = Designer frame · face 1t1 · **Buildable now: yes.** Checked
2026-11-02: every length matches KQC, and the LOM has no unconnected ports.

### Components
| instance | catalog ref | key params (units) | at (x, y) | rot | notes |
|---|---|---|---|---|---|
| QB1 | `Swissmon` | `COM` + `cpl_gap=[110,90,110], cpl_length=[0,158,0], cpl_width=[60,24,60], cl_offset=[150,-150]` | (4650, 5000) | 0 | cplr1 N (4650,5209); drive (4500,5150); flux S (4650,4746.67) |
| QB2 | `Swissmon` | `COM` + `cpl_gap=[110,102,110], cpl_length=[0,140,0], cpl_width=[60,24,60], cl_offset=[150,150]` | (5000, 5000) | 0 | cplr1 (5000,5215); drive (4850,4850); flux (5000,4746.67) |
| QB3 | `Swissmon` | as QB1 but `cl_offset=[-150,-150]` | (5350, 5000) | 0 | cplr1 (5350,5209); drive (5500,5150); flux (5350,4746.67) |
| PL1–PL3 | `WaveguideCoplanarSplitter` | `lengths=[11,11,31]`, `port_names=["right","left","bottom"]` | (x_k, 7900), x = 4650/5000/5350 | 0 | probeline T's; bottom faces down |
| CK1–CK3 | `FingerCapacitorSquare` | `finger_number=4`, `finger_length` 60.8 / 61.55 / 58.1, `CAP` | snap `b` → PLk.bottom | (→ 90) | κ capacitor |
| TP1–TP3 | `WaveguideCoplanarTaper` | `a=5, b=20, a2=10, b2=6, taper_length=100` | snap `b` → CKk.a | (→ 90) | 50 → 86 Ω |
| RT1–RT3 | `WaveguideCoplanarSplitter` | `lengths=[22.5,22.5,62.5], a_list=[5,5,5], b_list=[20,20,20]`, port_names as PL | snap `right` → TPk.a | (→ 90) | tap T in the resonator: left goes down to the qubit, bottom goes east to the tail |
| IN | `FingerCapacitorSquare` | `finger_number=8, finger_length=55.4`, `CAP` | (4294.8, 7900) | 0 | series input cap ("35 fF" in source); a (4239.6,7900), b (4350,7900) |
| testarray_w/s/e/n | `JunctionTestPadsSimple` | as in single_xmons | (350,3750) / (3750,350) / (8350,3750) / (3750,8350) | 0 | standard KQC junction tests |

`COM = dict(arm_length=[146]*4, island_r=2, port_width=[10,5,10], arm_width=[24]*4, gap_width=[24]*4)`;
`CAP = dict(finger_gap=5, finger_gap_end=5, finger_width=15, ground_padding=10)`.

### Routes
| route | from → to | type, length (µm) | waypoints | notes |
|---|---|---|---|---|
| RR1 / RR2 / RR3 | RTk.left → QBk.cplr1 | cpw a=5 b=20; 2399.2 / 2392.45 / 2401.9 | none (straight down) | KQC: n_bridges=10 |
| RS1 / RS2 / RS3 | RTk.bottom → free_end((x_k+162.5, y_k), term=0) | cpw a=5 b=20; 2384.4 / 2204.85 / 2199.8 | none (stub east 100, then down to y = 5303.38 / 5482.18 / 5490.68) | shorted tail of the λ/4 |
| PL_in | chip.NW → IN.a | cpw 2696.68 | (2800, 7900) | |
| PL_a / PL_b / PL_c | IN.b → PL1.left / PL1.right → PL2.left / PL2.right → PL3.left | 289 / 328 / 328 | none | |
| PL_out | PL3.right → chip.NE | 3096.08 | (7200, 7900) | |
| DL1 | chip.WN → QB1.drive | cpw `term2=6`, 4559.48 | (2500, 7200) | diagonal |
| DL2 | chip.SW → QB2.drive | `term2=6`, 4890.53 | (2800,2500), (4850,4550) | |
| DL3 | chip.EN → QB3.drive | `term2=6`, 4559.48 | (7500, 7200) | |
| FL1 | chip.WS → QB1.flux | cpw 4366.09 | (900,2800), (4650,4646.667) | diagonal |
| FL2 | chip.SE → QB2.flux | 4864.76 | (7200,2500), (5000,4646.667) | |
| FL3 | chip.ES → QB3.flux | 4366.09 | (9100,2800), (5350,4646.667) | |

```python
d = Designer("kqc_xmons_dc", launchers="SMA8", chip={"name_chip": "XMonsDC"})
q1 = d.add("QB1", "Swissmon", at=(4650, 5000), junction=J, cpl_gap=[110, 90, 110], cpl_length=[0, 158, 0],
           cpl_width=[60, 24, 60], cl_offset=[150, -150], **COM)          # QB2, QB3 likewise
for k, x, lf in ((1, 4650, 60.8), (2, 5000, 61.55), (3, 5350, 58.1)):
    d.add(f"PL{k}", "WaveguideCoplanarSplitter", at=(x, 7900), lengths=[11, 11, 31], port_names=["right", "left", "bottom"])
    d.add(f"CK{k}", "FingerCapacitorSquare", snap="b", to=f"PL{k}.bottom", finger_number=4, finger_length=lf, **CAP)
    d.add(f"TP{k}", "WaveguideCoplanarTaper", snap="b", to=f"CK{k}.a", a=5, b=20, a2=10, b2=6, taper_length=100)
    d.add(f"RT{k}", "WaveguideCoplanarSplitter", snap="right", to=f"TP{k}.a", lengths=[22.5, 22.5, 62.5],
          a_list=[5, 5, 5], b_list=[20, 20, 20], port_names=["right", "left", "bottom"])
    d.route(f"RR{k}", f"RT{k}.left", f"QB{k}.cplr1", a=5, b=20)
    d.route(f"RS{k}", f"RT{k}.bottom", Designer.free_end(at=(x + 162.5, {1: 5303.38, 2: 5482.18, 3: 5490.68}[k]), term=0), a=5, b=20)
d.couple("C12", "QB1", "QB2"); d.couple("C23", "QB2", "QB3")     # direct arm-tip coupling (value from a C-matrix)
```

### Launchers, pads, test structures, markers, labels
SMA8 default names, all 8 used: NW = probeline in, NE = probeline out; WN/SW/EN = drive QB1/QB2/QB3; WS/SE/ES = flux
QB1/QB2/QB3. There are 4 junction-test arrays.

### LOM node structure (qubit ↔ resonator ↔ feedline ↔ bus ↔ control lines)
- QB1–QB3: island + SQUID + cplr1. QB1–QB2 and QB2–QB3 are direct capacitances via `d.couple` (C-matrix value,
  `sim_group` over QB1..QB3).
- Readout k: QBk.cplr1 ≡ RTk node (the RR route is a wire). RSk becomes a λ/4 TLres there. CKk is the series C
  (estimate ≈ 20 fF) to the probeline node (PL1–PL3 merged). IN is the series C (estimate 39.8 fF) from chip.NW to
  the probeline, and chip.NE is a 50 Ω port.
- **LOM gap:** the real resonator is a tapped λ/4, RR (2.4 mm) + T + RS (2.2–2.4 mm) ≈ 4.7–4.9 mm. The builder only
  counts RS as the TLres (lumped f ≈ 13–14 GHz) and treats RR as a wire. For a correct LOM, override the length
  (KQC `length` = 4868.6 / 4682.3 / 4686.7) or add a "resonator through splitter" rule.
- DLk becomes a `drive` control and FLk a `flux_bias` control on J_QBk.

### Targets (if stated)
"Target parameters V2": resonator lengths 2421.5+2447.1, 2436+2246.3, 2438.5+2248.2 µm (non-tail + tail), finger
lengths 60.8 / 61.55 / 58.1 µm, input C ≈ 35 fF. Chip params: `qubit_spacing=10`, `arm_width_a=arm_width_b=24`,
`rr_cpl_width=[24,24,24]`.

### Simplifications for a first rebuild
Skip the junction tests and airbridges. KQC puts n_bridges of 25/30 on the control lines, 10/5 on the resonators and
1–4 on the probeline. If a single conductor per resonator is wanted in the LOM, keep the RT/TP chain in the layout
but set the TLres length by hand until the builder supports tapped resonators.

### Quantcore PDK rebuild (2026-11-03)

The notebook is a **Quantcore-PDK rebuild**, not a replica (design rule, 2026-11-03): the netlist, LOM and imported components are kept, the process is Quantcore's.

Notebook: [`examples/designs/kqc/xmonsdirectcoupling.ipynb`](../../../examples/designs/kqc/xmonsdirectcoupling.ipynb).

- **Chip:** the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 10 × 10 mm chip (its launchers sit on the chip edges, so the design does not fit the 7.5 mm die); KQC's ChipFrame (dicing edge, corner markers, labels) is not drawn.
- **Stack:** sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); KQC's own simulation default is silicon (εr 11.45), so LOM capacitances and resonator frequencies here are for sapphire.
- **Junctions:** Quantcore Nb/AlOx/Nb trilayer junctions (`junction_type` from `layouts.registry.trilayer_junction`): fingers on 2/0 + 4/0, spacer 50/0 with the 51–53/0 gradient, sized on the PDK junction rule (Nb Δ = 1.4 meV, I_c·R_n = πΔ/2e, R_n·A 13.5 kΩ·µm² and C_J 50 fF/µm² assumed); every Swissmon's SQUID becomes a PDK SQUID of two 0.25 × 0.6 µm junctions → R_n = 45 kΩ in parallel, L_J = 6.73 nH at zero flux, C_J = 15 fF (in the 40–50 kΩ window) — KQC's `junction_width` sets the straight finger — in place of the assumed Lj 16 nH + 2 fF. Expected f_q ≈ 6.5 GHz (was 4.47–4.49 GHz), above the ≈ 5.3–5.5 GHz readouts; the three qubits stay identical (hybridised) (estimate from the pre-rebuild LOM C_Σ). The four `JunctionTestPads` arrays get the same Quantcore SQUID.
- **Kept:** the topology and every KQC element with the source's parameters, positions and orientations, the launcher assignment, every route's path and length, the sim groups (the T-tapped readouts with KQC's tail lengths, the assumed 0.3 fF direct coupling).
