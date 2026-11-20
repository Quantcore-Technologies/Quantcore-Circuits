# iSWAP 3: crossmons and coupler

Two crossmons 600 µm apart with a tunable coupler above their inner arms. A through line arches over the chip, and
the two qubits' 2 mm meanders and the coupler's 1.5 mm meander end open next to it. It is example 3 of the Qiskit
Metal iSWAP-gate notebook (after Phys. Rev. X 11, 021058, Fig. 1; Apache-2.0, © IBM and contributors). The Quantcore
rebuild is distributed under GPL-3.0.

Build this one to learn how a flux-tunable pair with a tunable coupler is wired, with open readout meanders beside a
through line, four control lines and declared couplings. It fits inside the standard 7.5 mm Quantcore die.

```{image} ../../images/designs/metal/iswap3_xmon_tc.png
:alt: The whole iswap3 chip as the v2 notebook builds it
:width: 100%
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/metal/iswap3_xmon_tc.ipynb` (an older one-cell version is kept as `iswap3_xmon_tc.v1.ipynb`) |
| Source | Qiskit Metal `Full-Physical-Design-of-iSWAP-Gates.ipynb`, example 3, © IBM and contributors, Apache-2.0 |
| Chip | 7.5 × 7.5 mm Quantcore die (the source's 4 × 3 mm area centred in it), CPW 10 / 6 µm |
| On the chip | 2 crossmons with Quantcore SQUIDs · 1 tunable coupler · 3 open meanders (2 mm, 2 mm, 1.5 mm) · 1 through line · 4 control lines · 6 bond pads |
| Builds today | yes (layout built on 2026-11-19 in 9 s) |

## How the notebook builds it

```{image} ../../images/designs/metal/iswap3_xmon_tc_steps.png
:alt: The layout segments of iswap3, one picture each
:width: 100%
```

1. **Die.** The 7.5 mm die with the QCT frame (dicing marks, alignment grids, chip boundary, device ID).
2. **Bond pads.** Six launchpads slid to the 100 µm pad-edge rule (the picture zooms on one pad).
3. **Through line.** The east-west line arching over the chip, between its two end pads.
4. **Qubits.** Two flux-tunable crossmons with Quantcore SQUIDs.
5. **Readout meanders.** One 2 mm open meander from each qubit's claw to an open end beside the through line.
6. **Coupling.** The tunable coupler above the inner arms, its 1.5 mm meander, and the declared couplings.
7. **Control lines.** Four straight lines to the north and south pads, two crossing over the arch.
8. **Whole chip.** Sim groups for the FEM jobs, the content centred in the die, the design saved.

## LOM estimates

Numbers are from a run of this notebook on 2026-11-19 (Setup, Design, Check and the LOM cells, 9 s): QuCat normal modes with QuTiP dressed values.

| group | qubit | f_q (GHz) | α (MHz) | resonator | f_r (GHz) | κ (MHz) | χ (MHz) |
|---|---|---|---|---|---|---|---|
| Q1+coupler_right | Q1 | 5.846 | -203 | coupler_right | 28.59 | 0 | -0.00573 |
| Q2+coupler_left | Q2 | 5.846 | -203 | coupler_left | 28.59 | 0 | -0.00573 |
| TC+coupler_mid | TC | 7.899 | -394 | coupler_mid | 39.7 | 0 | -0.847 |

| group | pair | ZZ (kHz) | neighbours | hybridised |
|---|---|---|---|---|
| Q1+TC+Q2 | Q1-Q2 | – | yes | yes |
| Q1+TC+Q2 | Q1-TC | – | yes | yes |
| Q1+TC+Q2 | Q2-TC | – | yes | yes |

```{image} ../../images/designs/metal/iswap3_xmon_tc_lom.png
:width: 80%
:alt: LOM plot of iswap3_xmon_tc
```

These are lumped-model estimates from component formulas and calibration, not FEM results. [The LOM page](../../library/lom.md) says how far to trust them.

## Build spec

The rest of this page is the detailed spec the notebook was built from: every component, port, route and length.

> The `metal:` references in this spec build as written, through the `metal:` wrapper (ports are the Metal pin names, parameters the Metal options). The Quantcore and KQC substitutions are optional.

Source: Quantum Metal `docs/circuit-examples/F.Small-quantum-chips/Full-Physical-Design-of-iSWAP-Gates.ipynb`,
Example 3, after Phys. Rev. X 11, 021058 (2021), Fig. 1. The same qubit and coupler pair is in
`D.Qubit-couplers/31-TwoCrossmonsTunableCoupler`. Licence Apache-2.0.
The chip has two `TransmonCrossFL` crossmons 600 µm apart, with a `TunableCoupler01` (an interdigitated C-shaped
island with a SQUID and a flux line) above their inner arms. An east–west through line arches over the top of the
chip. Two 2 mm qubit readout meanders and a 1.5 mm coupler meander end open next to that line. There are 6 pads.
The chip is 4000 × 3000 µm, centred, so **Designer = Metal + (2000, 1500)**. CPW 10/6 µm and Metal defaults
(cross_width 20, cross_length 200 per arm, cross_gap 20; claw 30/10/6, ground_spacing 5).
A first build uses these substitutions: `Xmon` for TransmonCrossFL, `Xmon(flux_port)` for TunableCoupler01, hanger
`end="open"` for the OpenToGround ends.

### Components
| instance | catalog ref | key params (µm) | at (x, y) | rot | notes |
|---|---|---|---|---|---|
| Q1 | `Xmon(cross_length=400, arm_width=20, gap=20, claws=["n","e","w"], flux_port=True)` (metal:TransmonCrossFL) | Metal pads b (N, connector_type 1 = gap coupler), c (E, claw); fl_options default | (2700, 1500) | 0 | Metal at (2300, 1500); moved 400 µm E to make room for the coupler cell. Metal pins b (2300, 1781) N, c (2581, 1500) E, flux (2300, 1241.5) S |
| Q2 | `Xmon(... claws=["n","e","w"])`, no flux line | same | (1300, 1500) | 180 | Metal at (1700, 1500) (moved 400 µm W), orientation 180: b S (1700, 1219), c W (1419, 1500); its flux line is not routed in the source |
| TC | `Xmon(cross_length=200, arm_width=10, gap=10, claws=["w","e"], flux_port=True)` (metal:TunableCoupler01) | Metal c_width 400, l_width 20, l_gap 10, a_height 100, fl 5/3/10 | (2000, 1500) | 180 | Metal at (2000, 1650). Metal pins Control (2038, 1784) N, Flux (1886, 1777.5) N; after rot 180 the flux port faces N |
| T_west, T_east | `BondPad(pad_width=80, pad_height=80, pad_gap=58, taper_length=122)` | Metal default pad | (525, 1500), (3475, 1500) | 270, 90 | through line |
| T_NE, T_NW | `BondPad` | same | (2500, 2475), (1500, 2475) | 180 | Q1 drive (b), TC flux |
| T_SW, T_SE | `BondPad` | same | (1500, 525), (2500, 525) | 0 | Q2 drive (b), Q1 flux |

### Routes
| route | from → to | type, length | waypoints / hanger | notes |
|---|---|---|---|---|
| tline | T_east.a → T_west.a | cpw ≈ 4750–4960 | nodes [(3225, 1500), (3225, 2000), (2871, 2354), (1121, 2354), (768, 2000), (768, 1500)] | Metal RouteMeander with jogs R, 45°, 45°, 45°, 45°, R (all 0.5 mm, middle 1.75 mm). The Metal path overshoots T_west and doubles back; use the nodes instead |
| cpw_1 | T_SE.a → Q1.flux | cpw ≈ 800 | — | lead 250/250 |
| cpw_2 | T_SW.a → Q2.claw_n | cpw ≈ 780 | — | Metal Q2.b (gap coupler) → drive line; claw stands in for it |
| cpw_3 | T_NE.a → Q1.claw_n | cpw ≈ 780 | — | Metal Q1.b |
| cpw_4 | T_NW.a → TC.flux | cpw ≈ 930 | — | coupler flux bias |
| k1, k2 | Q1.claw_w → TC.claw_w; Q2.claw_w → TC.claw_e | cpw ≈ 200 | — | short capacitive links that replace the interdigitated overlap |
| coupler_right | Q1.claw_e → `tline.hanger(s≈400, length=100, side="left", end="open")` | meander 2000 | — | Metal open2 at (3100, 1500), 125 µm from the tline's x = 3225 vertical run; spacing 90, fillet 40 |
| coupler_left | Q2.claw_e → `tline.hanger(s≈3650, length=100, side="left", end="open")` | meander 2000 | — | Metal open3 at (900, 1500), beside the x = 768 vertical run |
| coupler_mid | (TC readout) → `tline.hanger(s≈2000, side="right", end="open")` | meander 1500 | — | Metal: TC.Control → open1 (2250, 2300), 54 µm below the y = 2354 run. Optional, because the Xmon stand-in has no free claw |

### Launchers, pads, test structures, markers, labels
6 default Metal pads: W/E for the through line, NE/SW for the qubit drives, SE for Q1 flux, NW for coupler flux.
There are no markers.

### LOM node structure
- Q1 and Q2 are fixed transmons; Q1 has a flux line in the layout. TC is a tunable coupler island with a SQUID biased
  from T_NW.
- The coupling chain is Q1, C, TC, C, Q2, plus the direct Q1–Q2 arm capacitance.
- The readout resonators (coupler_right/left, and the coupler's coupler_mid) have C_g at the claw and open ends
  capacitively coupled to the through line, which runs between the 50 Ω ports T_east and T_west.

### Targets (if stated)
None. The 2 mm open-open lines would resonate near 30 GHz, so the lengths are illustrative only.

### Simplifications for a first rebuild
1. Use realistic readout lengths: make each a λ/4 hanger with `end="short"`, meander about 4500 µm.
2. Drop coupler_mid until the coupler cell has a readout claw (or use KQC `Swissmon` for TC: cplr0/cplr2 to the
   qubits, cplr1 to the readout, flux port).
3. The qubit spacing is widened from 600 to 1400 µm so a coupler cell and the k1/k2 links fit. Keep this if
   `metal:TunableCoupler01` is not used.

### Quantcore PDK rebuild

The notebook is a Quantcore PDK rebuild of the source, not a replica: the netlist, LOM and imported components are kept, and the process is Quantcore's.

Notebook: [`examples/designs/metal/iswap3_xmon_tc.ipynb`](../../../examples/designs/metal/iswap3_xmon_tc.ipynb).

- Chip: the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), on the 7.5 × 7.5 mm Quantcore die; the source's 4 × 3 mm chip area is centred in it (`box=(-1750, -2250, 5750, 5250)`), so every coordinate stays the source's.
- Stack: sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); Metal's `DesignPlanar` default is silicon (εr 11.45, 750 µm), so the LOM capacitances, resonator frequencies and FEM jobs here are for sapphire rather than the source's substrate.
- Junctions: Quantcore Nb/AlOx/Nb trilayer junctions (`junction_type` from `layouts.registry.trilayer_junction`): fingers on 2/0 + 4/0, spacer 50/0 with the 51–53/0 gradient, sized on the PDK junction rule (Nb Δ = 1.4 meV, I_c·R_n = πΔ/2e, R_n·A 13.5 kΩ·µm² and C_J 50 fF/µm² assumed); the two `TransmonCrossFL` (flux lines) and the `TunableCoupler01` each get a PDK SQUID of two 0.25 × 0.6 µm junctions → R_n = 45 kΩ in parallel, L_J = 6.73 nH at zero flux, C_J = 15 fF (in the 40–50 kΩ window), in place of the assumed 10 nH + 2 fF. Expected f_q ≈ 5.8 GHz (an estimate), the coupler ≈ 7.9 GHz at zero flux. The two qubits stay identical.
- Kept: the topology and every Metal component with the source's options (through the `metal:` wrapper), positions and orientations, every route's end pins and total length, the sim groups (the three open meanders 1.5 / 2.0 / 2.0 mm, the arched through line, the two airbridges, the `d.couple` estimates).
