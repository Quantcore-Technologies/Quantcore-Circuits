# Simulation export audit (Q3D C-matrix, HFSS eigenmode)

Date: 2026-11-15, updated 2026-11-16 (causes C3–C9 fixed, audit re-run). Export only — **no AEDT was started, nothing was solved**. Every catalog cell (`qcc components --json --details`) that has a port or a junction, or is a qubit / resonator / coupler / junction — 105 cells on 2026-11-15, 106 on 2026-11-16 (WaveguideCoplanarCurved now has ports) — was placed alone in a scratch design and exported for `q3d_cmatrix` and `hfss_eigenmode`; the job folders were then checked with `quantcore_circuits.sim_tools.geometry_check` (what AEDT imports: one object per GDS polygon of each KQC metal layer).

Reproduce: `python scripts/check_sim_export.py audit --out <scratch dir>` (writes `audit.json` and a raw table); check any job folder with `python scripts/check_sim_export.py check <job>…`. Regression tests: `tests/test_sim_export_geometry.py` (C1, C1b, C2) and `tests/test_sim_export_causes.py` (C3–C9).

Scratch contexts: **qubits** (LOM model with a junction) — two BondPads, a pad-to-pad feedline and a hanger readout (`cpw`, short end) from the readout port turned towards the feedline, exported like the GUI's Simulate (`guiflow.export_manual`, group = qubit + readout, margin 300 µm; Lj = 10 nH, Cj = 2 fF); Gatemon with a GatemonCoupler on its readout edge and the feedline through the coupler; TransmonTaperedInsets with `connection_pads = {"readout": {}}`. **Other cells** — inline between two pads (first two CPW ports), else one pad into the first port, else alone; sim group = the cell, margin 100 µm, the lines cut by the box (edge ports / 50 Ω edge ports).

Checks per job: (1) **nets disjoint** — objects of different nets never touch or overlap (Q3D: "…are touching"); objects of one net never touch without overlapping (KQC joins them, Q3D splits the net); (2) **junction port polygon** — KQC itself finds the signal/ground edges (no `Unable to create polygon for port`), the sheet has no metal inside, its two edges are on two different nets, neither island net reaches the box edge; (3) no signal metal to the top/bottom of the domain; (4) HFSS line ports have polygons; warnings: unlabelled C-matrix nets, GDS polygons > 4095 points (metal and the gap layers AEDT imports as mesh-seed sheets), and — Q3D only — a junction island whose net also holds a line the box cuts at an edge port (its capacitance includes the cut line; before 2026-11-16 this was an error).

## The reported failure (build/test.json, Flipmon F1, `gui_sim` q3d_cmatrix)

`python scripts/check_sim_export.py check build/build/jobs/test_gui_sim_q3d_cmatrix` on a failed job (left unchanged) reports what AEDT hit:

```
error: net 1: 1t1_signal_1_0 and 1t1_signal_1_1 touch without overlapping (AEDT sees two conductors) at (4115.0, 6404.0) µm
error: F1.junction (port 1): KQC finds no metal edge at the signal point (4115.00, 6391.00)
error: F1.junction (port 1): KQC finds no metal edge at the ground point (4115.00, 6396.00)
error: F1.junction [stand-in sheet] (port 1): 40.00 µm² of metal inside the port sheet (the junction is shorted)
error: F1.junction [stand-in sheet] (port 1): both port edges are on net 1 (the junction is shorted)
error: 1t1_indium_bump_0 (net 1) reaches the top of the domain (0–1000 µm)
warning: net 1 is 2 separate conductors
```

The GDS has two polygons on `1t1_signal_1`: the disc (r = 60 µm) and ring + junction pads. The pads run from the ring edge (y 6384) to the disc edge (y 6404) with no gap (12 + 13 µm pads in a 20 µm gap) and meet the disc only at its vertex (4115, 6404); port 1's points (y 6391 / 6396) lie inside that metal. KQC put both polygons in net 1 (`Region.interacting` counts a vertex contact), AEDT's `AutoIdentifyNets` made the second one its own net and then refused two touching nets. After the fix the same export (`qcc sim subset test.json --instances F1`) has nets `F1.island2` (disc), `F1.coupler`, `F1.island1` (ring), an 8 × 8 µm KQC port sheet at y 6390–6398, no bump, and no check errors, for q3d_cmatrix and hfss_eigenmode.

Earlier exports affected (re-export before the next solve — no kept FEM results were found): `examples/designs/qpdk/flipmon_test_chip.json` (groups Q1R1…Q4R4: C1, `Q*.island1` was missing; Q1R1 and Q3R3 also C1b, a neighbour's point contact — Q3D would have stopped as on build/test.json), `examples/designs/sqdmetal/2_transmons_wres_comp.json` (ALL: `Q1/Q2.island2` missing), `build/test.json` (gui_sim). `examples/designs/sqdmetal/floating_transmon.json` (100 µm gap) exports bit-identically (XOR of the simulated metal = 0).

## Status after the C3–C9 fixes (2026-11-16)

Full audit re-run (`scripts/check_sim_export.py audit`, 106 cells × q3d_cmatrix + hfss_eigenmode, export only): **102 cells clean** in both analyses (was 72 of 105), **2 with check errors** (was 26: both are C5b, metal-only Metal qubits placed without their pocket — a scratch-context limit, not an export bug), **3 with warnings** (was 9): NeckTermination's Q3D job keeps a 5614-point polygon (flux-trap holes, see C8), SquidTermination's Q3D island includes its λ/4 line cut by the box (by design for a termination), metal:TunableCoupler02's stub port (C5b). KQC's `Unable to create polygon for port` now appears only for the two C5b cells (was 10 cells). Whole-chip check: `examples/tutorials/designs/t03_demoqpu17.json` q3d_cmatrix went from 68 errors (17 StarQubit junction ports × 4) and a > 4095-point warning to **0 errors, 0 warnings**; `examples/tutorials/designs/t02_ibm_bowtie_5q.json` triangle_A / triangle_B eigenmode_epr from 1 error each (R_Q0 / R_Q3 50 Ω port without polygon) to **0**.

Fab builds: all 105 example designs were built with the code before and after the change and XOR-ed per layer (instance-name labels 222/0 ignored): **104 identical**; the only difference is `examples/designs/amplifiers/qpdk_cpw_jpa.json` (SquidTermination, C9: 69.3 µm² on 130/1 at the new pocket strips). The simulation-side fixes (C3–C8) live in the simulation export only.

**Effect on the example designs' own sim groups** (153 of 515 group × analysis exports sampled — one per design and analysis kind — `build_simulation` before vs after, box / ports / nets / port polygons / simulated geometry compared): 96 identical, 57 changed, each for one of the causes above: bends simplified ≤ 0.05 µm where a polygon had > 4000 points (33 groups; 32 had > 4095-point polygons, up to 100 131); conductors that had no label now named (C7, e.g. chip_07_resonators R2, resonator_chip_01 R1, seven_qubit_processor Q0R, flipmon_test_chip Q1R1, fem_loop_rev0/1 FL2R); StarQubit-type junction ports moved onto the gap (C5: demoqpu17 / t03_demoqpu17, m53_wallraff_17q / t03_wallraff_17q, m54_wallraff_cell D5 — its Z3 junction pin lies outside the margin-0 box, now said in a note); eigenmode box edges moved 4–22 µm off bends (C6: sqchip_em Q1R and iswap3_xmon_tc Q1_read had a 50 Ω port without polygon; ibm_bowtie_5q / t02_ibm_bowtie_5q(_fb) Q2_read, ibm_falcon_27q Q0_read, a2_two_coupled_transmons Q1_read1, gatemon_test_chip CH_A had the edge on a bend, KQC's port skewed); qpdk_cpw_jpa (C9 geometry and the meander overlap noted under C9). Re-export these groups before their next solve.


## Causes

| id | cause | cells | status | fix lives in |
|---|---|---|---|---|
| C1 | Sim junction pads overlap / end on a curved island in a narrow gap | Flipmon, TransmonTaperedInsets | fixed | layouts/junctions/sim_gap.py; layouts/qubits/qpdk_cells.py; layouts/qubits/sqdmetal_cells.py |
| C1b | junction metal of a qubit that is in the box but not simulated touches its island at one point | Flipmon (neighbour in flipmon_test_chip) | fixed | sim_tools/builder.py |
| C2 | indium bump in a one-face simulation is a PEC pillar to the top of the box | AirbridgeMultiFace, Flipmon | fixed | sim_tools/builder.py |
| C3 | junction sub-cell simulated on its own | Manhattan, ManhattanSingleJunction, NoSquid, QuantcoreJunction, QuantcoreSquid, Sim, SquidV0, SuperInductor, TrilayerJunction, TrilayerJunctionCompact, TrilayerJunctionHSQ, TrilayerSquid, TrilayerSquidHSQ | fixed | sim_tools/builder.py (is_junction_cell, _is_qubit, build_simulation); sim_tools/subset.py (has_junction) |
| C4 | galvanic lead port shorted to ground / leaving the box | LumpedJpa, TwoPadTransmon | fixed | sim_tools/builder.py (lead_open_ends, galvanic_routes, build_simulation) |
| C5 | Metal-wrapped junction pins off the metal edges (stand-in sheet is wrong) | metal:SNAIL, metal:StarQubit | fixed | sim_tools/builder.py (FaceMetal, junction_gap, junction_sheet, sheet_junction_port) |
| C5b | metal-only Metal cell placed without its pocket | metal:TransmonConcentricType2, metal:TunableCoupler02 | context | — (design side) |
| C6 | eigenmode 50 Ω edge port without a polygon (box edge on a bend / taper / narrow line) | KiTwpaSerpentine, QubitResonator, SpiralLine, metal:LaunchpadWirebondDriven, metal:ReadoutResFC, metal:ResonatorCoilRect | fixed | sim_tools/builder.py (straighten_box, edge_port_ok, crossing_square) |
| C6b | eigenmode / driven 50 Ω edge port without a polygon where a straight line crosses the box edge at an angle | (designs: m53_wallraff_17q, demoqpu17, tutorial 03, xmonsdirectcoupling) | fixed | sim_tools/builder.py (line_port, line_port_ok, crossing_port, _route_spines, edge_midpoint_locations); sim_tools/geometry_check.py (check_port_lines) |
| C7 | C-matrix nets without a design label (warning) | CapacitiveXCoupler, JtwpaChain, SpiralResonatorPolygon | fixed | sim_tools/builder.py (_cell_probes, label_unnamed); layouts/others/amplifiers.py (JtwpaChain.qcc_probes) |
| C8 | GDS polygon with > 4095 points (XY record > 0x8000 bytes) | CoupledConnector, CoupledResonator, CpweQuarterWaveResonator, NeckTermination, QubitResonator | partly fixed | sim_tools/builder.py (FaceMetal.max_points, DesignSimulation.simplified_region, split_large_polygons); sim_tools/geometry_check.py |
| C9 | SquidTermination lead shorted to ground in the drawn cell (fab build too) | SquidTermination | fixed | layouts/others/amplifiers.py (SquidTermination.build) |
| C10 | route gap strip misses the cell's etch by < 1 nm at an angled / off-grid port (fab build) | ConcentricTransmon, CircularTransmonSingleIsland, metal:CapNInterdigitalTee, AirbridgeConnection (oblique), Xmon (claw off the grid) | fixed | route/waveguide.py (joined_nodes, misses_etch); layouts/chips/design_chip.py (DesignChip._join_ends); assembly/plan.py (RoutePlan.joins) |
| ctx | scratch-context routing fallback (not an export issue) | HyperbolicVertexCoupler, metal:ResonatorLumped | context | — |

## C1: FIXED — Sim junction pads overlap / end on a curved island in a narrow gap

The cell placed KQC's `Sim` junction with `junction_total_length = gap` and KQC's default 12 + 13 µm pads. In a gap below 25 µm (both cells' default: 20 µm) the pads overlap: the two islands are one conductor, the port points lie inside metal (KQC: `Unable to create polygon for port 1`; `narrow_junction_port` drew a stand-in) and the C-matrix lost an island. The pad also ended exactly on the island edge; on the curved Flipmon disc it touched the disc at one polygon vertex — KQC (`Region.interacting`) counted that as connected, Q3D's `AutoIdentifyNets` did not and stopped with `Object '1t1_signal_1_2' in Net 'Net1' and object '1t1_signal_1_3' in Net '1t1_signal_1_3' are touching` (build/test.json, 2026-11-15).

**Proposed fix:** Done: `layouts/junctions/sim_gap.py::sim_junction_in_gap` — the Sim pads reach 2 µm into the metal on both sides, keep KQC's 12/13 µm in the gap when that leaves ≥ 8 µm, else a centred min(8, gap/2) µm port; no background-gap box. Used by `Flipmon.build` (`layouts/qubits/qpdk_cells.py`) and `TransmonTaperedInsets.build` (`layouts/qubits/sqdmetal_cells.py`) for `junction_type == "Sim"` only (fab junctions and chip builds unchanged; floating_transmon's 100 µm gap exports bit-identically).

| cell | library | category | q3d_cmatrix export | hfss_eigenmode export | nets disjoint | junction port polygon | cause | scratch context |
|---|---|---|---|---|---|---|---|---|
| Flipmon | quantcore | qubit | ok (was: Q3D 'objects are touching' (point contact disc/pad), islands merged, no port polygon, bump to box top) | ok (was: islands merged, no port polygon, bump to box top) | yes (was: no) | ok (KQC polygon) (was: missing) | C1, C2 | pads + feedline + hanger readout from coupler |
| TransmonTaperedInsets | quantcore | qubit | ok (was: islands merged (pads overlap), no port polygon) | ok (was: islands merged (pads overlap), no port polygon) | yes | ok (KQC polygon) (was: missing) | C1 | pads + feedline + hanger readout from readout |

## C1b: FIXED — junction metal of a qubit that is in the box but not simulated touches its island at one point

Same contact, different cell instance: only the *selected* qubits get the Sim junction; a neighbour inside the box keeps its fab junction, and the Flipmon's trilayer CLEARER window (metal, `window_height` = the gap) ends on the curved disc at one vertex. Found in `examples/designs/qpdk/flipmon_test_chip.json` groups Q1R1 (neighbour Q2, contact at (3465.8, 4786.7)) and Q3R3 (neighbour Q4, (2235.8, 1413.3)) — the same Q3D "touching" error. Single-cell scratch designs have no neighbour, so no catalog row shows it.

**Proposed fix:** Done, generic: `sim_tools/builder.py::vertex_contact_patches` finds metal pieces that touch at a single point inside the box (KQC's view of the face: box − (gap − addition), min-coherence merge) and `DesignSimulation.build` adds a 0.5 µm `base_metal_addition` square on each contact (skipped if it would touch a third piece), so AEDT sees the one conductor KQC already assigned; recorded as `geometry.vertex_contacts_joined` + a note. Nets unchanged (KQC had already joined them). In the audit it fires only on metal:StarQubit (one pinch point in the star at (5000, 6625), same nets before and after); no-op on floating_transmon, 2_transmons_wres_comp, gatemon_test_chip, q1_r1_feedline.

## C2: FIXED — indium bump in a one-face simulation is a PEC pillar to the top of the box

The PDK simulates one face (`1t1`). With no opposite face KQC extends an `indium_bump` from the face to the top of the domain (0–1000 µm PEC). On the Flipmon it hung off island2: shorted to the outer boundary in HFSS, a 1 mm pillar's capacitance in Q3D.

**Proposed fix:** Done: `sim_tools/builder.py::strip_layers(bumps=False)` drops `*indium_bump` when the simulation face stack has one face; `build_simulation` records `geometry.indium_bump_shapes` and a note.

| cell | library | category | q3d_cmatrix export | hfss_eigenmode export | nets disjoint | junction port polygon | cause | scratch context |
|---|---|---|---|---|---|---|---|---|
| AirbridgeMultiFace | kqc | airbridge | ok | ok | yes | – (no junction port) | C2 | inline between two pads (a → b) |
| Flipmon | quantcore | qubit | ok (was: Q3D 'objects are touching' (point contact disc/pad), islands merged, no port polygon, bump to box top) | ok (was: islands merged, no port polygon, bump to box top) | yes (was: no) | ok (KQC polygon) (was: missing) | C1, C2 | pads + feedline + hanger readout from coupler |

## C3: FIXED — junction sub-cell simulated on its own

**Root cause:** junction cells take `junction_type`, so `builder._is_qubit` and `subset.has_junction` (its LOM model has a JJ) called them qubits; placed alone, their junction port had both ends on the ground plane (shorted), and NoSquid's eigenmode export demanded `instances.X.junction.Lj_nH`.

**Fix (done):** `sim_tools/builder.py::is_junction_cell` — KQC `Junction` subclasses, Quantcore trilayer cells, Metal category `junction` (metal:SNAIL, …). `_is_qubit` and `subset.has_junction` return False for them (so the GUI's qubit list, the subset planner and `guiflow.resolve_selection` no longer offer a lone junction as a qubit). In `build_simulation` a selected junction cell gets a junction port only where it bridges two different conductors on its axis (`junction_gap`; a code-built layout with the junction between two islands drawn by other cells keeps working); otherwise no port, no L_J needed, and a note: "junction cell … does not bridge two conductors here … simulate the qubit that contains it". Junctions inside qubits are untouched (the qubit cell is not a junction cell; its port follows the old path). All 13 cells: both analyses export with no check error (NoSquid eigenmode used to fail). Junction cells stay in the library (`examples/designs/legacy/chip_10a_3x_squid.json` places a TrilayerSquidHSQ alone: its whole-chip export now has no shorted port).

| cell | library | category | q3d_cmatrix export | hfss_eigenmode export | scratch context (now) |
|---|---|---|---|---|---|
| Manhattan | kqc | junction | ok (was: **check failed**: junction shorted (both ends on one net)) | ok (was: **check failed**: junction shorted (both ends on one net)) | alone (was: pads + feedline, no readout) |
| ManhattanSingleJunction | kqc | junction | ok (was: **check failed**: junction shorted (both ends on one net)) | ok (was: **check failed**: junction shorted (both ends on one net)) | alone (was: pads + feedline, no readout) |
| NoSquid | kqc | junction | ok (was: **check failed**: junction shorted (both ends on one net)) | ok (was: **failed**: ValueError: X: eigenmode analysis needs instances.X.junction.Lj_nH) | alone |
| QuantcoreJunction | quantcore | junction | ok (was: **check failed**: junction shorted (both ends on one net)) | ok (was: **check failed**: junction shorted (both ends on one net)) | alone (was: pads + feedline, no readout) |
| QuantcoreSquid | quantcore | junction | ok (was: **check failed**: junction shorted (both ends on one net)) | ok (was: **check failed**: junction shorted (both ends on one net)) | alone (was: pads + feedline, no readout) |
| Sim | kqc | junction | ok (was: **check failed**: junction shorted (both ends on one net)) | ok (was: **check failed**: junction shorted (both ends on one net)) | alone (was: pads + feedline, no readout) |
| SquidV0 | quantcore | junction | ok (was: **check failed**: junction shorted (both ends on one net)) | ok (was: **check failed**: junction shorted (both ends on one net)) | alone (was: pads + feedline, no readout) |
| SuperInductor | kqc | junction | ok (was: **check failed**: junction shorted (both ends on one net)) | ok (was: **check failed**: junction shorted (both ends on one net)) | alone (was: pads + feedline, no readout) |
| TrilayerJunction | quantcore | junction | ok (was: **check failed**: junction shorted (both ends on one net)) | ok (was: **check failed**: junction shorted (both ends on one net)) | alone (was: pads + feedline, no readout) |
| TrilayerJunctionCompact | quantcore | junction | ok (was: **check failed**: junction shorted (both ends on one net)) | ok (was: **check failed**: junction shorted (both ends on one net)) | alone (was: pads + feedline, no readout) |
| TrilayerJunctionHSQ | quantcore | junction | ok (was: **check failed**: junction shorted (both ends on one net)) | ok (was: **check failed**: junction shorted (both ends on one net)) | alone (was: pads + feedline, no readout) |
| TrilayerSquid | quantcore | junction | ok (was: **check failed**: junction shorted (both ends on one net)) | ok (was: **check failed**: junction shorted (both ends on one net)) | alone (was: pads + feedline, no readout) |
| TrilayerSquidHSQ | quantcore | junction | ok (was: **check failed**: junction shorted (both ends on one net)) | ok (was: **check failed**: junction shorted (both ends on one net)) | alone (was: pads + feedline, no readout) |

## C4: FIXED — galvanic lead port shorted to ground / leaving the box

**Root cause:** TwoPadTransmon's leads end on its pocket edge, so an unrouted lead (`left`) joins its pad to the ground plane (in Q3D the whole ground plane became net `X.island1`); in the eigenmode box (the GUI selects the qubit alone) the galvanic readout from `right` / LumpedJpa's `signal` tap is a grounded λ/4 line (hanger short) that the builder did not terminate, so it reached the box edge and KQC made the island ground. Both cells are used for fab and stay as drawn.

**Fix (done, simulation only):** (1) `lead_open_ends` — an unconnected port of a simulated qubit whose *own* junction island runs through the port into the ground plane (the island piece reaches the box edge) gets an open end (`b` long, `a + 2b` wide) etched beyond it in the simulation cell (`geometry.lead_open_ends`, note); the fab layout keeps the lead on the pocket edge (tested). (2) `galvanic_routes` — a grounded line whose box crossing lies on a junction island is terminated at the box edge like any other line (eigenmode: 50 Ω lumped port, marked `floating` so KQC does not merge the island into ground; Q3D: an edge port), with a note. TwoPadTransmon: nets `X.island1`, `X.island2` in both analyses (eigenmode also the 50 Ω port on R); LumpedJpa eigenmode: `X.island` plus the 50 Ω port on R. The analysis metal stands in an open end at cut-route stub ports, so a coupler pad with a stub is not mistaken for ground.

| cell | library | category | q3d_cmatrix export | hfss_eigenmode export | scratch context (now) |
|---|---|---|---|---|---|
| LumpedJpa | quantcore | resonator | ok | ok (was: **check failed**: island joined to ground / box edge) | pads + feedline + hanger readout from signal |
| TwoPadTransmon | quantcore | qubit | ok (was: **check failed**: island joined to ground / box edge) | ok (was: **check failed**: island joined to ground / box edge) | pads + feedline + hanger readout from right |

## C5: FIXED — Metal-wrapped junction pins off the metal edges (stand-in sheet is wrong)

**Root cause:** the junction port was drawn from the raw pins. Where they are not on metal edges (StarQubit: the island pin sits between the two junction leads, 45 µm short of the island along the junction axis, the ground pin inside the ground), KQC found no edge and `narrow_junction_port`'s stand-in lay on metal (201 µm²) with no metal beyond its signal end. metal:SNAIL placed alone is a junction cell (C3).

**Fix (done):** when KQC would not find both edges (or for a junction cell), `junction_gap` walks the junction axis through the simulated metal (`FaceMetal`: box − (gap − addition), as KQC builds it) and takes the gap between two *different* conductors that overlaps the pins' span (nearest its middle) — so pins on the edges, inwards, overlapping into the metal or in a cut-out all work. The port's signal / ground points move onto those two edges (KQC then finds them: no log line), and `junction_sheet` draws the lumped sheet: a strip on the axis, 10 µm wide or narrower until no metal lies within 1 µm of its long sides, cut to the gap so its ends follow the metal edges (`sheet_junction_port`). Qubits whose pins KQC already handles keep the old path (bit-identical). A zero-length junction gets no port (note). metal:StarQubit: 75 µm sheet from the ground edge to the island between its leads, 10 µm wide, no check error. `examples/tutorials/designs/t03_demoqpu17.json` (whole chip, q3d_cmatrix): all 17 StarQubit ports now span 40 µm gaps, 68 errors → 0, and each junction port's net is its island (before, the islands were floating nets the ports did not touch).

| cell | library | category | q3d_cmatrix export | hfss_eigenmode export | scratch context (now) |
|---|---|---|---|---|---|
| metal:SNAIL | metal | junction | ok (was: **check failed**: no KQC junction polygon (stand-in sheet); metal under the junction sheet; junction shorted (both ends on one net)) | ok (was: **check failed**: no KQC junction polygon (stand-in sheet); metal under the junction sheet; junction shorted (both ends on one net)) | inline between two pads (a → b) (was: pads + feedline + hanger readout from a) |
| metal:StarQubit | metal | qubit | ok (was: **check failed**: no KQC junction polygon (stand-in sheet); metal under the junction sheet) | ok (was: **check failed**: no KQC junction polygon (stand-in sheet); metal under the junction sheet) | pads + feedline + hanger readout from pin_rdout |

## C5b: CONTEXT — metal-only Metal cell placed without its pocket

Unchanged and out of scope: alone on the ground plane the qubit is ground metal, so `junction_gap` finds no gap between two conductors and the port stays at the drawn pins (the note says so). Design-side: place them on a `metal:Rectangle` pocket with `subtract: true` (catalog note).

| cell | library | category | q3d_cmatrix export | hfss_eigenmode export | scratch context (now) |
|---|---|---|---|---|---|
| metal:TransmonConcentricType2 | metal | qubit | **check failed**: no KQC junction polygon (stand-in sheet); metal under the junction sheet; junction shorted (both ends on one net) | **check failed**: no KQC junction polygon (stand-in sheet); metal under the junction sheet; junction shorted (both ends on one net) | pads + feedline + hanger readout from pin1 |
| metal:TunableCoupler02 | metal | coupler | **check failed**: no KQC junction polygon (stand-in sheet); metal under the junction sheet; junction shorted (both ends on one net) (warn: stub port without polygon) | **check failed**: no KQC junction polygon (stand-in sheet); metal under the junction sheet; junction shorted (both ends on one net) | pads + feedline + hanger readout from pin1 |

## C6: FIXED — eigenmode 50 Ω edge port without a polygon (box edge on a bend / taper / narrow line)

**Root cause:** the eigenmode export terminates each line leaving the box with a lumped 50 Ω port 1 µm inside the edge (the line etched `a` long, `a + b` wide); where the edge cut the route in a bend, KQC found no metal edge and AEDT skipped the port; where the edge ran along a meander leg KQC found edges but the line was cut lengthwise.

**Fix (done):** `straighten_box` (eigenmode / driven): a crossing is good when KQC builds the port (`edge_port_ok`: both port points on a metal edge after the port etch) and the line crosses roughly square (`crossing_square`: one piece `a`…`a + b/2` wide across the port depth). Each box edge with a bad crossing moves out (up to max(margin, 2r + 30 µm), inside the chip) or in (up to margin / 2) by the smallest 2 µm step that removes it; a crossing that moves on to the neighbouring edge (a bend at the box corner) is fixed there in a second pass; the original box is kept if nothing improves. Note: "box edge(s) moved (…) so … leave the box on a straight section at 90°"; groups whose crossings were all good keep their box. All six cells pass. `t02_ibm_bowtie_5q` triangle_A / triangle_B eigenmode_epr: 0 errors (R_Q0 / R_Q3 had no polygon); R_Q1 / R_Q2 (triangle_B: R_Q2 / R_Q4) still leave the box along a meander leg — no straight section within reach, the note lists them; their ports have KQC polygons as before. Lines that leave the box diagonally over a long stretch have no square crossing within reach: that case is C6b below (e.g. `examples/designs/kqc/xmonsdirectcoupling.json` group `qubits` exported as eigenmode_epr: DL1–3 / FL1–3 had no port polygon; since C6b all 12 ports have one). A box search that finds nothing keeps the original box.

| cell | library | category | q3d_cmatrix export | hfss_eigenmode export | scratch context (now) |
|---|---|---|---|---|---|
| KiTwpaSerpentine | quantcore | waveguide | ok | ok (was: **check failed**: 50 Ω edge port without polygon (AEDT skips it)) | inline between two pads (a → b) |
| QubitResonator | quantcore | resonator | ok (was: ok (warn: > 4095-point GDS polygon)) | ok (was: **check failed**: 50 Ω edge port without polygon (AEDT skips it) (warn: > 4095-point GDS polygon)) | one pad into end |
| SpiralLine | quantcore | resonator | ok | ok (was: **check failed**: 50 Ω edge port without polygon (AEDT skips it)) | inline between two pads (a → b) |
| metal:LaunchpadWirebondDriven | metal | launcher | ok | ok (was: **check failed**: 50 Ω edge port without polygon (AEDT skips it)) | inline between two pads (tie → in) |
| metal:ReadoutResFC | metal | resonator | ok | ok (was: **check failed**: 50 Ω edge port without polygon (AEDT skips it)) | one pad into readout |
| metal:ResonatorCoilRect | metal | resonator | ok | ok (was: **check failed**: 50 Ω edge port without polygon (AEDT skips it)) | one pad into spiralPin |

## C6b: FIXED — 50 Ω edge port without a polygon where a straight line crosses the box at an angle

**Root cause:** the at-edge port cuts the line along the box normal: signal 1 µm inside the edge, ground `a` further
in, `a + b` wide. When a line crosses at an angle, that cut misses the conductor's edges (at 45° the ground point
lands in the gap). KQC then builds no polygon and AEDT skips the port, so the line is left open. `straighten_box`
moves axis-aligned edges, and that cannot square up a diagonal line. This was seen on the 45° surface-17 lattices:
m53 `D5_readout` (4 of 11 ports), demoqpu17 `Q12_readout` (7 of 10) and `Q33_readout` (3 of 11), and the same
groups in tutorial 03.

**Fix (done, 2026-11-18):**
- `crossing_port` keeps the at-edge port where it works and the line crosses square (`edge_port_ok` and
  `crossing_square`, both unchanged).
- Otherwise `line_port` follows the route's centre line from the box edge inwards. The centre lines are KQC's
  zero-width `waveguide_path` paths (`_route_spines`).
- If the line runs straight (segments within about 0.1°) through the port and `b` beyond it, and crosses within 80°
  of the edge's normal, the port sits on the line's own axis. The cut is `a + b` wide and `a − 2·over_etching`
  long, square to the line, with its corner nearest the box edge 1 µm inside. At 90° this is the at-edge geometry.
- The stub between the cut and the box edge stays metal, like the at-edge port's 1 µm stub.
- `line_port_ok` checks that KQC finds both edges and that the cut separates the stub (which reaches the box edge)
  from the line.
- A bend or a taper is still a bad crossing for `straighten_box`.
- KQC's polygon corners are the found edges' end points on the 1 nm grid, so on a slanted port the drawn points can
  miss the sheet by a fraction of a nm. The first AEDT render refused `FLNE_3`'s Lumped RLC: "Both endpoints of the
  directed line must lie on the boundary face" (the point was 1·10⁻⁵ µm outside). `edge_midpoint_locations` now
  exports the midpoints of KQC's signal and ground edges, and `geometry_check.check_port_lines` flags a point off its
  polygon.
- **Driven:** an angled crossing gets the same lumped 50 Ω port instead of a wave port, which needs the line normal
  to the box face. Its kind is `edge_lumped`; the signal is on the line, and the stub to the box wall is its
  reference.
- A note lists the ports and their angles.

**Results:**
- Square crossings export identically: 19 groups compared on box, every port field, notes and nets.
- Ports with a polygon after the fix: m53 11/11, demoqpu17 10/10 and 11/11, `xmonsdirectcoupling` `qubits` 12/12.
  `geometry_check` is clean on all of them.
- Rendering m53 `D5_readout` into AEDT 2024 R1 (no solve) gives 1 junction RLC and 10 × 50 Ω Lumped RLC, and
  `check_project` passes.
- Tests: `tests/test_sim_angled_ports.py`.

## C7: FIXED — C-matrix nets without a design label (warning)

**Root cause:** only ports and port-mapped LOM nodes were probed; JtwpaChain's inner islands, CapacitiveXCoupler's floating cross, and SpiralResonatorPolygon's line pieces (cut where its dropped airbridges cross) and enclosed ground had no probe.

**Fix (done):** cells may declare `qcc_probes(params) → {LOM node: (x, y)}` (cell frame, no geometry) — JtwpaChain does: `X.n1`…`X.n15`. Any conductor still unnamed gets a label from its component (`label_unnamed`): a piece of a selected cell's own line → the cell's LOM island when it has exactly one (`X.res#2`…), a piece of a route → the route (`L_E#2`), else `<cell>.floating[k]` (CapacitiveXCoupler: `X.floating`; JtwpaChain's four resonator coupling buses: `X.floating1…4`; SpiralResonatorPolygon's enclosed ground) — with a note (airbridges=True keeps the bridges). The read-back ignores labels that are not circuit nodes, with a note. **Found on the way, FIXED 2026-11-16 (fab, approved):** JtwpaChain's resonator coupling lead was drawn inside the trench etch, so in the fab layout each loading resonator's coupling bus was not connected to its chain island (`_resonator` added the lead only in the pocket/slot; `trench - metal` etched it away between the island and the trench wall). `JtwpaChain.build` now keeps the lead's metal (width `max(2·finger_width, 4)`) from the island through the trench (`layouts/others/amplifiers.py`); the buses are now part of `X.n<k>` and the export no longer names `X.floating1…4` (tests: `test_jtwpa_resonator_leads_join_their_islands`, `test_floating_conductors_get_design_labels`). Fab builds of all 105 example designs before / after: only `examples/designs/amplifiers/jtwpa_4wm.json` changes on this account (130/1: 2 688 µm² = 16 leads × 168 µm² more metal, i.e. less etch, between the islands and the trench walls).

| cell | library | category | q3d_cmatrix export | hfss_eigenmode export | scratch context (now) |
|---|---|---|---|---|---|
| CapacitiveXCoupler | kqc | coupler | ok (was: ok (warn: unlabelled nets)) | ok | inline between two pads (p11 → p21) (was: alone) |
| JtwpaChain | quantcore | waveguide | ok (was: ok (warn: unlabelled nets)) | ok | pads + feedline + hanger readout from a |
| SpiralResonatorPolygon | kqc | resonator | ok (was: ok (warn: unlabelled nets)) | ok | inline between two pads (a → b) |

## C8: PARTLY FIXED — GDS polygon with > 4095 points (XY record > 0x8000 bytes)

**Root cause:** long meanders / spirals keyhole 4100–5600 points into one ground or line polygon (in existing design groups up to 100 000 points, which KLayout's own GDS writer then cuts edge to edge at 8000); NeckTermination's ~1400 flux-trap holes do the same with no bends involved.

**Fix (done, simulation only):** when a metal or gap polygon of the box would exceed 4000 points, `DesignSimulation.simplified_region` (KQC's etch simplification, applied before every simulation layer is derived, so metal and gap stay consistent) also smooths the etch by at most 0.05 µm (`Region.smoothed`, horizontal / vertical edges kept): bends lose points, nothing moves more than 50 nm (`geometry.bends_simplified_um`, note). That is enough for every bend-dominated polygon (all five catalog cells: CoupledConnector, CoupledResonator, CpweQuarterWaveResonator, QubitResonator, metal:ReadoutResFC; 19 of the 33 affected example groups). A polygon still above the limit (holes, not bends) is, in HFSS jobs only, written to the GDS as pieces of the same conductor that overlap by 0.01 µm inside the original outline (`builder.split_large_gds_polygons`, called by `export._split_gds_records` after KQC built the port polygons from the whole outlines; `geometry.gds_polygons_split`). Q3D jobs keep such a polygon whole (warning stays), because Q3D's `AutoIdentifyNets` does not join overlapping pieces (render below). The checker now also scans the gap layers AEDT imports as mesh-seed sheets.

**AEDT check (import only, nothing solved; each in a new non-graphical AEDT 2024 R1 started by `qcc hfss render … --aedt batch --timeout 1200`, closed when done):** NeckTermination scratch design (`nk`, group `c`): hfss_eigenmode with the split — `ok import 73.8 s`, project saved, `boundary_types: {'Perfect E': 1, 'Lumped RLC': 1}`, the three ground pieces imported (≤ 1930 points each) and covered by PerfE1. q3d_cmatrix with the split — imported, but nets `Net1`, `1t1_signal_1_2`, `1t1_signal_1_3`: one conductor became three Q3D nets, hence no split for Q3D. q3d_cmatrix as exported now (bends simplified, no split: one 5614-point polygon, a GDS XY record of 44 912 bytes > 0x8000) — `ok import 251.4 s`, one object `1t1_signal_1_1`, one net `Net1`; the project's `NumVertices=3774` is exactly the record's 5614 points minus the two keyhole points of each of its 920 holes, so AEDT 2024 R1 reads records above 0x8000 bytes completely. The 4095-point limit is therefore not an AEDT import limit; the real hazard is a polygon above 8000 points, which KLayout's GDS writer cuts edge to edge (touching pieces — Q3D splits the net). Bend simplification removes those in every audited job and example group; the checker keeps warning above 4095 points, as decided.

**Not fixed (open):** polygons made of real features rather than bends stay large after the 0.05 µm simplification (0.2 µm would not help either: chip_07_resonators R2 13 898 → 9 168 points): in the sampled example groups ki_twpa_serpentine `launch` (the serpentine's signal net, 98 946 points), seven_qubit_processor `Q0R` (ground, 14 777 / 16 679), chip_07_resonators `R2` (ground, 13 549), m52_barends_5q, resonator_test_chip, vortex_neck_test_chip, resonator_chip_01, qm2litho_12q_flux_processor, tuokkola_near_ms_transmon (ground, 4 600–27 000). HFSS jobs write them as overlapping pieces (imports, see above). Q3D jobs keep them whole: up to 8000 points AEDT reads them (verified); above 8000 KLayout's writer cuts them edge to edge, as before this change — Q3D would make each piece of a signal net its own net (ki_twpa_serpentine `launch` q3d_cmatrix). A fix needs the pieces united inside AEDT after the import (`sim_tools/aedt_scripts.py`: `oEditor.Unite` on the pieces of one layer, then `AutoIdentifyNets` again), which was not attempted here.

| cell | library | category | q3d_cmatrix export | hfss_eigenmode export | scratch context (now) |
|---|---|---|---|---|---|
| CoupledConnector | quantcore | waveguide | ok (was: ok (warn: > 4095-point GDS polygon)) | ok (was: ok (warn: > 4095-point GDS polygon)) | inline between two pads (start → end) |
| CoupledResonator | quantcore | resonator | ok (was: ok (warn: > 4095-point GDS polygon)) | ok (was: ok (warn: > 4095-point GDS polygon)) | one pad into end |
| CpweQuarterWaveResonator | quantcore | resonator | ok (was: ok (warn: > 4095-point GDS polygon)) | ok (was: ok (warn: > 4095-point GDS polygon)) | alone |
| NeckTermination | quantcore | termination | ok (warn: > 4095-point GDS polygon) | ok (was: ok (warn: > 4095-point GDS polygon)) | one pad into o1 |
| QubitResonator | quantcore | resonator | ok (was: ok (warn: > 4095-point GDS polygon)) | ok (was: **check failed**: 50 Ω edge port without polygon (AEDT skips it) (warn: > 4095-point GDS polygon)) | one pad into end |

## C9: FIXED — SquidTermination lead shorted to ground in the drawn cell (fab build too)

**Root cause:** the 28 µm landing head is wider than the CPW's a + 2b = 22 µm and the pocket started at the lead end, so the head's back edge (x = lead_length, 11 < |y| < 14 µm) touched the ground beside the lead: the lead was shorted to ground and the SQUID bypassed (fab and simulation).

**Fix (done, fab geometry, approved):** when the head is wider than a + 2b, the pocket starts `b` before the head (x from lead_length − b) around the lead's centre conductor: two 6 × 6 µm etched strips (11 < |y| < 17 µm) beside the lead's last 6 µm; heads within the CPW width are unchanged. Without the junction gap the lead + head is now its own conductor (tested with No Squid and with the PDK SQUID); the sim export has the junction port between `X.island` (lead + head) and ground, no check error (Q3D: a warning that the island's net includes the λ/4 line the box cuts — a termination's island *is* the line end).

**Designs that change:** `examples/designs/amplifiers/qpdk_cpw_jpa.json` (ST: 69.3 µm² more etch on 130/1 = the two 36 µm² strips minus 2.7 µm² that was already etched there) and the `build/test.json` (ST1–ST3, not modified here: 216 µm² = 3 × 2 strips; that file currently fails validation because its `gui_sim` group still names the deleted F1 / R2 — the KLayout plugin's `scrub_references` drops them on the next edit). No other design uses SquidTermination (tests/test_amplifiers.py builds it from parameters). `qcc components SquidTermination` (ports a / pump / squid_a / squid_b, `--schema`, `--outline`) and a design with it alone or routed to a pad build and export cleanly; the reported "could not place it" was that stale sim group making every build of build/test.json fail validation, not the cell.

**Found on the way (not changed, fab, before and after):** in `examples/designs/amplifiers/qpdk_cpw_jpa.json` the `JPA` meander route's last turn (an arc from (3965.75, 3690) to (3905, 3755) µm) lies past the route's end node, over the SquidTermination: it etches the 2 µm ground strip between the SQUID pocket and the pump line (x 3936–3938 at y ≈ 3690–3761) and nicks the pump centre conductor near y ≈ 3700. In the `jpa` eigenmode export the SQUID's far side therefore lands on the pump line; the export now says so (junction port spans 3916 → 3944 µm, no clean sheet) where before it drew a stand-in whose ground end lay in etch. The q3d export cuts the JPA route and is unaffected. **FIXED 2026-11-16 (router, approved):** root cause — the route asks for `meanders: 6` on a 478.5 µm straight (3361.5 → 3840 µm), but KQC's `Meander` puts its first bend `r` after the straight's start and every turn takes 2·r along it, so it needs a straight of at least 2·r·(turns + 1) = 840 µm; on a shorter one the first / last bends run backwards past the straight's end nodes (here over the SquidTermination) and KQC only checks `l_direct < 4r`. `route/router.py` (`with_length_increment`, new `meander_span` / `max_meanders`) now cuts a requested number of turns to `int(span / 2r − 1)` (JPA: 6 → 2; the meander is wider, the length is the same 4 664 µm). Fab builds of all example designs before / after: only `qpdk_cpw_jpa.json` changes on this account (its JPA meander); no other example had a turn past its straight. Test: `tests/test_router.py::test_meander_stays_on_its_straight_when_too_many_turns_are_asked`. **Design follow-up 2026-11-16 (keep the compact shape):** `qpdk_cpw_jpa` JPA route r 60 → 30 µm, so six turns fit (2·30·7 = 420 ≤ 478.5 µm): 6 turns, 739 µm tall (2 turns at r = 60: 2142 µm), 4664 µm, no overlap with the SquidTermination or the pump line (M1 regions disjoint); the router warning is gone.

| cell | library | category | q3d_cmatrix export | hfss_eigenmode export | scratch context (now) |
|---|---|---|---|---|---|
| SquidTermination | quantcore | termination | ok (warn: island includes the cut line (Q3D)) (was: **check failed**: junction shorted (both ends on one net)) | ok (was: **check failed**: junction shorted (both ends on one net)) | one pad into a |

## C10: FIXED — route gap strip misses the cell's etch at an angled / off-grid port (fab build, 2026-11-17)

**Reported:** build/test.json, R2 from `CT1.coupler_2` (ConcentricTransmon at (2400, 1589), 60°, route a/b 10/6): in the fab mask a thin metal sliver with rounded ends between the route's gap strip and the qubit's pocket.

**Root cause:** the route's strips and the cell's etch meet along one line, but each is snapped to the 1 nm grid on its own. At an angled port, or an axis-aligned port half a grid step off (Xmon `claw_n` at y = ….4625 µm), they can miss by less than 1 nm. The build looks closed, but the merge keeps the strip a separate polygon behind a zero-width metal crack. `export_fab`'s corner rounding works per polygon: it rounds the strip's end corners (r = 0.25 × 6 µm) and the crack opens into two metal crescents per strip, 0.48 µm² each, up to 0.51 µm wide and 1.9 µm long (test.json, left strip). Port positions, `KQC_EXTRA_PORTS`, the oblique router and the meander are not involved. KQC's own `merge_layout_layers_on_face` hides this with a 4 nm merge tolerance. Quantcore's 1/0 export has no such tolerance.

**Fix (done, fab geometry, approved 2026-11-17):** the plan records each route end at a placed cell's port (`RoutePlan.joins`). `DesignChip` checks each one (`misses_etch`): a strip piece neither overlaps nor touches the cell's etch, yet the cell is etched within 10 nm behind it. Only such an end is redrawn `JOIN_SHIFT` = 10 nm into the cell, so the strips overlap the etch. The route's port refpoints stay on the cell's port, and the plan's route length is unchanged. Ends that already merge, and pins on solid metal (metal:StarQubit, metal:TransmonConcentricType2), are drawn exactly as before. Cell-to-cell snaps are not covered; none of the examples' snaps misses (m54_wallraff_cell has 7 oblique snaps). Test: `tests/test_oblique_join.py`.

**Designs that change** (all 105 examples fab-built before / after, 1/0 XOR without cheese and 3/0; 98 identical; raw-build XOR only at the moved ends):

| design | ends moved | fab 1/0 XOR (µm²) | build 1/0 XOR (µm²) |
|---|---|---|---|
| examples/designs/metal/m53_wallraff_17q.json | 20 (13 CapNInterdigitalTee, 7 AirbridgeConnection) | 0.638 | 0.438 |
| examples/tutorials/designs/t03_wallraff_17q.json | 22 (12, 10) | 0.358 | 0.336 |
| examples/designs/devicelayout/demoqpu17.json | 19 (12, 7) | 0.198 | 0.225 |
| examples/tutorials/designs/t03_demoqpu17.json | 19 (12, 7) | 0.198 | 0.225 |
| examples/two_qubit_synth.json | 2 Xmon claws (axis, off the grid) | 15.367 | 0.024 |
| examples/tutorials/designs/t04_two_qubit_user.json | 2 Xmon claws | 2.092 | 0.024 |
| examples/tutorials/designs/t04_two_qubit.json | 1 Xmon claw | 1.046 | 0.012 |

In the Xmon designs the fab change also reaches the Xmon's other corners: once the strip merges, that polygon's rounding radius changes. The build/test.json (not modified here) changes at CT1.coupler_2.

## ctx: CONTEXT — scratch-context routing fallback (not an export issue)

The router could not auto-route the inline context (ports at 120° / 45°), so the cell was exported with one pad only. Both cells are clean.

| cell | library | category | q3d_cmatrix export | hfss_eigenmode export | scratch context (now) |
|---|---|---|---|---|---|
| HyperbolicVertexCoupler | quantcore | coupler | ok | ok | one pad into o1 |
| metal:ResonatorLumped | metal | resonator | ok | ok | one pad into pin_east |

## Clean (all checks pass in both analyses, never in a cause above) — 68 cells

| cell | library | category | q3d_cmatrix export | hfss_eigenmode export | scratch context (now) |
|---|---|---|---|---|---|
| AirbridgeConnection | kqc | airbridge | ok | ok | inline between two pads (a → b) |
| AirbridgeRectangular | kqc | airbridge | ok | ok | inline between two pads (a → b) |
| BondPad | quantcore | launcher | ok | ok | one pad into a |
| CircularCapacitor | kqc | capacitor | ok | ok | inline between two pads (a → b) |
| CircularTransmonSingleIsland | kqc | qubit | ok | ok | pads + feedline + hanger readout from coupler_1 |
| ConcentricTransmon | kqc | qubit | ok | ok | pads + feedline + hanger readout from coupler_1 |
| ConnectorPad | quantcore | launcher | ok | ok | one pad into a |
| CpwResonator | quantcore | resonator | ok | ok | inline between two pads (start → end) |
| CpwSegment | quantcore | waveguide | ok | ok | inline between two pads (a → b) |
| CpweBondPad | quantcore | launcher | ok | ok | one pad into a |
| CpweFingerCapacitor | quantcore | capacitor | ok | ok | inline between two pads (a → b) |
| CpweFingerLine | quantcore | capacitor | ok | ok | inline between two pads (a → b) |
| CpweGapCapacitor | quantcore | capacitor | ok | ok | inline between two pads (a → b) |
| CpweMeanderLine | quantcore | waveguide | ok | ok | inline between two pads (a → b) |
| CpweOpenEnd | quantcore | termination | ok | ok | one pad into a |
| CpweTaper | quantcore | waveguide | ok | ok | inline between two pads (a → b) |
| DoublePads | kqc | qubit | ok | ok | pads + feedline + hanger readout from cplr |
| DoublePadsSplines | kqc | qubit | ok | ok | pads + feedline + hanger readout from cplr |
| FingerCapacitorSquare | kqc | capacitor | ok | ok | inline between two pads (a → b) |
| FingerCapacitorTaper | kqc | capacitor | ok | ok | inline between two pads (a → b) |
| FluxlineStandard | kqc | other | ok | ok | alone |
| FluxlineStraight | kqc | other | ok | ok | alone |
| Gatemon | quantcore | qubit | ok | ok | pads + feedline through a GatemonCoupler on the readout edge |
| GatemonCoupler | quantcore | coupler | ok | ok | inline between two pads (o1 → o2) |
| HangerResonator | kqc | resonator | ok | ok | inline between two pads (a → b) |
| Launcher | kqc | launcher | ok | ok | one pad into port |
| LauncherDC | kqc | launcher | ok | ok | alone |
| Meander | kqc | waveguide | ok | ok | inline between two pads (a → b) |
| PadCoupler | quantcore | coupler | ok | ok | inline between two pads (left → right) |
| QuarterWaveCpwResonator | kqc | resonator | ok | ok | inline between two pads (a → b) |
| SmoothCapacitor | kqc | capacitor | ok | ok | inline between two pads (a → b) |
| SmoothCapacitorSemicircle | quantcore | capacitor | ok | ok | inline between two pads (a → target) |
| SpiralCapacitor | kqc | capacitor | ok | ok | inline between two pads (a → b) |
| Swissmon | kqc | qubit | ok | ok | pads + feedline + hanger readout from cplr0 |
| TaperedPad | quantcore | test_structure | ok | ok | one pad into finger |
| WaveguideComposite | kqc | waveguide | ok | ok | inline between two pads (a → b) |
| WaveguideCoplanar | kqc | waveguide | ok | ok | inline between two pads (a → b) |
| WaveguideCoplanarCurved | kqc | waveguide | ok (was: not run) | ok (was: not run) | inline between two pads (a → b) |
| WaveguideCoplanarSplitter | kqc | waveguide | ok | ok | inline between two pads (a → b) |
| WaveguideCoplanarTaper | kqc | waveguide | ok | ok | inline between two pads (a → b) |
| Xmon | quantcore | qubit | ok | ok | pads + feedline + hanger readout from claw_n |
| metal:Airbridge | metal | airbridge | ok | ok | inline between two pads (a → b) |
| metal:BridgeFreeJunction | metal | junction | ok | ok | alone |
| metal:Cap3Interdigital | metal | capacitor | ok | ok | inline between two pads (a → b) |
| metal:CapFingerInFrame | metal | capacitor | ok | ok | inline between two pads (frame → finger) |
| metal:CapNInterdigital | metal | capacitor | ok | ok | inline between two pads (north_end → south_end) |
| metal:CapNInterdigitalTee | metal | coupler | ok | ok | inline between two pads (prime_start → prime_end) |
| metal:CoupledLineTee | metal | coupler | ok | ok | inline between two pads (prime_start → prime_end) |
| metal:LaunchpadWirebond | metal | launcher | ok | ok | one pad into tie |
| metal:LaunchpadWirebondCoupled | metal | launcher | ok | ok | one pad into tie |
| metal:LineTee | metal | coupler | ok | ok | inline between two pads (prime_start → prime_end) |
| metal:NSquareSpiral | metal | shape | ok | ok | one pad into spiralPin |
| metal:OpenToGround | metal | termination | ok | ok | one pad into open |
| metal:PolylineCPW | metal | waveguide | ok | ok | inline between two pads (start → end) |
| metal:SQUID_LOOP | metal | junction | ok | ok | alone |
| metal:ShortToGround | metal | termination | ok | ok | one pad into short |
| metal:TransmonConcentric | metal | qubit | ok | ok | pads + feedline + hanger readout from pin1 |
| metal:TransmonCross | metal | qubit | ok | ok | pads + feedline, no readout |
| metal:TransmonCrossFL | metal | qubit | ok | ok | pads + feedline, no readout |
| metal:TransmonInterdigitated | metal | qubit | ok | ok | pads + feedline + hanger readout from readout |
| metal:TransmonPocket | metal | qubit | ok | ok | pads + feedline, no readout |
| metal:TransmonPocket6 | metal | qubit | ok | ok | pads + feedline, no readout |
| metal:TransmonPocketCL | metal | qubit | ok | ok | pads + feedline, no readout |
| metal:TransmonPocketTeeth | metal | qubit | ok | ok | pads + feedline, no readout |
| metal:TransmonStar | metal | qubit | ok | ok | pads + feedline, no readout |
| metal:TunableCoupler01 | metal | coupler | ok | ok | pads + feedline, no readout |
| metal:jj_dolan | metal | junction | ok | ok | alone |
| metal:jj_manhattan | metal | junction | ok | ok | alone |

## Not audited (no port, no junction; markers, shapes, test structures) — 38 cells

AlignmentMarkers, BoundaryBox, CornerMarker, CrossMarker, DicingMarker, EbeamMarker, GlobalMarker, WaferMap75, JunctionGroundPad, JunctionTestPads, ProbePadPair, ArcPath, JJFingerBent, JJFingerStraight, SpiralPath, TextLabel, FluxHoleArray, FluxHoles (Quantcore); WaveguideCoplanarStraight, ChipFrame, MarkerStandard, MaskMarkerFc, AirbridgeDC, CrossTest, JunctionTestPadsSimple, StripesTest, StripesTestIncreasingWidth, TsvTestPattern, FlipChipConnectorDc, FlipChipConnectorRf, TsvStandard (KQC); metal:CircleCaterpillar, metal:CircleRaster, metal:NGon, metal:Rectangle, metal:RectangleHollow, metal:SmileyFace, metal:MyQComponent (Metal).

Note: the KQC flip-chip connectors carry indium bumps; with C2 a one-face export drops them (the second face is not simulated).
