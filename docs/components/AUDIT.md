# Component migration audit

Independent check of the component migration (KQCircuits, Quantum Metal, legacy QWri) by an independent audit,
2026-11-03 (cloud VM, 01:59–02:40 UTC). Nothing here is taken from `scripts/make_catalog.py` or
`docs/components/MIGRATION.md`: every number comes from the audit's own scripts in `build/audit/`, which use only
library APIs (`layouts.catalog`, `registry.create_cell` / `element_cell_ports`, `assembly.builder.build`,
`wafers.fab_export.fab_regions`, `lom.fragment.lom_model`) and the read-only legacy harness `tests/legacy_ref/`.

Re-run (venv, `QCC_LIVE=0 MPLBACKEND=Agg`), about 2 minutes in total:

```bash
python build/audit/coverage.py          # inventory -> catalog, legacy PCells / helper calls -> cells (coverage.json)
python build/audit/build_ports.py       # build + port probes + layers + renders (build_ports.json, cells/*.png)
python build/audit/design_junctions.py  # connection continuity in the 19 built example designs
python build/audit/lom_check.py         # LOM models on default instances (lom_check.json)
python -m pytest -q tests/test_golden_legacy*.py --junitxml=build/audit/golden.xml
python build/audit/summarize.py && python build/audit/legacy_files.py   # summary.json, legacy_files.json
python build/audit/montage.py           # montages/*.png
```

## Counts

### How each number is obtained

* **inventory**: `docs/components/inventory.json` (5 Quantcore, 69 KQC, 48 Metal items, 78 legacy files).
* **migrated**: the item's `ref` is in `catalog(chips=True, routes=True)` and resolves to a cell. The 6 Metal routes
  are counted as migrated because `resolve_cell` refuses them with the qcc route to use (`build/audit/metal_routes.json`).
* **verified**, per catalog cell, over the defaults **and** the real parameter sets (215 builds of 154 cells; sets
  taken from the instances in `examples/designs/*/*.json` and from legacy chip calls, listed in
  `build_ports.py::EXTRA_SETS`):
  1. it builds (`create_cell`; KLayout error cells raise);
  2. ports: the fab M1 etch is probed across every directed port (0.02–3 µm inside, 0.05/0.5 µm outside). A defect
     is (a) etch across the centre conductor just outside the port (a connecting route is cut), (b) drawn centre
     width ≠ declared `a` (> 2 %), (c) drawn gap narrower than declared `b`. A wider drawn gap is KQC ground padding
     and is not counted. Ports judged by eye as by design are listed in `summarize.py::ACCEPTED`;
  3. LOM: an electrical cell (electrical category, or any directed port) has a model whose nodes, ports and
     elements are consistent (`lom_check.py`). Plausibility findings are listed but do not fail the check;
  4. fab: the default instance leaves device geometry in the PDK v2 fab layers. A cell drawn only on layers the
     export drops, or an electrical cell with no M1 etch, counts as a gap.
  Metal routes count as verified on the mapping alone.
* **gaps**: inventory items that are not verified. The reasons are in `build/audit/summary.json` → `table[].gaps`.

### Per source and category

| source | category | inventory | migrated | verified | gaps |
|---|---|---|---|---|---|
| quantcore | chip | 1 | 1 | 1 | 0 |
| quantcore | junction | 2 | 2 | 2 | 0 |
| quantcore | launcher | 1 | 1 | 1 | 0 |
| quantcore | qubit | 1 | 1 | 0 | 1 |
| kqc | airbridge | 3 | 3 | 0 | 3 |
| kqc | capacitor | 5 | 5 | 5 | 0 |
| kqc | chip | 24 | 24 | 24 | 0 |
| kqc | coupler | 1 | 1 | 1 | 0 |
| kqc | flip_chip | 3 | 3 | 1 | 2 |
| kqc | junction | 5 | 5 | 5 | 0 |
| kqc | launcher | 2 | 2 | 2 | 0 |
| kqc | marker | 3 | 3 | 3 | 0 |
| kqc | other | 2 | 2 | 1 | 1 |
| kqc | qubit | 5 | 5 | 2 | 3 |
| kqc | resonator | 3 | 3 | 2 | 1 |
| kqc | test_structure | 6 | 6 | 5 | 1 |
| kqc | waveguide | 7 | 7 | 6 | 1 |
| metal | airbridge | 1 | 1 | 0 | 1 |
| metal | capacitor | 3 | 3 | 2 | 1 |
| metal | coupler | 5 | 5 | 3 | 2 |
| metal | junction | 5 | 5 | 5 | 0 |
| metal | launcher | 3 | 3 | 3 | 0 |
| metal | other | 1 | 1 | 1 | 0 |
| metal | qubit | 11 | 11 | 6 | 5 |
| metal | resonator | 3 | 3 | 1 | 2 |
| metal | shape | 7 | 7 | 6 | 1 |
| metal | termination | 2 | 2 | 2 | 0 |
| metal | waveguide (1 cell + 6 routes) | 7 | 7 | 7 | 0 |
| **quantcore (inventory)** | | **5** | **5** | **4** | **1** |
| **KQC** | | **69** | **69** | **57** | **12** |
| **Metal** | | **48** | **48** | **36** (30 of 42 cells + 6 routes) | **12** |

**All Quantcore cells** (43 cells; the inventory lists only 5): 43 build, **39 verified**. The 4 that are not
verified are Xmon (claw port width), CpwResonator (`end` port offset), and JunctionTestPads and JunctionGroundPad (the
legacy 3/0 is not reproduced).

**Legacy files (78)**: `build/audit/legacy_files.json`.

| status | files | how |
|---|---|---|
| ported | 42 | a Quantcore cell names the file or its PCell (in its docstring or module) and builds, and a golden test that runs the legacy code passes. 38 are matched automatically; 4 by hand from the test source: the 3 Cong cpwe macros via `test_cpwe_*`, and `xjc_*` via `test_trilayer_matches_legacy` / `test_xjc_v01_*` |
| └ verified | **34** | the cells also pass the port, LOM and fab checks |
| └ gaps | 8 | `CPWResonator.lym` (CpwResonator `end`), `xmon_cross.lym` and `xmon_handle.lym` (Xmon claw `b`), `testPad.py`, `testPad_AVAQUS.py`, `testPad_Nb_TL.py`, `testPad_Nb_TL_HSQ.py` and `xtp_testpads_TL_small.py` (explicit 3/0 not drawn) |
| design (chip scripts) | 16 | 12 have a rebuilt `examples/designs/legacy/*.json`. Pending: chip_08, chip_10a_3X, chip_10a_flux, chip_11f (chip_11m is counted as ported) |
| not migrated | 20 | 13 not a cell, 4 obsolete, 2 different process (microstrip), 1 superseded by the PDK die frame. Each was read; reasons are in `legacy_files.py::REASONS` |

Golden tests, re-run by the audit (`tests/test_golden_legacy*.py`): **158 passed, 0 failed**
(`build/audit/golden.{log,xml}`). The component migration's 182 also includes `tests/test_metal_components.py`.

### Legacy coverage: PCell classes and the helpers the chips call (`build/audit/coverage.json`)

* **PCell classes (23, in `pymacros/`)**: 19 are ported, each named by the docstring or module of its cell, with a
  passing golden test. The 4 others are not ported: `JJ_finger`, `JJ_finger_bottom_old` and `JJ_finger_negativeOLD`
  are obsolete, and `Circle` is KLayout's sample. All 8 PCells that the chips instantiate by display name are
  ported: Connector Pad (and Pad 2), Coplanar Waveguide, Coupled Resonator, JJ_finger Top/Bottom, Marker and Xmon Cross.
* **Helper functions called by chips and macros (28)**:
  * junction and test-pad creators (`junction_creator_HSQ`, `squid_creator_HSQ`, `xjc_*`, `testPad*`, `xtp_*`):
    ported, with golden tests;
  * `cpwe.b_pad`, `quarter_cap_coupled` and `term_open`: ported;
  * `cpwe.line` and `cpwe.arc`: replaced by qcc routes;
  * `draw.*` (make_cell, chip, text, ...): drawing utilities of the Cong macros, not cells;
  * `ustrip.*`: different process, used only by the Cong macros;
  * `die_creator.create_die`: e-beam marker and offsets ported, die frame superseded;
  * `chip_01_creator.create_chip`: a design (wafer_creator).
* **Needed by a chip but not portable**: `junction_creator.create_junction`, called by chip_01_creator, chip_02 and
  chip_03 (chip_04, chip_xxx_template and resonator_chip_01 import it without calling it). The module is not in
  `components/` or anywhere in the repo. **design decision**: which junction generation those chips used. The
  rebuilt JSONs currently use Squid V0 / Trilayer Junction (chip_01) and Trilayer Junction HSQ (chip_03).

### Where the audit disagrees with the component migration claims

| claim (components.md / MIGRATION.md) | audit finding |
|---|---|
| KQC 69/69 build, ports OK | 69/69 build; 12 KQC entries have port-width declarations that do not match the drawing, or produce nothing in the PDK v2 fab layers |
| Metal 42/42 cells build | 42/42 build, but 3 have no etch at all at defaults (empty in the negative mask), and 9 cells' pins are cut from their routes |
| Quantcore 43/43 | 43 build, 39 verified |
| legacy 42 ported / 16 designs / 20 not migrated | same split. 34 of the 42 are fully verified |
| 182 golden/port tests passed | 158 legacy golden tests re-run: all pass |
| every electrical KQC/Metal entry has a LOM model | true by category. With "has a directed port" as the test, metal:NSquareSpiral (shape, 1 pin) has no model |
| CPW-E cells build | yes: 8/8 build, golden pass, ports verified |
| new cells TrilayerJunctionCompact, JJFingerStraight/Bent, FluxHoles, TextLabel | all build, look right, golden pass |
| optional spacer gradient 51–53/0 | works on all 5 trilayer cells and through Xmon `junction_params`: three disjoint, nested, touching rings (`build/audit/spacer_gradient.json`). The geometry is still a design decision |

## Gap list (owner; **blocking** = blocks a legacy chip)

| # | gap | evidence | owner |
|---|---|---|---|
| 1 | **Blocking, d12 and d14.** Metal pins whose own gap continues past the pin over the full conductor width. The routes are cut off from the claws: d12 9/9 and d14 6/6 resonator routes have an open 6 µm etched bar at `Q*.a`. Affected cells: TransmonCross `a`, TransmonCrossFL `a`, TransmonInterdigitated (3 pins), TransmonPocketCL `Charge_Line`, TunableCoupler01 `Control`, CapFingerInFrame (2), ResonatorCoilRect `spiralPin` | `design_junctions.json`, `zoom/m2_metal_claw_cut.png`, `build_ports.json` | components (Metal wrapper) |
| 2 | Xmon `qcc_port_widths`: claw tail `b` is declared as the element `b` (6), but `claw_spacing` is drawn (2 at defaults) | `build_ports.json` Xmon, `zoom/m4.png` | components |
| 3 | CpwResonator `end` port is 11 µm beyond the CPW end (`start` sits exactly at the CPW start) | `zoom/m9_quantcore_ports.png` | components |
| 4 | KQC port widths reported as the element a/b but drawn differently: WaveguideCoplanarTaper `b`, AirbridgeConnection `b`, FluxlineStraight `flux`, QuarterWaveCpwResonator `resonator_b`, Swissmon `cplr*`, CircularTransmonSingleIsland / ConcentricTransmon `coupler_2/3` | `summary.json` | components (KQC width hooks) |
| 5 | metal:TransmonConcentricType2, metal:TunableCoupler02 and metal:ResonatorLumped: no etch at defaults (Metal's mm-scale defaults, metal only) | `cells/metal_TransmonConcentricType2__0.png` | components (catalog note); lom (models describe nothing drawn) |
| 6 | Legacy 3/0 is not reproduced. `qcc mask` 3/0 is 1/0 grown by 5 µm; legacy 3/0 is per cell (resonator ≈ +6 µm, Xmon Cross much larger, pads none, test pads an explicit second-metal pattern: XOR 0.43 of 0.45 mm²) | `legacy_m3.json`, `testpad_m3.json` | **design decision** (`pdk/`); affects test chips 04/06/08/11m |
| 7 | PDK v2 has no airbridge, SIS_shadow, 2b1-face or TSV layers. `qcc mask` drops them silently (KQC replicas: qualityfactor 130 airbridge pads) | `designs_lost_layers.json`; `NOT_EXPORTED` in `build_ports.json` | **design decision**; lead (a warning in `export_fab`) |
| 8 | Metal and KQC junctions are 2/0 footprints, not trilayer junctions (2/0 + 4/0 + 50/0) | `build_ports.json` fab; `montages/metal_junction_0.png`, `montages/kqc_junction_0.png` | **design decision** (substitute a Quantcore trilayer junction for fab) |
| 9 | `junction_creator` is missing (chips 01/02/03) | `coverage.json` → `missing_modules` | **design decision** |
| 10 | Golden test of TrilayerJunction/TrilayerSquid only at js = 1 with no second finger, while chip_10a uses js 5/8 with second finger 0.6 | `tests/test_golden_legacy.py::test_trilayer_matches_legacy` | components (tests) |
| 11 | metal:NSquareSpiral: a pin, no LOM model, empty in the mask; metal:Airbridge: only on airbridge_flyover (dropped) | `lom_check.json`, `build_ports.json` | components / lom (low) |
| 12 | Docs: the Xmon and BondPad docstrings do not name their legacy origin. CoupledResonator, QubitResonator and CoupledConnector `end` are open ends with the gap cap beyond the port; document it. TwoPadTransmon draws no junction (faithful to legacy `Transmon.lym`, 1/0 only) | `coverage.json` | components (low) |


### Resolved after the decisions (components-pdk, 2026-11-03; not re-audited)

| gap | decision | resolution |
|---|---|---|
| 2 | #22: the claw's gap should match the CPW gap | `Xmon.claw_tail_gap` (−1 = element `b`): the tail is drawn with that clearance and the port declares it; the claw body keeps `claw_spacing` |
| 6 | 3/0 = per-cell keep-out | `qcc_keepout(params)` hook on Xmon, the four legacy resonators, CpwSegment, ConnectorPad, BondPad, CornerMarker, JunctionTestPads, JunctionGroundPad: the legacy 3/0 shapes, golden-tested (`tests/test_keepout.py`); used by `fab_export.keepout_region` |
| 7 | #5: 300/0 airbridges, 700/0 TSV, 800/0+ flip-chip | layers mapped by the lead in `pdk`; cells draw KQC `airbridge_*`, `through_silicon_via`, face-2b1 layers. The gatemon's process layers are drawn on proposed 600–604/0 (no fab numbers) |
| 8 | #6 / #21: trilayer junctions | `junction_type: "Quantcore Junction"` / `"Quantcore Squid"` on Xmon, KQC qubits and `metal:<Class>` qubits (fingers 2/0 + 4/0, spacer 50/0 + 51–53/0, CLEARER), sized by the PDK rule (`pdk.JunctionProcess`, `circuit.bridges.size_junction`) |
| — | #4: spacer gradient = three dose levels | 51–53/0 drawn inside the 50/0 spacer (width / 3 strips; rings for windows / concentric spacers), on by default |

## LOM (check 3)

`build/audit/lom_check.json`: 129 non-chip catalog cells, 93 electrical, 92 with a model (metal:NSquareSpiral has
none). On default instances (Lj 10 nH / Cj 2 fF for qubits and junctions) there are **no consistency errors**: every
routing port is mapped, element ends exist, there are no dead nodes, and every qubit has a JJ/SQUID on its
island(s). Plausibility (E_C from the island capacitance, with coupler nodes taken as ground):

* Xmon: E_C 280 MHz (C_Σ 69 fF). Metal TransmonPocket and its variants: 406–446 MHz (C_Σ 43–48 fF). The other
  KQC and Metal transmons: 88–326 MHz (StarQubit 96, TransmonInterdigitated 88).
* Out of range:
  * TwoPadTransmon: 2.9 GHz. Its pads are tiny (5.9 fF) and its note says the leads set C_Σ.
  * metal:TransmonConcentricType2: 24 MHz (C_12 740 fF, rough). The cell is empty (gap 5).
  * metal:ResonatorLumped: 0.45 GHz (a λ/4 of 69.8 mm of trace). The cell is empty.
  * KQC HangerResonator and QuarterWaveCpwResonator: 63 and 32 GHz at their 1000 µm KQC default length. This is
    expected.

## PDK v2 layers (check 4)

At cell level (`build_ports.json` → `layers`/`fab`) and in fab output (`qcc mask` of chip_01, chip_04, chip_05 and
d14 → `build/audit/mask/*.oas`, layer list `build/audit/mask/layers.json`):

* The masks contain only PDK v2 layers: 1/0, 2/0, 3/0, 4/0, 50/0 (chip_05), 100/0, 1000/0 and 1001/0.
* **Junction fingers** are on 2/0 (SIS_junction) and 4/0 (SIS_junction_2) in every Quantcore trilayer cell, in Xmon
  and in the test pads.
* **Spacer** is on 50/0 in all 5 HSQ trilayer cells, Xmon, JunctionTestPads and the HSQ CornerMarker. Nothing is on
  500/0 except the wafer boundary of WaferMap75, which is correct for PDK v2.
* **150/0** is used only by CornerMarker (`hsq=True`), a legacy marker cell, and never appears in the fab output.
* **Markers**: AlignmentMarkers, CornerMarker, CrossMarker, EbeamMarker and GlobalMarker are on 1001/0; DicingMarker
  is on 1000/0; BoundaryBox is on 100/0; WaferMap75 is on 100/0, 500/0 and 501/0. The die frame puts 1000/0 and
  1001/0 on all 4 masks checked.
* The spacer gradient (51–53/0) appears only with `spacer_gradient=True` (`spacer_gradient.json`).
* For the layers the export drops, see gap 7; for 3/0, see gap 6.

## Snapshots (all looked at)

* Per-build renders (fab layers, ports as arrows with a/b bars; junction zoom where the junction is small):
  `build/audit/cells/<ref>__<set>.png`, 189 PNGs. Chips and WaferMap75 are not rendered.
  * Colours: metal = gold, 1/0 etch = dark grey, 2/0 = red, 4/0 = blue, 50/0 = green, 1000/1001 = orange/purple.
  * Cyan hatching marks shapes the fab export drops.
* Montages per source and category: `build/audit/montages/{quantcore,kqc,metal}_<category>_<k>.png` (40), with
  the combined views `_qc_misc.png`, `_metal_{a,b,c}.png` and `_kqc_{a,b,c,d}.png`. Every Quantcore (legacy) cell
  and every set is in them.
* Port zooms: `build/audit/zoom/m4.png` (CoupledResonator end, TransmonCross a, Xmon claw, TwoPadTransmon),
  `zoom/m9_quantcore_ports.png` (9 legacy ports) and `zoom/m2_metal_claw_cut.png` (d12/d14 cut at chip level).

Visual flags:

* Empty cells: metal:TransmonConcentricType2, TunableCoupler02, ResonatorLumped, NSquareSpiral and the
  positive-metal Metal shapes (by design).
* Wrong polarity: none.
* Ports off the metal: CpwResonator `end`.
* Missing junctions: TwoPadTransmon (as in legacy), and Xmon "No Squid" (chosen in chip_01).

## Not verified

* The design-level correctness of the legacy chip rebuilds (owned by legacy-a and legacy-b). Only the connection
  continuity was probed: 0 cuts in the 10 legacy chip JSONs, 15 in d12/d14.
* That Metal's own renderer lets route metal fill pin gaps (gap 1). This was not run here.
* Metal port positions against Metal's own pin table (the audit uses the wrapper's ports).
* Solver-based LOM values: no FEM was run.
* KQC chips are built at defaults only; their ports are not probed.
