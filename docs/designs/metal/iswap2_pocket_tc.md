# iSWAP 2: pockets and coupler

Two large pocket transmons, 8 mm apart, joined through a flux-tunable coupler (a SQUID in a bus line with two round
pads). Each qubit has a 10 mm line to a launchpad, and the coupler has a flux line to a third. It is example 2 of the
Qiskit Metal iSWAP-gate notebook (after Phys. Rev. Research 2, 033447, Fig. 1, structure only; Apache-2.0, © IBM and
contributors). The Quantcore rebuild is distributed under GPL-3.0.

Build this one to learn how a tunable coupler sits between two qubits with a pocket of its own, and how long port
lines run to the pads. The chip has no readout resonator.

```{image} ../../images/designs/metal/iswap2_pocket_tc.png
:alt: The whole iswap2 chip as the v2 notebook builds it
:width: 100%
```

## At a glance

| | |
|---|---|
| Notebook | `examples/designs/metal/iswap2_pocket_tc.ipynb` (an older one-cell version is kept as `iswap2_pocket_tc.v1.ipynb`) |
| Source | Qiskit Metal `Full-Physical-Design-of-iSWAP-Gates.ipynb`, example 2, © IBM and contributors, Apache-2.0 |
| Chip | 16 × 6 mm (the source's size, larger than the 7.5 mm Quantcore die) |
| On the chip | 2 pocket transmons (1 × 0.4 mm pads) · 1 tunable coupler with a Quantcore SQUID · 2 lines of 10 mm · 1 flux line · 3 bond pads |
| Builds today | yes (layout built on 2026-11-19 in 9 s) |

## How the notebook builds it

```{image} ../../images/designs/metal/iswap2_pocket_tc_steps.png
:alt: The layout segments of iswap2, one picture each
:width: 100%
```

1. **Die.** An empty 16 × 6 mm chip with the QCT frame (dicing marks, alignment grids, chip boundary, device ID).
2. **Bond pads.** Three launchpads slid to the 100 µm pad-edge rule (the picture zooms on one pad).
3. **Readout.** None: the two 10 mm lines end on their pads, so they are port lines.
4. **Qubits.** Two mm-scale `TransmonPocket6` qubits with Quantcore junctions.
5. **Lines.** A 10 mm meandered line from each qubit's outer pad to its launchpad.
6. **Coupler.** The tunable coupler with its pocket and the two lines to the qubits.
7. **Flux line.** The coupler's flux bias line from the east pad.
8. **Whole chip.** The sim group (both qubits and the coupler), the centring check, the design saved.

## LOM estimates

Numbers are from a run of this notebook on 2026-11-19 (Setup, Design, Check and the LOM cells, 39 s): QuCat normal modes with QuTiP dressed values.

| group | qubit | f_q (GHz) | α (MHz) | resonator | f_r (GHz) | κ (MHz) | χ (MHz) |
|---|---|---|---|---|---|---|---|
| Q1+route4 | Q1 | 4.222 | -102 | – | – | – | – |
| Q2+route5 | Q2 | 4.222 | -102 | – | – | – | – |
| TC | TC | 5.149 | -155 | – | – | – | – |

```{image} ../../images/designs/metal/iswap2_pocket_tc_lom.png
:width: 80%
:alt: LOM plot of iswap2_pocket_tc
```

These are lumped-model estimates from component formulas and calibration, not FEM results. [The LOM page](../../library/lom.md) says how far to trust them.

## Build spec

The rest of this page is the detailed spec the notebook was built from: every component, port, route and length.

> The `metal:` references in this spec build as written, through the `metal:` wrapper (ports are the Metal pin names, parameters the Metal options). The Quantcore and KQC substitutions are optional.

> The notebook `examples/designs/metal/iswap2_pocket_tc.ipynb` builds all `metal:` cells (TransmonPocket6, TunableCoupler02) at the source's scale and adds a TC02 pocket of 3.8 × 2 mm. A coupled LOM of the TC02 model (a series SQUID) is not available.

Source: Quantum Metal `docs/circuit-examples/F.Small-quantum-chips/Full-Physical-Design-of-iSWAP-Gates.ipynb`,
Example 2, after Phys. Rev. Research 2, 033447 (2020), Fig. 1 (structure only). Licence Apache-2.0.
The chip has two large `TransmonPocket6` qubits, each with two pads. A `TunableCoupler02` (a floating two-pad SQUID
coupler with a flux-bias line) sits between them. Each qubit has a 10 mm meandered line to its own wire-bond pad, and
the coupler's flux line goes to a third pad.
mm-scale: pads 1 × 0.4 mm, pocket 1.5 × 1.2 mm, pad_gap 50 µm; coupler pocket 3 × 2 mm, pad radius 0.3 mm. The chip
is 16 × 6 mm centred at (0, 1) mm, so **Designer = Metal + (8000, 2000)**. `cpw_width` 10 µm, gap 6 µm.
A first build uses these substitutions: `Xmon` for TransmonPocket6, and an `Xmon` with `flux_port` as the
tunable-coupler transmon in place of TunableCoupler02.

### Components
| instance | catalog ref | key params | at (x, y) | rot | notes |
|---|---|---|---|---|---|
| Q1 | `Xmon(claws=["w","e"])` (metal:TransmonPocket6) | Metal pad 1000 × 400, pocket 1500 × 1200, pad_gap 50; pads bus_03 (loc_W 0, loc_H −1, w 100, gap 50), readout (0, +1, 100, 50); orientation 90 | (4000, 2000) | 0 | Metal pins: bus_03 E (4700, 2000) → coupler; readout W (3300, 2000) → P1 |
| Q2 | `Xmon(claws=["w","e"])` | same | (12000, 2000) | 0 | Metal: bus_03 E (12700, 2000) → P2; readout W (11300, 2000) → coupler |
| TC | `Xmon(claws=["w","e"], flux_port=True, cross_length=300)` (metal:TunableCoupler02) | Metal: pad_radius 300, bus_width 100, bus inner/outer 500, JJ 100 × 400, fbl 100 × 500, fbl_offset 100 | (8000, 2000) | 180 | flux points N after rot 180; Metal pins pin2 (6100, 2050) W, pin1 (9900, 2050) E, fbl (7550, 3000) N |
| P1_C | `BondPad(pad_width=500, pad_height=1000)` | lead 0 | (1000, 2500) | 0 | |
| P2_C | `BondPad` | same | (15000, 2500) | 0 | |
| P3_C | `BondPad` | same | (11000, 5000) | 90 | Metal orientation −180, faces W |

### Routes
| route | from → to | type, length | waypoints | notes |
|---|---|---|---|---|
| route1 | Q1.claw_e → TC.claw_e (faces W after rot 180) | cpw ≈ 1400 | — | Metal RouteStraight Q1.bus_03 → TC.pin2 |
| route2 | Q2.claw_w → TC.claw_w (faces E) | cpw ≈ 1400 | — | Metal Q2.readout → TC.pin1 (pin names swapped in the source) |
| route3 | P3_C.a → TC.flux | cpw ≈ 5320 (Metal) | [(x_flux, 5000)], x_flux ≈ 8010 = TC.flux x | Metal: W 3.4 mm to (7600, 5000), then down to fbl (7550, 3000); fillet 90 |
| route4 | Q1.claw_w → P1_C.a | meander 10 000 | — | lead 200/500, fillet 90, asym 0 |
| route5 | Q2.claw_e → P2_C.a | meander 10 000 | — | same |

### Launchers, pads, test structures, markers, labels
3 pads: P1 and P2 are the qubit lines (bottom edge) and P3 is the coupler flux bias (top). There are no markers.

### LOM node structure
- Q1 and Q2 are fixed transmons, each a two-pad island pair with a JJ (Xmon: island + JJ to ground).
- TC is a flux-tunable coupler: an island with a SQUID (`TrilayerSquid` / junction list) and the flux bias from P3.
- The coupling chain is Q1, C_g, TC, C_g, Q2.
- Each qubit has a 10 mm line to a 50 Ω port. It is a direct port line, not a resonator: the pads end galvanically
  on wire-bond pads.

### Targets (if stated)
None.

### Simplifications for a first rebuild
1. Scale the qubits down to the Xmon default size (cross_length 300). Keep the 4 mm qubit–coupler spacing, or shorten
   it to ≈1 mm with the routes as straight cpw.
2. The Metal "readout" lines are not resonators. To read out, replace route4 and route5 with λ/4 meanders hanging off
   a feedline (as in `A2_two_coupled`).
3. Put a SQUID on TC: `junction={"Lj_nH": [Lj1, Lj2]}` or `junction_type` for the SQUID.

### Quantcore PDK rebuild

The notebook is a Quantcore PDK rebuild of the source, not a replica: the netlist, LOM and imported components are kept, and the process is Quantcore's.

Notebook: [`examples/designs/metal/iswap2_pocket_tc.ipynb`](../../../examples/designs/metal/iswap2_pocket_tc.ipynb).

- Chip: the Quantcore die frame (L dicing markers 1000/0, 3 × 3 alignment grids 1001/0, chip boundary 100/0, device ID where an edge is free; any brand text is QCT), drawn on the source's 16 × 6 mm chip (the design does not fit the 7.5 mm die); no KQC chip frame.
- Stack: sapphire 650 µm, εr 10.25 (the PDK default stack, used by the LOM estimates and every FEM export); Metal's `DesignPlanar` default is silicon (εr 11.45, 750 µm), so the LOM capacitances, resonator frequencies and FEM jobs here are for sapphire rather than the source's substrate.
- Junctions: Quantcore Nb/AlOx/Nb trilayer junctions (`junction_type` from `layouts.registry.trilayer_junction`): fingers on 2/0 + 4/0, spacer 50/0 with the 51–53/0 gradient, sized on the PDK junction rule (Nb Δ = 1.4 meV, I_c·R_n = πΔ/2e, R_n·A 13.5 kΩ·µm² and C_J 50 fF/µm² assumed); both qubits get the PDK nominal junction, 0.5 × 0.6 µm fingers → R_n = 45 kΩ, L_J = 6.73 nH, C_J = 15 fF (in the 40–50 kΩ window), the coupler (`TunableCoupler02`, a series SQUID) a PDK SQUID of two 0.25 × 0.6 µm junctions → R_n = 45 kΩ in parallel, L_J = 6.73 nH at zero flux, C_J = 15 fF (in the 40–50 kΩ window), in place of the assumed 10 nH + 2 fF. Expected f_q ≈ 4.3 GHz (an estimate for the mm-scale pads), the coupler ≈ 5.3 GHz at zero flux. The two qubits stay identical.
- Kept: the topology and every Metal component with the source's options (through the `metal:` wrapper), positions and orientations, every route's end pins and total length, the sim groups (including the coupler pocket, which the rebuild adds).
