# Component duplicates and near-duplicates

Inventory of cells that draw the same structure or do the same job, within and across the three libraries of the
catalog (Quantcore, KQCircuits, Quantum Metal), for deciding what to remove, alias or keep. Written 2026-11-15
from the live catalog (`qcc components --json --details`): **144 components** (57 Quantcore, 45 KQC, 42 Metal).
The 25 whole KQC chips and the 6 Metal routes (already mapped to qcc routes) are not components and are left out.

**Updated 2026-11-16 with the decisions** (section [Decisions](#decisions-2026-11-15)):
`metal:MyQComponent` is removed from the catalog (143 components now), 11 cells are marked legacy, 11 alias groups
(15 aliased cells) are declared, and `CapacitiveXCoupler` / `WaveguideCoplanarCurved` have ports. No cell's
drawing changed. Every catalog entry is assigned to exactly one place: one group below, or the list of unique
cells at the end (coverage check in the last section). In the group tables, **key** marks a member that is used by an existing design *and*
simulation-compatible (LOM model and CPW ports).

## Key components

The members used by existing designs (`examples/`: legacy chips, tutorials, ported designs) **and**
simulation-compatible: a LOM model with circuit elements and at least one CPW (or edge) port, probed 0.02 µm
inside the port as in [How the checks were done](#how-the-checks-were-done). Ports "when configured" exist once the
connection pads / claws are set (Metal qubits have no connection pads at defaults). *Designs* counts design stems under
`examples/` (a design's .json, .ipynb and .py count once; build outputs left out) naming the ref, its `metal:` ref
or its `junction_type` string, recounted 2026-11-16. Junctions have no CPW ports by convention (`common` is the
junction lead); they enter a qubit through `junction_type`.

| Cell | Library | Category | LOM | Ports | Designs |
|---|---|---|---|---|---|
| `Xmon` | Quantcore | qubit | yes | `claw_n/e/w` CPW (one per claw) | 19 |
| `metal:TransmonPocket` | Metal | qubit | yes | connection pads CPW (when configured) | 15 |
| `metal:TransmonCrossFL` | Metal | qubit | yes | claws CPW (when configured), `flux_line` CPW | 12 |
| `metal:TransmonPocket6` (alias of TransmonPocket) | Metal | qubit | yes | connection pads CPW (when configured) | 11 |
| `metal:TransmonCross` | Metal | qubit | yes | claws CPW (when configured) | 10 |
| `Swissmon` | KQC | qubit | yes | `cplr0–2` CPW·wide, `flux` CPW | 7 |
| `DoublePads` | KQC | qubit | yes | `cplr` CPW·wide | 4 |
| `metal:TransmonPocketCL` | Metal | qubit | yes | pads CPW (when configured), `Charge_Line` CPW | 4 |
| `TransmonTaperedInsets` | Quantcore | qubit | yes | connection pads CPW (when configured) | 2 |
| `CircularTransmonSingleIsland` | KQC | qubit | yes | `coupler_1–3` CPW | 1 |
| `Flipmon` | Quantcore | qubit | yes | `coupler` CPW | 1 |
| `Gatemon` | Quantcore | qubit | yes | `gate` CPW (`readout` is the island edge, snapped to GatemonCoupler) | 1 |
| `TwoPadTransmon` | Quantcore | qubit | yes | `left`, `right` CPW·wide | 1 |
| `metal:TransmonConcentric` | Metal | qubit | yes | `pin1–3` CPW·wide | 1 |
| `metal:TransmonPocketTeeth` | Metal | qubit | yes | pads CPW (when configured) | 1 |
| `CoupledResonator` | Quantcore | resonator | yes | `end` CPW | 12 |
| `LumpedJpa` | Quantcore | resonator | yes | `signal` CPW | 2 |
| `QuarterWaveCpwResonator` | KQC | resonator | yes | `a`, `b`, `resonator_b` CPW | 1 |
| `metal:ReadoutResFC` | Metal | resonator | yes | `readout` CPW | 1 |
| `QuantcoreJunction` ("Quantcore Junction") | Quantcore | junction | yes | `common` (junction lead) | 44 |
| `QuantcoreSquid` ("Quantcore Squid") | Quantcore | junction | yes | `common` | 34 |
| `TrilayerSquid` (alias of QuantcoreSquid) | Quantcore | junction | yes | `common` | 7 |
| `TrilayerJunctionHSQ`, `TrilayerSquidHSQ`, `TrilayerJunctionCompact` | Quantcore | junction | yes | `common` | 2 each |
| `TrilayerJunction` (alias of QuantcoreJunction) | Quantcore | junction | yes | `common` | 1 |
| `metal:CapNInterdigitalTee` | Metal | coupler | yes | `prime_start`, `prime_end`, `second_end` CPW | 9 |
| `metal:CoupledLineTee` | Metal | coupler | yes | 3 × CPW | 5 |
| `metal:LineTee` (alias of WaveguideCoplanarSplitter) | Metal | coupler | yes | 3 × CPW | 4 |
| `GatemonCoupler` | Quantcore | coupler | yes | `o1`, `o2` CPW | 1 |
| `FingerCapacitorSquare` | KQC | capacitor | yes | `a`, `b` CPW·wide | 25 |
| `metal:CapNInterdigital` | Metal | capacitor | yes | `north_end`, `south_end` CPW | 3 |
| `FingerCapacitorTaper` | KQC | capacitor | yes | `a`, `b` CPW | 2 |
| `SmoothCapacitor` | KQC | capacitor | yes | `a`, `b` CPW·wide | 1 |
| `metal:Cap3Interdigital` | Metal | capacitor | yes | `a`, `b` CPW·wide | 1 |
| `BondPad` | Quantcore | launcher | yes | `a` CPW | 49 |
| `metal:LaunchpadWirebond` (alias of BondPad) | Metal | launcher | yes | `tie` CPW | 18 |
| `ConnectorPad` (alias of BondPad) | Quantcore | launcher | yes | `a` CPW | 9 |
| `metal:LaunchpadWirebondDriven` (alias of BondPad) | Metal | launcher | yes | `tie` CPW (`in`: the pad terminal) | 5 |
| `metal:LaunchpadWirebondCoupled` | Metal | launcher | yes | `tie` CPW | 4 |
| `CpweBondPad`, `Launcher` (aliases of BondPad) | Quantcore, KQC | launcher | yes | `a` / `port` CPW | 1 each |
| `metal:OpenToGround` (alias of CpweOpenEnd) | Metal | termination | yes | `open` edge | 8 |
| `metal:ShortToGround` | Metal | termination | yes | `short` (the route ends in ground; nothing drawn) | 2 |
| `CpweOpenEnd`, `NeckTermination`, `SquidTermination` | Quantcore | termination | yes | `a` edge / `o1` CPW·wide / `a`, `pump` CPW | 1 each |
| `CpwSegment` (alias of WaveguideCoplanar) | Quantcore | waveguide | yes | `a`, `b` CPW | 9 |
| `WaveguideCoplanarSplitter` | KQC | waveguide | yes | `a`, `b`, `c` CPW | 8 |
| `CpweTaper` (alias of WaveguideCoplanarTaper), `WaveguideCoplanarTaper` | Quantcore, KQC | waveguide | yes | `a`, `b` CPW | 1 each |
| `CpweMeanderLine`, `JtwpaChain`, `KiTwpaSerpentine`, `metal:PolylineCPW` | Quantcore, Metal | waveguide | yes | `a`, `b` (`start`, `end`) CPW | 1 each |

Also key, not tabled: the route-engine cells every route draws although no design names them (`WaveguideComposite`,
`WaveguideCoplanar`, `Meander`; `WaveguideCoplanarTaper` at a/b changes; `Launcher` as chip launchers), and
`AirbridgeConnection` (5 designs, CPW ports; airbridges are left as they are).

**Used but not simulation-compatible** (qubits, resonators, couplers first; all of them stay):

| Cell | Designs | Why |
|---|---|---|
| `metal:StarQubit` | 8 | `pin_cpl1–4`, `pin_rdout` sit on the coupler pads (75 µm wide, no CPW behind the pin) |
| `metal:TransmonInterdigitated` | 1 | `readout`, `bus1`, `bus2` no-CPW (the CPW is drawn beyond the pin) |
| `metal:TransmonConcentricType2`, `metal:TunableCoupler02`, `metal:ResonatorLumped` | 1 each | metal only (no pocket): ports are metal until placed on a pocket |
| `metal:TunableCoupler01` | 3 | `Flux` drawn 5 / 3 µm vs declared a 20 / b 12; `Control` no-CPW |
| `SpiralLine` | 1 | single-strip metal path: `a`, `b` are metal ends, not CPW |
| `SmoothCapacitorSemicircle` | 1 | `a` is a CPW end only with `lead_length` > 0; `target` is a placement reference |
| `CpweFingerLine` | 1 | the fingers reach both ports (the probe at the port sees a finger), LOM yes |
| `WaveguideCoplanarStraight` | 1 (608 instances) | no ports (placed by position); the WaveguideCoplanarCurved fix would apply, see [ports](#ports-capacitivexcoupler-and-waveguidecoplanarcurved) |

## Decisions (2026-11-15)

Implemented in `src/quantcore_circuits/layouts/catalog.py` (`EXCLUDED`, `LEGACY`, `ALIASES`; `Component.legacy`,
`alias_of`, `aliases`, all in `qcc components --json --details`) and `layouts/registry.py` (`KQC_EXTRA_PORTS`);
tests in `tests/test_catalog_decisions.py`. No class file moved (designs and the KLayout plugin resolve cells by
name), no drawing changed: five designs built before / after (a probe design with every touched cell,
`kqc/xmonsdirectcoupling`, `qpdk/resonator_test_chip`, `ibm/ibm_bowtie_5q`, `legacy/d12_coupled_chip`) are
identical on all 21 fab layers (XOR, 222/0 ignored), with the same design hashes.

**Removed from the catalog:** `metal:MyQComponent` (= `metal:Rectangle`, Metal's user template, unused). It is no
longer listed by `catalog()`, `find()`, `list_components()` or `qcc components`; `resolve_cell("metal:MyQComponent")`
still works (Metal provides it).

**Legacy** (still listed, still placeable; `legacy` = the reason, plain listing tag `(legacy)`):

| Cell | Reason (short) | New designs use |
|---|---|---|
| `SpiralPath` | legacy spiral.lym, SpiralLine's curve without ports / LOM | `SpiralLine` |
| `SquidV0` | pre-HSQ SQUID, no design since chip_01 moved to the PDK SQUID | `QuantcoreSquid` |
| `StripesTest` | = StripesTestIncreasingWidth(stripe_step 0) | `StripesTestIncreasingWidth` |
| `ManhattanSingleJunction` | KQC shadow-evaporation footprint, unused | `QuantcoreJunction` |
| `metal:SQUID_LOOP` | Metal 2/0 SQUID footprint without pins, unused | `QuantcoreSquid` |
| `metal:BridgeFreeJunction` | Metal 2/0 junction footprint without pins, unused | `QuantcoreJunction` |
| `DoublePadsSplines` | DoublePads with spline islands, unused | `DoublePads` |
| `metal:NSquareSpiral` | Metal sample shape, metal only, unused | `metal:ResonatorCoilRect` |
| `metal:Airbridge` | unused; routes draw AirbridgeRectangular | `AirbridgeRectangular` / route airbridges |
| `CapacitiveXCoupler` | KQC FEM test element, unused (now with ports and a LOM) | — |
| `WaveguideCoplanarCurved` | the arc piece of routes, unused as a cell (now with ports and a LOM) | a route |

**Aliases** (the adopted definition: the same kind of element with the same circuit, i.e. equivalent LOM models for
the same dimensions, drawn differently). A marker only: nothing is redirected, each ref keeps its geometry,
parameters and port names. `alias_of` = the group's canonical cell; `aliases` = the other members. Every member has
an equivalence test (`test_alias_shares_an_equivalent_circuit`: the LOM fragment, in the canonical's port names,
has the same nodes, element types and values and lines). No model needed adjusting: each pair already gave the same
circuit for the same dimensions.

| Canonical | Alias | Mapping (alias → canonical) | Group |
|---|---|---|---|
| `CpweOpenEnd` | `metal:OpenToGround` | termination_gap → length, width → a, gap → b; port open → a | G16 |
| `WaveguideCoplanarSplitter` | `metal:LineTee` | t_length → lengths [t, t, t], angles [0, 180, 270]; prime_end → a, prime_start → b, second_end → c | G20 |
| `WaveguideCoplanarTaper` | `CpweTaper` | taper_type 0: length → taper_length, a_end → a2, b_end → b2; ports a, b | G19 |
| `BondPad` | `metal:LaunchpadWirebond`, `metal:LaunchpadWirebondDriven` | the Launcher polygon + a 25 µm lead; Driven = Wirebond + pin `in` on the pad (same node); port tie → a | G15 (pair) |
| `BondPad` | `Launcher`, `ConnectorPad`, `CpweBondPad` | each the Launcher polygon with mapped parameters; all a 50 Ω port | G15 |
| `WaveguideCoplanar` | `CpwSegment` | length L → path [(−L/2, 0), (L/2, 0)]; ports a, b | G18 |
| `QuantcoreJunction` | `TrilayerJunction` | finger_width 0.5, second_finger_width 0.6, clearer | G4 |
| `QuantcoreSquid` | `TrilayerSquid` | finger_width 0.25, second_finger_width 0.6, clearer | G5 |
| `metal:TransmonPocket` | `metal:TransmonPocket6` | same options; Pocket6 pad_cpw_shift 5 µm, pocket_rise 65 µm for the same pad | G1 |
| `metal:TransmonCross` | `metal:TransmonStar` | num_points 4, arm_* → cross_*, junction_arm_index 3; claw arm_index | G2 |
| `FluxHoles` | `FluxHoleArray` | the array's centres as a list (no circuit elements) | G29 |
| `StripesTestIncreasingWidth` | `StripesTest` | stripe_step 0 (no circuit) | G25 |

The LaunchpadWirebond pair sits in the launch-pad group G15, whose members are all the KQC Launcher polygon
and all a 50 Ω port; `BondPad` is its canonical (the recommended pad). Not aliased although exact or near
duplicates: `TwoPadTransmon` / `PadCoupler` (a qubit vs a series capacitor: different circuits), `metal:PolylineCPW`
(its LOM ends a free end **open** while its drawing ends flush, i.e. shorted like CpwSegment: a model question for
the LOM owner, see below), `WaveguideCoplanarStraight` (no ports), `GatemonCoupler` (an extra coupling port), `Xmon`
vs `metal:TransmonCross` (own calibrated model, different claws), `metal:TransmonCrossFL` (adds a flux line and a
SQUID), `SpiralPath` (no model), `TrilayerJunctionHSQ` / `TrilayerSquidHSQ` (near duplicates only).

### Ports: CapacitiveXCoupler and WaveguideCoplanarCurved

Why they had none: KQC never calls `add_port` in either class. `WaveguideCoplanarCurved` is the arc piece that
`WaveguideCoplanar` inserts between straight segments (its origin is the arc centre, no refpoints at all);
`CapacitiveXCoupler` is a KQC FEM test element whose arm ends are refpoints `p11`, `p21`, `p31`, `p41` (KQC's own
`get_sim_ports` turns them into edge ports) but no `port_*` refpoints, which is what qcc reads.

Both can be derived reliably, so `registry.KQC_EXTRA_PORTS` (applied in `element_cell_ports`, the one place ports
are extracted; a `port_<name>` refpoint the cell itself draws wins) now gives them, as metadata only:

* `CapacitiveXCoupler`: `p11`..`p41` at the drawn refpoints, facing out along each arm (the arm's first segment,
  replayed from KQC's `build`: '+' variant S, E, N, W; 'x' variant the four corners, diagonal for a square box,
  along the longer side otherwise), a / b = the element's (the arms are drawn at the element CPW). LOM
  (`kqc_models.x_coupler_lom`): each arm couples through its FingerCapacitorSquare (FingerCapacitorSquare's analytic
  estimate, ≈ 4 fF at defaults) to the floating centre cross `c`; C to ground per arm and for the centre (CPW
  sections + half finger blocks, rough); `remove_capacitors`: one conductor.
* `WaveguideCoplanarCurved`: `a` at (r, 0), `b` at angle alpha, both facing out along the tangent. LOM
  (`kqc_models.waveguide_curved_lom`): a CPW line of r·|alpha| (as WaveguideCoplanar: a wire between connected
  ports, a stub with a free end).

Checked by tests: positions and directions for five X-coupler variants and three arcs, the drawn CPW 0.5 µm inside
each port equals the declared a / b and nothing is etched beyond it, `qcc components <Cell>` lists them, and a
design routes to both (pads → X-coupler arm, arm → arc → pad) and its LOM joins them.

`WaveguideCoplanarStraight` has the same gap (no ports; `airbridge_crossings` places 608 of them by position). The
same one-entry fix would give it `a` / `b`, but it would add 1 216 dangling ports to that design's DRC and LOM, so
it was left open.

## Summary

| | count |
|---|---|
| catalog entries | 144 (57 Quantcore · 45 KQC · 42 Metal) at the audit; 143 since metal:MyQComponent was removed |
| duplicate groups | **30**, covering **120** entries |
| unique entries (no duplicate) | **24** |
| entries no example design uses by name | 64 (29 of them are not named by any test either) |

**Exact geometric duplicates found** (XOR = 0 on the fab layers, checked; mapping of parameters given):

1. `TwoPadTransmon` = `PadCoupler` (PadCoupler is a subclass; only the LOM model and the junction differ).
2. `QuantcoreJunction` = `TrilayerJunction`(0.5 / 0.6 µm, CLEARER on); `QuantcoreSquid` = `TrilayerSquid`(0.25 / 0.6 µm, CLEARER on). This is by design: they are the PDK presets.
3. Straight CPW: `CpwSegment` = `WaveguideCoplanarStraight` = `WaveguideCoplanar` (2 nodes) = `metal:PolylineCPW` (straight) = the line of `GatemonCoupler` (shifted by L/2).
4. Open end: `CpweOpenEnd`(length L) = `metal:OpenToGround`(termination_gap L). This is also KQC `term2` on a waveguide and qcc's `FreeEnd.term`.
5. Launch pads: `BondPad` (square pad), `ConnectorPad` (square pad), `CpweBondPad` (linear taper) and `metal:LaunchpadWirebond` (apart from a 25 µm lead) are each the KQC `Launcher` polygon with mapped parameters, rotated. `metal:LaunchpadWirebondDriven` = `metal:LaunchpadWirebond`.
6. `metal:TransmonPocket` = `metal:TransmonPocket6` (at defaults, and with one connection pad once Pocket6's pad defaults are set to Pocket's).
7. Cross transmon body: `metal:TransmonCross` = `metal:TransmonStar`(4 arms) = the cross of `Xmon` without claws (arm 20, length 400, gap 20) on the M1 etch.
8. `metal:Rectangle` = `metal:MyQComponent`.
9. `FluxHoleArray` = `FluxHoles` (the same centres given as a list).
10. `StripesTest` = `StripesTestIncreasingWidth`(stripe_step 0).
11. `metal:LineTee` = `WaveguideCoplanarSplitter`(lengths 50/50/50, angles 0/180/270).

**Near duplicates** (checked): `CpweTaper` (linear) ≈ `WaveguideCoplanarTaper` (XOR 0.03 µm² of 565);
`SpiralPath` ≈ `SpiralLine` (archimedean; XOR 2.4 of 155 µm²); `TrilayerJunctionHSQ` ≈ `TrilayerJunction` with
mapped parameters (fingers XOR 0, spacer differs: its offset formula is different); `metal:TransmonCrossFL` =
`metal:TransmonCross` + its flux line (XOR 222 µm², the flux line only).

### Top recommendations

These are ordered by value against risk. Details and the risk of each are in the group tables. **Status
2026-11-16:** 1 done (removed); 2 and 3 done as *legacy markers* (every cell stays listed and placeable);
5 done as *alias markers* (no redirection; see [Decisions](#decisions-2026-11-15)); 4 and 6 open.

1. **Remove from the catalog, no risk:** `metal:MyQComponent`. It is an exact copy of `metal:Rectangle` (Metal's "EDIT HERE" user template). No design or test uses it. (G27)
2. **Deprecate (hide, keep the class for its golden test):**
   * `SpiralPath`: the same curve as `SpiralLine` archimedean, but with no ports and no LOM model; unused. (G14)
   * `SquidV0`: the pre-HSQ SQUID. No design uses it since chip_01 was rebuilt on the PDK `Quantcore Squid`. (G5)
3. **Hide unused KQC/Metal entries that duplicate a used cell or that cannot be wired.** The upstream classes stay resolvable by ref; only the catalog listing changes:
   * `StripesTest`: a subset of `StripesTestIncreasingWidth`. (G25)
   * `CapacitiveXCoupler`: no ports, a KQC FEM test element. (G9)
   * `WaveguideCoplanarCurved`: no ports; drawn inside every route anyway. (G18)
   * `metal:Airbridge`: unused; `AirbridgeRectangular` is what routes draw. (G21)
   * `metal:SQUID_LOOP`, `metal:BridgeFreeJunction`, `ManhattanSingleJunction`: unused 2/0-only footprints, not the trilayer process. (G6)
   * `DoublePadsSplines`: unused. (G1)
   * `metal:NSquareSpiral`: unused, metal only. (G14)
4. **Merge code, not refs (geometry stays identical, no design changes):** draw `FluxHoleArray` through `FluxHoles`. (G29)
5. **Used exact duplicates: keep for now, decide on aliases later.** Each needs an alias with parameter and port-name translation, and that changes cell names, LOM element names and sidecars:
   * `CpweOpenEnd` ↔ `metal:OpenToGround`: identical at every existing use, 6 µm. (G16)
   * `metal:LineTee` → `WaveguideCoplanarSplitter`. (G20)
   * `metal:LaunchpadWirebondDriven` → `metal:LaunchpadWirebond`. (G15)
   * `CpweTaper` (linear) → `WaveguideCoplanarTaper`. (G19)

   Do not alias `BondPad`, `ConnectorPad` or `CpwSegment` to KQC cells. They carry the legacy 3/0 keep-out and the
   lumped-port refpoints, and ConnectorPad's rounded mode (all 18 of its instances) has no KQC equivalent.
6. **Mark a canonical cell for new designs and leave the legacy ports for their golden tests:**
   * pads: `BondPad`
   * open and short ends: a route end `term`
   * straight CPW: a route
   * T-junction: `WaveguideCoplanarSplitter`
   * λ/4 resonators: a meander route with `HangerEnd`
   * junctions: `Quantcore Junction` / `Quantcore Squid`
   * frame: the PDK die frame

## How the checks were done

* **Geometry (`XOR`)**: each cell was built with `registry.create_cell`, the shapes were flattened per layer, and the
  pair was XORed with `klayout.db`. The layers compared are the M1 etch (`base_metal_gap_wo_grid`), metal
  (`base_metal_addition`), the junction layers 2/0 and 4/0 (`SIS_junction`, `SIS_junction_2`), the spacer 50–53/0
  and the airbridge, flip-chip and TSV layers. KQC bookkeeping layers (ground-grid avoidance, waveguide_path, ports,
  refpoints, EBL copy) were ignored. Parameters are the defaults unless a mapping is shown. Areas are in µm².
* **Ports (`probe`)**: each directed port of a default instance was probed. The drawn cross-section was measured
  0.02 µm inside and 0.05 µm outside the port. The labels:
  * **CPW**: centre = `a`, both gaps = `b`.
  * **CPW·wide**: centre = `a`, gaps wider than `b` (ground padding).
  * **edge**: the port sits on the element's own gap or finger box (in-line capacitors, open ends); a route continues outward.
  * **no-CPW**: directed, but no CPW gap pair is drawn at it (a placement point, a pad point, or the CPW drawn on the far side).
  * **metal**: positive metal, no pocket at defaults.
  * **undir**: no direction (junction `common`, `squid_a/b` simulation terminals).
  * **+cut**: etch crosses the conductor just beyond the port (a gap cap or window beyond it).
* **LOM**: from `lom.fragment.lom_model(ref)`, with the model function named where it matters.
* **Used by** counts design stems under `examples/`: the .json, .ipynb and .py of one design count once,
  generator modules such as `designs/legacy/_legacy.py` included. Cell refs, `metal:` refs and `junction_type`
  strings were searched. **Tests** counts the files in `tests/` that name the class or ref. Every entry is also
  covered by the catalog-wide parametrised tests (`test_catalog_contract.py`, the pin test in
  `test_metal_components.py`). No test hard-codes catalog counts. `build/*.qcc.json` sidecars agree with the
  sources and are not listed separately. **implicit** marks use through another cell: KQC sub-cells of routes and
  chips, KQC defaults, a `junction_type` string or the KLayout plugin.
* Tags in the text: **[XOR]** and **[probe]** were checked; **[code]** was read in the source; **[doc]** comes from
  the docstring; **[inferred]** was not checked.
* For KQC and Metal entries, *remove/hide* means taking them out of the qcc catalog listing (`catalog.py` lists
  every KQC element and Metal qlibrary class automatically; an exclusion list would be needed). The upstream class
  stays in `other-libs/` and resolvable by ref. For Quantcore cells, *remove* means deleting the class, which is
  safe only when nothing uses it. *Alias* means `resolve_cell` mapping an old ref onto another class with parameter
  and port translation. No alias mechanism exists today [code: `registry.resolve_cell`].

---

## Qubits

### G1 · Floating two-island transmon

Verdict: the same job with different drawings across libraries. The only exact pair is inside Metal (Pocket ⊂ Pocket6).

| Member | What differs (defaults) | Ports [probe] | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|---|
| Quantcore · `TwoPadTransmon` · qubit · **key** | legacy `Transmon.lym`: 20×30 µm pads, 10 µm gap, 10 µm leads, own pocket (270×80 µm; etch 3 500, metal 1 400). Drawing = `PadCoupler` (G11) [XOR 0] | left, right CPW·wide; squid_a/b undir | yes (`two_pad_transmon_lom`) | 1 design (`designs/metal/tut443_10x10_package`, 100 instances with Quantcore Junction); 5 test files | keep | — |
| KQC · `DoublePads` · qubit · **key** | two rounded 500×100 µm islands with tapers to the junction, built-in coupler, drive point; 905×805 µm | cplr CPW·wide; drive no-CPW | yes | 4 designs (kqc/munchqubits, qpdk/_qpdk, qpdk/filled_qubit_test_chip, qpdk/qubit_test_chip); 3 tests | keep | — |
| KQC · `DoublePadsSplines` · qubit | subclass of DoublePads with spline islands; XOR vs DoublePads 19 891 (islands only; junction layers XOR 0) [XOR] | as DoublePads | yes | unused (0 designs, 0 tests) | **legacy** (marked, still listed) | none found |
| Metal · `TransmonPocket` · qubit · **key** | 455×90 µm pads, 30 µm gap, 650×650 µm pocket; no connection pads at defaults | squid_a/b undir (pads only when configured) | yes (`_pocket_lom`) | 15 designs (metal a1–a3, a5, m51, m52, m54, tut13, tut222, iswap2/3, flipchip, component_examples, sqchip_em, sqdmetal/two_transmon); 3 tests | keep | — |
| Metal · `TransmonPocket6` · qubit · **key** | = TransmonPocket at defaults and with one +1/+1 pad when `pad_cpw_shift` 5 µm / `pocket_rise` 65 µm are set [XOR 0]; its own pad defaults (0 / 0) give XOR 4 316; adds the `loc_W` 0 positions (6 pads) | as Pocket | yes (same `_pocket_lom`) | 11 designs (IBM bowtie/falcon, a4, a7, seven_qubit, tuokkola, tutorials t02…) | keep; **alias of TransmonPocket** (marker) | a redirecting alias Pocket→Pocket6 would change connection-pad defaults in 15 designs |
| Metal · `TransmonPocketTeeth` · qubit · **key** | pocket with teeth pads; XOR vs Pocket 4 133 [XOR] | squid undir | yes | 1 design (metal/component_examples) | keep | — |
| Metal · `TransmonPocketCL` · qubit · **key** | Metal subclass of TransmonPocket + charge line [code] | Charge_Line CPW | yes | 4 designs (seven_qubit, a6, component_examples, m51) | keep | — |
| Metal · `TransmonInterdigitated` · qubit | interdigitated islands in a 1 510×1 510 µm pocket | readout, bus1, bus2 no-CPW (CPW drawn beyond the pin, nothing behind it) | yes | 1 design (component_examples) | keep | — |
| Quantcore · `TransmonTaperedInsets` · qubit · **key** | SQDMetal re-implementation: 800×110 µm tapered pads in a filleted 1 000×800 µm pocket | corner and pocket pins no-CPW (placement marks, catalog note); squid undir | yes | 2 designs (sqdmetal/2_transmons_wres_comp, floating_transmon); 3 tests | keep | — |

### G2 · Grounded cross / star transmon (Xmon family)

Verdict: the same structure (the cross body is identical across three cells) with different claws and couplers.

| Member | What differs (defaults) | Ports [probe] | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|---|
| Quantcore · `Xmon` · qubit · **key** | legacy `xmon_cross` / `xmon_handle`: cross 300 µm, arm 25, gap 25, claws (n), junction below the south arm (default `junction_type` "Trilayer Junction"), 3/0 keep-out hook. Cross body with `claws: []`, arm 20, length 400, gap 20 = `metal:TransmonCross` on M1 [XOR 0]. The claws were not compared | claw_n CPW | yes (`Xmon.qcc_lom`) | 19 designs (legacy chip_01/01_4x4/01_creator/02/03/05/10a, q1_r1_*, five/two_qubit_synth, tutorials t00/t04); 21 test files; kplugin | keep (canonical) | — |
| KQC · `Swissmon` · qubit · **key** | 4 arms of 150 µm, 3 coupler claws, flux line, drive point | cplr0–2 CPW·wide; flux CPW; drive undir | yes | 7 designs (kqc demo/demo_twoface/simple/singlexmons/shaping/xmonsdirectcoupling, devicelayout/singletransmon); 8 tests | keep | — |
| Metal · `TransmonCross` · qubit · **key** | cross only at defaults; Metal junction footprint on 2/0 (400 µm²) | squid undir (claws when configured) | yes | 10 designs (d12, d14, chip12 tutorials, component_examples, flipchip, qm2litho_6xmon, xmon_cap_sim, squadds); 5 tests | keep | — |
| Metal · `TransmonCrossFL` · qubit · **key** | Metal subclass: TransmonCross + flux line; XOR 222 µm² (the flux line) at defaults and with one claw [XOR] | flux_line CPW; squid undir | yes | 12 designs (google_tc, iswap2/3, a4, m52, d12, chip12 tutorials …) | keep | — |
| Metal · `TransmonStar` · qubit | N-arm generalisation of TransmonCross (6 arms at defaults); with `num_points` 4, `arm_length` 200 µm, `junction_arm_index` 3 = TransmonCross [XOR 0] | squid undir | yes | unused | keep; **alias of TransmonCross** (marker) | none (unused); do not alias TransmonCross to it (option names differ) |

### G3 · Circular / concentric transmon

Verdict: the same job with different drawings. No exact pair.

| Member | What differs (defaults) | Ports [probe] | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|---|
| KQC · `CircularTransmonSingleIsland` · qubit · **key** | one round island (r 120) in a round pocket, 3 arc couplers (non-Manhattan) | coupler_1–3 CPW; drive no-CPW | yes | 1 design (kqc/munchqubits) | keep | — |
| KQC · `ConcentricTransmon` · qubit | inner disc + outer ring (two islands), 3 couplers; XOR vs Circular 175 878 [XOR] | coupler_1–3 CPW; drive no-CPW | yes | unused (test_catalog) | keep | — |
| Quantcore · `TrilayerConcentricTransmon` · qubit | added 2026-11-17: the Quantcore copy of KQC `ConcentricTransmon` (same islands, couplers, ports, LOM branches) with the PDK trilayer junction (`junction_type` "Quantcore Squid", fingers 2/0 + 4/0, spacer 50/0, gradient 51–53/0, `junction_params`) instead of KQC's Manhattan SQUID; not an alias group (the junction differs) | = ConcentricTransmon | yes | new | keep | — |
| Metal · `StarQubit` · qubit | round island with up to 4 couplers + readout | pin_cpl1–4, pin_rdout no-CPW; squid undir | yes | 8 designs (surface17 / demoqpu17 / wallraff family, component_examples) | keep | — |
| Metal · `TransmonConcentric` · qubit · **key** | floating disc + ring in a pocket, 1.7×1.0 mm | pin1–3 CPW·wide | yes | 1 design (component_examples) | keep | — |
| Metal · `TransmonConcentricType2` · qubit | metal only, no pocket (empty in the negative mask alone; catalog note), mm-scale defaults (5.3×6.0 mm) | pin1–3 metal | yes (AUDIT: E_C 24 MHz, rough) | 1 design (metal/iswap1_concentric_direct) | keep | — |
| Quantcore · `Flipmon` · qubit · **key** | QPDK flip-chip: disc + ring on M1, top disc on face 2b1, indium bump; the flip-chip analogue of ConcentricTransmon | coupler CPW; squid undir | yes | 1 design (qpdk/flipmon_test_chip); 3 tests | keep | — |

## Junctions

### G4 · Trilayer single junction (Quantcore process)

Verdict: generations and presets of one structure. All use the same LOM (`junction_lom`); `common` is undirected
(junction convention).

| Member | What differs (defaults) | Used by | Rec. | Risk |
|---|---|---|---|---|
| Quantcore · `QuantcoreJunction` · junction · **key** | subclass of TrilayerJunction with the PDK fingers 0.5×0.6 µm and CLEARER on; = TrilayerJunction(0.5, 0.6, clearer) on 2/0, 4/0, 1/0 metal and 50–53/0 [XOR 0] | `junction_type` "Quantcore Junction" in 44 designs (349 instances); the PDK default; 3 tests | keep (canonical) | — |
| Quantcore · `TrilayerJunction` · junction · **key** | legacy `xjc_junction_TL_mod` (golden): 0.1 µm fingers, no CLEARER | 1 design (chip_10a_flux_tlqubits) + implicit (Xmon's default `junction_type`); 8 tests | keep; **alias of QuantcoreJunction** (marker) | — |
| Quantcore · `TrilayerJunctionHSQ` · junction · **key** | first HSQ generation (subclass). Fingers reproduced by TrilayerJunction(bent_finger_y −2, bent_shift 0, hsq_extra 0.1) [XOR 0 on 2/0, 4/0]; the spacer offset formula differs (50/0 XOR 0.10 of 0.08 µm²), so it is not a parameter subset | chip_03_trilayer, chip_05_flux_tlqubits (13 instances); golden test | keep | folding it into TrilayerJunction with a switch changes the golden-tested code |
| Quantcore · `TrilayerJunctionCompact` · junction · **key** | own build: 12×12 µm window, notches at the lead ends, 22×22 µm footprint | chip_11f_jjplacer, chip_11m_testjj16x_pads (17 instances); 3 tests | keep | — |

### G5 · Trilayer SQUID (Quantcore process)

| Member | What differs (defaults) | Used by | Rec. | Risk |
|---|---|---|---|---|
| Quantcore · `QuantcoreSquid` · junction · **key** | = TrilayerSquid(0.25, 0.6, clearer) [XOR 0]; the PDK SQUID | "Quantcore Squid" in 34 designs (180 instances); 5 tests; kplugin | keep (canonical) | — |
| Quantcore · `TrilayerSquid` · junction · **key** | legacy `xjc_squid_TL_mod` (golden) | 7 designs (chip_10a, q1_r1_*, five/two_qubit_synth); 7 tests | keep; **alias of QuantcoreSquid** (marker) | — |
| Quantcore · `TrilayerSquidHSQ` · junction · **key** | first HSQ generation; XOR vs TrilayerSquid: 2/0 14.1, 4/0 31.0 µm² [XOR]; separate `straight_pad_height` | chip_05_flux_tlqubits, chip_10a_3x_squid; golden test | keep | — |
| Quantcore · `SquidV0` · junction | pre-HSQ SQUID (no spacer), 18 µm windows | **no design** (chip_01 now uses Quantcore Squid; only its notebook text names "Squid V0"); golden tests `test_squid_v0_*` | **legacy** (marked; still listed and a junction_type choice, design decision) | low |

### G6 · Shadow-evaporation junction and SQUID footprints (KQC / Metal)

Verdict: the same job, different drawings; none is the Quantcore trilayer process. These are 2/0 footprints
(AUDIT gap 8; design decision: substitute the Quantcore trilayer cells).

| Member | What differs (defaults) | Ports | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|---|
| KQC · `Manhattan` · junction | Manhattan SQUID: 2/0 + SIS_shadow + 1/0 patch; the default `junction_type` of KQC qubits | common undir | yes (`junction_lom`) | no design (every KQC qubit instance in examples sets `junction_type`, checked); 6 tests | keep | — |
| KQC · `ManhattanSingleJunction` · junction | single-junction version; XOR vs Manhattan 275 on 2/0 | common undir | yes | unused | **legacy** (marked, still listed) | none |
| Metal · `jj_manhattan` · junction | 2/0 only, no pins | none | `_bare_junction` (modelled by the qubit) | 1 design (component_examples); 2 tests | keep | — |
| Metal · `jj_dolan` · junction | 2/0 only, no pins | none | `_bare_junction` | 1 design (component_examples) | keep | — |
| Metal · `SQUID_LOOP` · junction | 2/0 only, no pins | none | `_bare_junction` | unused | **legacy** (marked, still listed) | none |
| Metal · `BridgeFreeJunction` · junction | 2/0 only, no pins | none | `_bare_junction` | unused | **legacy** (marked, still listed) | none |

## Couplers

### G7 · Feedline tee couplers (Metal)

Verdict: the same job (tapping a resonator off a feedline at a T), different coupling. Related non-cells: qcc
route `HangerEnd` (a coupled-line hanger) and KQC `HangerResonator`'s coupling section (G12) [code/doc].

| Member | What differs | Ports [probe] | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|---|
| Metal · `CapNInterdigitalTee` · coupler · **key** | T with an interdigital capacitor on the branch (= LineTee + CapNInterdigital per its docstring [doc]) | prime_start, prime_end, second_end CPW | yes | 9 designs (surface17 / demoqpu17 / wallraff family, a4, a7, sqchip_em) | keep | — |
| Metal · `CoupledLineTee` · coupler · **key** | T whose branch runs parallel to the line (coupled-line hanger) | 3 × CPW | yes | 5 designs (metal a1–a4, m52) | keep | — |

### G8 · Tunable couplers (Metal)

Verdict: the same job, different designs (two papers).

| Member | What differs | Ports [probe] | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|---|
| Metal · `TunableCoupler01` · coupler | SQUID + interdigital capacitor to ground + coupler arm, 430×219 µm | Control no-CPW; **Flux: drawn 5 / 3 µm vs declared a 20 / b 12** (flag, not a duplicate issue); squid undir | yes | 3 designs (a4, component_examples, iswap3_xmon_tc) | keep | — |
| Metal · `TunableCoupler02` · coupler | metal only, mm-scale, empty in the mask alone (catalog note) | pin1, pin2, fbl metal | yes | 1 design (iswap2_pocket_tc); 2 tests | keep | — |

### G9 · Multi-port capacitive node

Verdict: the same job (one capacitive node shared by ≥ 3 lines), different drawings.

| Member | What differs | Ports [probe] | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|---|
| Quantcore · `HyperbolicVertexCoupler` · coupler | QPDK: a disk cut into q pins (q = 3 at defaults) | o1–o3 CPW (non-Manhattan) | yes | unused in designs; 3 tests | keep | — |
| KQC · `CapacitiveXCoupler` · coupler | "for testing FEM computations" [doc]; X-shaped finger coupler, 700×700 µm | was none; **p11–p41 CPW since 2026-11-16** (`registry.KQC_EXTRA_PORTS`: the arm ends) | yes (each arm → finger C → floating centre) | unused; test_catalog, test_catalog_decisions | **legacy** (marked, still listed) | none |

## Capacitors

### G10 · Series interdigital capacitor in a CPW

Verdict: the same job, different drawings. No pair is identical at defaults. All LOMs are π networks
(C_ab + C to ground) with different estimators.

| Member | What differs (defaults) | Ports [probe] | Used by | Rec. | Risk |
|---|---|---|---|---|---|
| Quantcore · `CpweFingerCapacitor` · capacitor | legacy `cpwe.finger_cap`: fingers share the centre width (no widening), 4 × 50 µm; 252×32 µm, etch 944 | a, b edge | unused in designs; 4 tests (golden, kplugin joins) | keep (golden) | — |
| KQC · `FingerCapacitorSquare` · capacitor · **key** | widened finger block with ground padding, 5 × 20 µm fingers; 273×87 µm, etch 4 351 | a, b CPW·wide | 25 designs (KQC demo family, qpdk test chips, IBM bowtie, surface17, amplifiers, tutorials) | keep (canonical) | — |
| KQC · `FingerCapacitorTaper` · capacitor · **key** | tapered finger block; 343×91 µm | a, b CPW | 2 designs (kqc/demo, demo_twoface) | keep | — |
| Metal · `CapNInterdigital` · capacitor · **key** | fingers between two vertical CPW leads (146 µm port to port); `finger_length` 0 gives a plain gap capacitor [doc] | north_end, south_end CPW | 3 designs (a4, a7, m52); 2 tests | keep | — |
| Metal · `Cap3Interdigital` · capacitor · **key** | 3-finger capacitor in a ground pocket; 80×355 µm | a, b CPW·wide | 1 design (a6_hackathon_2q) | keep | — |

### G11 · Series gap / shaped-gap capacitor

Verdict: the same job, different shapes. `PadCoupler`'s drawing is `TwoPadTransmon` (G1) [XOR 0].

| Member | What differs (defaults) | Ports [probe] | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|---|
| Quantcore · `CpweGapCapacitor` · capacitor | legacy `cpwe.gap_cap`: a 5 µm gap box across the CPW (110 µm²) | a, b edge | yes | unused in designs; 2 tests (golden) | keep (golden) | — |
| Quantcore · `PadCoupler` · coupler | legacy `coupler.lym`: two facing 20×30 µm pads = TwoPadTransmon without junction refpoints [XOR 0, subclass] | left, right CPW·wide | yes (`pad_coupler_lom`: series C) | unused in designs; 3 tests | keep (shares code already) | — |
| KQC · `CircularCapacitor` · capacitor | inner disc + outer arc electrode (180° sweep), 400×210 µm | a, b CPW | yes | unused | keep | — |
| KQC · `SmoothCapacitor` · capacitor · **key** | smooth (curved) finger capacitor | a, b CPW·wide | yes | 1 design (kqc/munchqubits) | keep | — |
| KQC · `SpiralCapacitor` · capacitor | spiral-shaped fingers (180° spiral angle) | a, b CPW | yes | unused | keep | — |
| Metal · `CapFingerInFrame` · capacitor | one finger inside a frame electrode, 272×275 µm | frame no-CPW; finger CPW·wide | yes | unused | keep | — |

## Resonators and meanders

### G12 · λ/4 CPW resonator with a built-in coupler

Verdict: the same job, different drawings. The qcc-native way to draw one is a meander route with a `HangerEnd`
or `FreeEnd(term)` (not a cell).

| Member | What differs (defaults) | Ports [probe] | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|---|
| Quantcore · `CoupledResonator` · resonator · **key** | legacy `CPW_Coupled_Resonator`: coupler on y = 0, shorted start, open tail | end CPW +cut (gap cap beyond the port with ground=True, catalog note) | yes | 13 designs (legacy chips 01–10a, resonator_chip_01, _legacy, _legacy_b); 3 tests | keep | — |
| Quantcore · `QubitResonator` · resonator | legacy `Qubit_Resonator`: same base class, mandatory tail, coupler variants; XOR vs CoupledResonator at defaults 27 827 [XOR] | end CPW +cut | yes | unused in designs; 4 tests (golden, keep-out, kplugin) | keep (golden) | — |
| Quantcore · `CpweQuarterWaveResonator` · resonator | legacy `cpwe.quarter_cap_coupled`: open coupler arm, taper, meander, short | **none** (placed by refpoints) | yes | unused in designs; 3 tests | keep (golden) | — |
| KQC · `QuarterWaveCpwResonator` · resonator · **key** | probe line + λ/4 with a coupler, optional airbridges | a, b, resonator_b CPW | yes | 1 design (kqc/qualityfactor) | keep | — |
| KQC · `HangerResonator` · resonator | coupling section + resonator, 4 ports | a, b, resonator_a, resonator_b CPW | yes | unused | keep | — |
| Metal · `ReadoutResFC` · resonator · **key** | flip-chip readout: circle pad + meander | readout CPW | yes | 1 design (metal/flipchip_qubit_resonator) | keep | — |

### G13 · Meandered CPW section

Verdict: the same structure (a meandered CPW between two ends), different meander algorithms and end conditions.

| Member | What differs | Ports [probe] | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|---|
| Quantcore · `CpwResonator` · resonator | legacy `CPWResonator.lym`: meander grounded at both ends | start, end CPW | yes | unused in designs; 4 tests (golden) | keep (golden) | — |
| Quantcore · `CoupledConnector` · waveguide | legacy `CoupledConnector`: meander from a shorted start; end open with a gap box (ground=False default) | start no-CPW (shorted); end edge +cut | yes | unused in designs; 2 tests (golden) | keep (golden) | — |
| Quantcore · `CpweMeanderLine` · waveguide · **key** | legacy `cpwe.meander_line` (with `lead` = `cpwe.quarter_wave`) | a, b CPW | yes | 1 design (legacy/ki_twpa_structures) | keep | — |
| KQC · `Meander` · waveguide | fixed-length meander between a and b | a, b CPW | yes | explicit 0; **implicit: every `type: "meander"` route** (`WaveguideComposite` inserts Meander [code: KQC source]); 2 tests | keep | cannot be removed (route engine) |

### G14 · Spiral line / spiral resonator

Verdict: same family. `SpiralPath` is the only near-duplicate.

| Member | What differs (defaults) | Ports [probe] | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|---|
| Quantcore · `SpiralLine` · resonator | legacy `draw.spiral`: archimedean, fermat or double fermat by angle; metal path | a, b metal | yes (open line of the drawn length) | 1 design (legacy/ki_twpa_structures); test_spirals | keep (canonical) | — |
| Quantcore · `SpiralPath` · shape | legacy `spiral.lym`: archimedean path from inner_r to outer_r, etched. ≈ SpiralLine archimedean with spiral_r = (width + spacing)/2π, start = inner_r/spiral_r, end = outer_r/spiral_r, rotated 180°: XOR 2.4 of 155 µm² [XOR] (point sampling and end) | none | **no** | unused in designs; 1 golden test | **legacy** (marked, still listed) → SpiralLine | low (not bit-identical, so keep the class for its golden test) |
| KQC · `SpiralResonatorPolygon` · resonator | CPW (not single-strip) polygon spiral resonator, 5 mm | a, b CPW | yes | unused; test_designer | keep | — |
| Metal · `ResonatorCoilRect` · resonator | rectangular spiral set by length | spiralPin no-CPW (1 / 0.6 µm) | yes | unused; 2 tests | keep | — |
| Metal · `NSquareSpiral` · shape | n-turn square spiral, metal only (no pocket; AUDIT gap 11); same job as ResonatorCoilRect [doc] | spiralPin metal | yes (rough) | unused; 1 test | **legacy** (marked, still listed) | none |

## Launchers and terminations

### G15 · Wire-bond launch pad (pad + taper to the CPW)

Verdict: **the same polygon.** Each square / linear member is the KQC `Launcher` with mapped parameters and a
rotation [XOR 0]. They differ in refpoints, keep-out, port frame and the non-linear modes. All LOMs are a 50 Ω port,
except Coupled (a pad coupled through a C).

| Member | Mapping to `Launcher` (s = pad length, l = taper, a_launcher, b_launcher, frame gap) | Ports [probe] | Used by | Rec. | Risk |
|---|---|---|---|---|---|
| Quantcore · `BondPad` · launcher · **key** | rounded=False: s = pad_height, l = taper_length, a_l = pad_width, b_l = frame gap = pad_gap, rotated 270° [XOR 0 at defaults; same polygon for any values, code]. Extras: refpoints pad_center / chip_edge / lumped_*, legacy 3/0 keep-out, rounded mode | a CPW | 49 designs (305 instances, all rounded=False): amplifiers, qpdk, google, ibm, devicelayout, legacy 07/09/10a, fem_loop, q1_r1_*, tutorials; 18 test files; kplugin | keep (canonical pad; canonical of the alias group) | an alias to Launcher would drop the keep-out and lumped refpoints |
| Quantcore · `ConnectorPad` · launcher · **key** | rounded=False: s = 300, l = 300, a_l = 275, b_l = b·pad_width/a (165), frame gap = pad_height (300), rot 270° [XOR 0]. Not expressible as BondPad (side gap ≠ back gap: XOR ≥ 81 675) [XOR]. **All 18 instances use rounded=True**, which has no Launcher/BondPad equivalent [code] | a CPW | 10 legacy designs (chip_01 … 10a, resonator_chip_01, _legacy, _legacy_b); 6 tests | keep; **alias of BondPad** (marker) | — |
| Quantcore · `CpweBondPad` · launcher · **key** | taper_type 0: s = pad_length, l = taper_length, a_l = pad_width, b_l = pad_gap, frame gap = end_length, rot 180° + shift [XOR 0]. Default and used taper_type 3 (exponential) differs (XOR 125 953) | a CPW | 1 design (legacy/ki_twpa_structures, 2 instances, taper 3); 3 tests | keep; **alias of BondPad** (marker) | — |
| KQC · `Launcher` · launcher · **key** | reference | port CPW | 1 design explicit (kqc/test_chips/sample_holder_test) + **implicit**: chip `launchers` in 11 KQC-family designs and the KQC chips; 3 tests | keep; **alias of BondPad** (marker) | cannot be removed (chip launchers) |
| Metal · `LaunchpadWirebond` · launcher · **key** | = Launcher(s 80, l 122, a_l 80, b_l 58, frame gap 58) rot 180° + a 25 µm CPW lead (XOR 300 = the lead) [XOR] | tie CPW | 18 designs (metal a1–a7, m51, m52, iswap1–3, community, xmon_cap_sim, squadds); 2 tests | keep; **alias of BondPad** (marker) | — |
| Metal · `LaunchpadWirebondDriven` · launcher · **key** | = LaunchpadWirebond [XOR 0] + pin `in` at the pad (lumped drive terminal). No design references `.in` (checked d12, d14, t01) | tie CPW; in no-CPW +cut | 5 designs (d12, d14, chip12 tutorials); 2 tests | keep; **alias of BondPad**, one group with LaunchpadWirebond (marker; pair) | low; LOM loses the `in` node; test `test_launchpad_driven_in_pin_keeps_its_pad_gap` |
| Metal · `LaunchpadWirebondCoupled` · launcher · **key** | pad coupled to the tie line through a gap (XOR vs LaunchpadWirebond 3 383) | tie CPW | 4 designs (a4, a5, component_examples, m51) | keep | — |

### G16 · Open CPW end

Verdict: **exact duplicate.** `CpweOpenEnd`(length L) = `metal:OpenToGround`(termination_gap L) [XOR 0 at L = 6
and 10 µm, default a/b]. This is also the KQC waveguide `term2` = L (XOR 132 µm² = this box) and the qcc
`FreeEnd.term`.

| Member | What differs | Ports [probe] | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|---|
| Quantcore · `CpweOpenEnd` · termination · **key** | default length 10 µm; **all 16 instances use 6 µm** | a edge | yes (open end) | 1 design (qpdk/resonator_test_chip); 2 tests (golden) | keep; **canonical of the alias group** with metal:OpenToGround (marker; pair). A redirecting alias either way is geometry-identical at every existing use [XOR at defaults; instance a/b not compared] | port name a vs open; an alias adds or removes the Metal import |
| Metal · `OpenToGround` · termination · **key** | default termination_gap 6 µm; all 29 instances at 6 µm | open edge | yes (open end) | 8 designs (google_tc ×2, d14, a5, component_examples, iswap1, iswap3, m52); 2 tests | keep; **alias of CpweOpenEnd** (marker) | — |

For new designs, prefer a route end `term` (no extra cell).

### G17 · Shorted CPW end

Verdict: the same job, different drawings. The qcc-native form is `FreeEnd.term` = 0.

| Member | What differs | Ports [probe] | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|---|
| Metal · `ShortToGround` · termination · **key** | draws nothing (a pin where the CPW meets ground) | short no-CPW | yes (short end) | 2 designs (flipchip_qubit_resonator, m54_wallraff_cell) | keep | — |
| Quantcore · `NeckTermination` · termination · **key** | QPDK: short through a taper + 2 µm neck in an etched window with vortex-trap holes | o1 CPW·wide | yes | 1 design (qpdk/vortex_neck_test_chip); 3 tests | keep | — |

## Waveguides

### G18 · Straight / polyline CPW

Verdict: **exact duplicate on M1.** `CpwSegment`(L), shifted by L/2 = `WaveguideCoplanarStraight`(l = L) =
`WaveguideCoplanar` (2 nodes) = `metal:PolylineCPW` (straight) = `GatemonCoupler`'s line [XOR 0 at 100, 200, 500 and
600 µm].

| Member | What differs | Ports [probe] | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|---|
| Quantcore · `CpwSegment` · waveguide · **key** | legacy `CPW.lym`: centred at the origin; `lc/rc_thickness` and `keepout_gap` only change the 3/0 keep-out [code] | a, b CPW | yes | 9 legacy designs (feedlines of chip_01 … 10a, resonator_chip_01); 3 tests | keep; **alias of WaveguideCoplanar** (marker) | a redirecting alias would lose the legacy 3/0 keep-out |
| KQC · `WaveguideCoplanar` · waveguide | polyline CPW; also draws waveguide_path / grid-avoidance bookkeeping | a, b CPW | yes | explicit 0; **implicit: every route** (inside WaveguideComposite) | keep | route engine |
| KQC · `WaveguideCoplanarStraight` · waveguide | bare straight segment, **no ports** | none | no elements | 1 design (kqc/test_chips/airbridge_crossings, 609 instances) | keep | — |
| KQC · `WaveguideCoplanarCurved` · waveguide | bare arc segment; had no ports | **a, b CPW since 2026-11-16** (`registry.KQC_EXTRA_PORTS`: the arc ends, tangent) | a line of r·\|alpha\| | explicit 0; implicit inside WaveguideCoplanar [code] | **legacy** (marked, still listed) | none |
| KQC · `WaveguideComposite` · waveguide | the qcc route engine (nodes, tapers, airbridges, meanders) | a, b CPW | yes | explicit 0; **implicit: every route** of every design | keep | route engine |
| Metal · `PolylineCPW` · waveguide · **key** | Metal polyline CPW | start, end CPW | yes | 1 design (metal/iswap1_concentric_direct); 1 test | keep (or migrate its one user to a route); not aliased: its LOM ends a free end open, its drawing ends flush | — |
| Quantcore · `GatemonCoupler` · coupler · **key** | line = CpwSegment(600) [XOR 0] + reference port `qubit` + LOM with the gatemon coupling C | o1, o2 CPW; qubit no-CPW (capacitive reference, catalog note) | yes | 1 design (qpdk/gatemon_test_chip); 3 tests | keep (pairs with Gatemon) | — |

### G19 · CPW taper

Verdict: **near duplicate.** The linear profile is the same: XOR 0.03 of 565 µm² for 10/6 → 20/12 over 31.4 µm (dbu
rounding) [XOR].

| Member | What differs | Ports [probe] | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|---|
| Quantcore · `CpweTaper` · waveguide · **key** | legacy `cpwe.tapper`; also exponential profiles 1–3 | a, b CPW | yes (pass-through) | 1 design (amplifiers/unsw_kipa, 9 instances, all linear); 2 tests | keep; **alias of WaveguideCoplanarTaper** (marker; pair) | not bit-identical (sub-µm² differences) |
| KQC · `WaveguideCoplanarTaper` · waveguide · **key** | linear only | a, b CPW | yes (pass-through) | 1 design (kqc/xmonsdirectcoupling) + **implicit: every route a/b change** | keep | route engine |

### G20 · CPW T-junction

Verdict: **exact duplicate at defaults.** `metal:LineTee` = `WaveguideCoplanarSplitter`(lengths [50, 50, 50],
angles [0, 180, 270]) [XOR 0].

| Member | What differs | Ports [probe] | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|---|
| KQC · `WaveguideCoplanarSplitter` · waveguide · **key** | N-way splitter (3 ports of 11 µm at defaults) | a, b, c CPW | yes (one conductor) | 8 designs (KQC demo family, quality_factor_twoface, shaping) + **implicit**: the kplugin T-join tool (`joins.TEE_CELL`) | keep (canonical) | — |
| Metal · `LineTee` · coupler · **key** | Metal T (t_length 50 µm) | prime_start, prime_end, second_end CPW | yes (one conductor) | 4 designs (IBM bowtie and its tutorials, 6 instances at default options); 2 tests | keep; **alias of WaveguideCoplanarSplitter** (marker; pair; t_length → lengths, widths → a_list / b_list) | port names change (prime_* → a/b/c); equality at non-default widths is [inferred] |

## Airbridges

### G21 · Airbridge

Verdict: the same job. Rectangular, MultiFace and Metal draw no CPW at their ports (the bridge sits over one).
The PDK maps the airbridge layers to 300/0.

| Member | What differs | Ports [probe] | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|---|
| KQC · `AirbridgeRectangular` · airbridge | pads + flyover; the default `airbridge_type` of KQC elements and routes | a, b no-CPW | yes (wire / ground strap) | 1 design explicit (airbridge_crossings, 1 281 instances) + implicit (route airbridges, KQC defaults); 1 test | keep (canonical) | — |
| KQC · `AirbridgeMultiFace` · airbridge | flip-chip bridge with bumps (face 2b1) | a, b no-CPW | yes | unused | keep (KQC airbridge_type option) | — |
| KQC · `AirbridgeConnection` · airbridge · **key** | bridge + CPW tapers on both sides | a, b CPW | yes | 5 designs (surface17 / demoqpu17 / wallraff family) + implicit (every route airbridge is an AirbridgeConnection [code: KQC source]) | keep | route engine |
| Metal · `Airbridge` · airbridge | two landing pads + flyover | a, b no-CPW | yes | unused; 1 test | **legacy** (marked, still listed) | none |

## Markers and frames

### G22 · Alignment markers

Verdict: the same job, different drawings. The PDK die frame (`layouts/chips/frame.py`, not a catalog cell) draws
the alignment grids of every `DesignChip`.

| Member | What differs | Used by | Rec. | Risk |
|---|---|---|---|---|
| Quantcore · `AlignmentMarkers` · marker | legacy `draw.marker_align`: 5 µm squares at the four chip corners (1001/0) | unused; golden test | keep (golden), mark legacy | — |
| Quantcore · `CornerMarker` · marker | legacy `Marker.lym`: L marker, HSQ variant, 3/0 keep-out | 4 legacy designs (chip_05, 06, 08, 10a); 2 tests | keep | — |
| Quantcore · `CrossMarker` · marker | legacy `draw.marker`: 20 µm cross (1001/0) | unused; golden | keep (golden), mark legacy | — |
| Quantcore · `EbeamMarker` · marker | legacy `die_creator`: 4 squares in a 600 µm window | unused; golden | keep (golden), mark legacy | — |
| Quantcore · `GlobalMarker` · marker | legacy `draw.global_marker`: 6 squares | unused; golden | keep (golden), mark legacy | — |
| KQC · `MarkerStandard` · marker | KQC chip-frame marker (on M1 / airbridge layers) | unused explicitly (ChipFrame's default `marker_types` [code]); 1 test | keep | — |
| KQC · `MaskMarkerFc` · marker | flip-chip mask marker | unused | keep | — |
| KQC · `CrossTest` · test_structure | a row of optical-lithography crosses on M1 | unused | keep | — |

No LOM, no ports (non-electrical).

### G23 · Chip frame, boundary, dicing

Verdict: the same job. All three are superseded for new designs by the PDK die frame (dicing L-markers, alignment
grids, device ID; AUDIT: "superseded by the PDK die frame").

| Member | What differs | Used by | Rec. | Risk |
|---|---|---|---|---|
| Quantcore · `BoundaryBox` · marker | legacy `boundaryBox.lym`: boundary square on 100/0 | unused; golden | keep (golden), mark legacy | — |
| Quantcore · `DicingMarker` · marker | legacy `draw.marker_dicing`: cross on 1000/0 | unused; golden | keep (golden), mark legacy | — |
| KQC · `ChipFrame` · marker | KQC frame: dicing, markers, texts | unused (DesignChip uses the PDK frame [code: design_chip]) | keep | — |

## Test structures

### G24 · Junction test / DC probe pads

Verdict: the same job, different drawings. These are DC structures: no RF ports, and no LOM except TaperedPad.

| Member | What differs | Used by | Rec. | Risk |
|---|---|---|---|---|
| Quantcore · `JunctionTestPads` · test_structure | legacy `testPad_*` / `xtp_testpads`: two probe pads + a trilayer junction | 7 legacy designs (chip_01_creator, 02, 04, 05, 06, 08, 10a); 2 tests | keep | — |
| KQC · `JunctionTestPadsSimple` · test_structure | KQC pad array with Manhattan junctions | unused; 1 test | keep | — |
| Quantcore · `ProbePadPair` · test_structure | chip_11m pads, junction optional (upper pad 1/0, lower pad 3/0) | 2 designs (chip_11f, chip_11m) | keep | — |
| Quantcore · `JunctionGroundPad` · test_structure | legacy `testPad.py`: pad to ground through a junction bridge | 2 designs (chip_01, chip_01_4x4) | keep | — |
| Quantcore · `TaperedPad` · test_structure | legacy `pad.lym`: probe pad tapering to a junction finger | 1 design (chip_06); 2 tests. Port finger: CPW·wide +cut (it ends in its window, by design) | keep | — |

### G25 · Lithography stripes (KQC)

Verdict: **exact subset.** `StripesTest` = `StripesTestIncreasingWidth`(stripe_step 0) [XOR 0].

| Member | Used by | Rec. | Risk |
|---|---|---|---|
| KQC · `StripesTest` · test_structure | unused (KQC chips use it internally [inferred]) | **legacy** (marked, still listed); alias of StripesTestIncreasingWidth | none |
| KQC · `StripesTestIncreasingWidth` · test_structure | unused | keep | — |

## Shapes and other

### G26 · Junction finger primitives

Verdict: the parts of G4 / G5, not duplicates of each other. They use the same finger functions as the trilayer
cells [code], on 2/0 and 4/0 respectively.

| Member | Used by | Rec. | Risk |
|---|---|---|---|
| Quantcore · `JJFingerStraight` · shape | 1 design (legacy/chip_10a_3x_squid); 2 tests (golden) | keep | — |
| Quantcore · `JJFingerBent` · shape | unused; 2 tests (golden) | keep | — |

### G27 · Metal rectangle

Verdict: **exact duplicate.** `metal:Rectangle` = `metal:MyQComponent` (500×300 µm metal) [XOR 0].

| Member | Used by | Rec. | Risk |
|---|---|---|---|
| Metal · `Rectangle` · shape | 3 designs (pockets with `subtract: true`: iswap1, iswap2, tut443); 3 tests | keep | — |
| Metal · `MyQComponent` · other | unused (Metal's user template, "EDIT HERE") | **removed from the catalog** (still resolves by ref) | none |

### G28 · Metal filled round shape

Verdict: the same job: a filled disc (an n-gon approximates a circle as n grows).

| Member | Used by | Rec. | Risk |
|---|---|---|---|
| Metal · `CircleRaster` · shape | unused | keep or hide | none |
| Metal · `NGon` · shape | unused | keep or hide | none |

### G29 · Flux-trap holes

Verdict: **exact duplicate.** `FluxHoleArray` = `FluxHoles` with the array's centres as a list [XOR 0]. Both LOMs
are empty (no elements).

| Member | Used by | Rec. | Risk |
|---|---|---|---|
| Quantcore · `FluxHoleArray` · other | 7 legacy designs (chip_03, 05, 07, 09, 09_sim, 10a, d14); 2 tests | keep the ref; **alias of FluxHoles** (marker); optionally draw it through FluxHoles (code merge) | low (XOR 0) |
| Quantcore · `FluxHoles` · other | unused in designs; 2 tests | keep | — |

### G30 · Flux bias line (KQC)

Verdict: the same job, two KQC variants, selected by the qubits' `fluxline_type`. Xmon and TransmonCrossFL draw
their own lines.

| Member | Ports [probe] | LOM | Used by | Rec. | Risk |
|---|---|---|---|---|---|
| KQC · `FluxlineStandard` · other | flux CPW | yes (control) | explicit 0; **implicit**: the default `fluxline_type` of the 24 Swissmon / DoublePads / CircularTransmonSingleIsland instances that do not set it [inferred from the KQC default] | keep | — |
| KQC · `FluxlineStraight` · other | flux CPW | yes | unused; 1 test | keep | — |

---

## Unique cells (no duplicate), per category

| Category | Cell (library) | Note |
|---|---|---|
| qubit | `Gatemon` (Quantcore) · **key** | CNT gatemon (QPDK); 1 design |
| junction | `NoSquid` (KQC) | placeholder, draws nothing; "No Squid" in 6 legacy designs |
| junction | `Sim` (KQC) | simulation stand-in, substituted for every `junction_type` in simulation builds |
| junction | `SuperInductor` (KQC) | SQUID-array superinductor; unused |
| junction | `metal:SNAIL` (Metal) | asymmetric multi-junction loop; unused |
| coupler | — | all 9 couplers are in groups (G7, G8, G9, G11, G18, G20) |
| capacitor | `CpweFingerLine` (Quantcore) | finger-loaded CPW (shunt fingers to ground); 1 design. Related to KiTwpaSerpentine's unit cells [inferred] |
| capacitor | `SmoothCapacitorSemicircle` (Quantcore) | SQDMetal coupling pad snapped onto a qubit pin; 1 design. Not KQC `SmoothCapacitor` despite the name |
| resonator | `LumpedJpa` (Quantcore) · **key** | lumped JPA (junction + IDC); 2 designs |
| resonator | `metal:ResonatorLumped` (Metal) | lumped LC resonator, metal only, mm-scale; 1 design |
| launcher | `LauncherDC` (KQC) | DC pad, undirected port; drawn for `launcher_type: "DC"` chips |
| termination | `SquidTermination` (Quantcore) · **key** | CPW shorted through a SQUID, with a pump line; 1 design |
| waveguide | `JtwpaChain` (Quantcore) · **key** | junction-chain TWPA; 1 design |
| waveguide | `KiTwpaSerpentine` (Quantcore) · **key** | kinetic-inductance TWPA; 1 design |
| airbridge | — | all in G21 |
| marker | `WaferMap75` (Quantcore) | 4-inch wafer map of 7.5 mm dies; golden test, kplugin |
| test_structure | `AirbridgeDC` (KQC) | 4-point airbridge DC test; unused |
| test_structure | `TsvTestPattern` (KQC) | TSV fence test; unused |
| flip_chip | `FlipChipConnectorDc` (KQC) | indium bump; also used inside other KQC cells |
| flip_chip | `FlipChipConnectorRf` (KQC) | RF bump transition; used inside WaveguideComposite for face changes [code: KQC source] |
| flip_chip | `TsvStandard` (KQC) | TSV; unused |
| shape | `ArcPath` (Quantcore) | legacy `Arc.lym` single-strip arc (not a CPW); golden test |
| shape | `TextLabel` (Quantcore) | etched text; 7 designs |
| shape | `metal:RectangleHollow` (Metal) | frame shape; unused |
| shape | `metal:CircleCaterpillar` (Metal) | a chain of circles; unused |
| shape | `metal:SmileyFace` (Metal) | Metal "for fun only" test shape; unused. Not a duplicate, but a candidate to hide |
| other | — | all 5 are in groups (G27, G29, G30) |

## What could not be decided (open questions)

Items 1–3 were decided on 2026-11-15 (see [Decisions](#decisions-2026-11-15)): an alias is a catalog marker
for the same circuit drawn differently, never a redirection (so every design keeps its cell names, sidecars and
ports); upstream duplicates stay listed (only metal:MyQComponent is removed); legacy cells stay listed and
placeable with a `legacy` marker (documented later). Of the legacy-only cells of item 3 it
marked SquidV0 and SpiralPath; the others (G22, G23, CpweGapCapacitor, CpweFingerCapacitor, QubitResonator,
CpwResonator, CoupledConnector, CpweQuarterWaveResonator) are unmarked for now.

1. ~~**Does an alias count as "rebuilds identically"?**~~ Decided: aliases are markers, nothing is redirected. An
   alias keeps the geometry (XOR 0 where checked), but a *redirecting* alias would change the cell names in the
   OAS, the `cell` field in sidecars and dashboards, the LOM model and element names, and sometimes the port names
   (`metal:LineTee` prime_* → a/b/c; `CpweOpenEnd` a ↔ `metal:OpenToGround` open).
2. ~~**Metal and KQC upstream duplicates:**~~ Decided: list everything (aliases marked); only metal:MyQComponent
   is removed.
3. ~~**Legacy-only cells**~~ Decided: legacy marker, still listed (11 cells, the Decisions table).
4. **Which pad carries the PDK pad-edge rule** if the launch pads are consolidated. BondPad is the obvious
   canonical, but this was not checked against `pdk/`.
5. **Not compared:**
   * the claws (Xmon claw vs Metal claw connection pads; the cross bodies are identical);
   * DoublePads vs TwoPadTransmon / TransmonPocket at matched sizes (different pocket rules; judged by code);
   * LineTee and CpweOpenEnd at non-default widths;
   * the instances' own a/b in the designs that use the G16 open ends.
6. **Port findings outside the duplicate question**, for the components owner:
   * `metal:PolylineCPW`'s LOM ends a free end **open** (`("open", "open")`), but its drawing ends flush like
     CpwSegment (XOR 0), i.e. a free end runs into ground (short), unless `open_pins` keeps Metal's etch there. It
     only matters for a free end (its one design was not checked);
   * `metal:TunableCoupler01.Flux` declares a 20 / b 12 but draws 5 / 3 µm;
   * several Metal pins (`TransmonInterdigitated` readout/bus, `CapFingerInFrame.frame`, `ResonatorCoilRect`, `StarQubit` pins) have their CPW drawn beyond the pin rather than behind it at defaults. That may be intended (the wrapper's `open_pins` handling) but was not verified.

## Checks run (evidence)

Geometry XORs (µm², default parameters unless shown; A/B = the two areas on the layer named):

| Pair | Layer(s) | Result |
|---|---|---|
| TwoPadTransmon vs PadCoupler | 1/0 etch, metal | 0, 0 |
| WaveguideCoplanarStraight(l 200) vs CpwSegment(200)+100 | etch | 0 |
| metal:PolylineCPW vs CpwSegment(500)+250 | etch | 0 |
| WaveguideCoplanar vs CpwSegment(100)+50 | etch | 0 |
| GatemonCoupler vs CpwSegment(600)+300 | etch | 0 |
| metal:OpenToGround vs CpweOpenEnd(length 6) | etch | 0 |
| metal:OpenToGround(10 µm) vs CpweOpenEnd | etch | 0 |
| WaveguideCoplanar vs WaveguideCoplanar(term2 6) | etch | 132 (the open-end box) |
| WaveguideCoplanarTaper vs CpweTaper(31.416, 20/12) | etch | 0.029 of 565 |
| BondPad vs Launcher(450, 450, 400, 225, 225) rot 270 | etch | 0 |
| ConnectorPad vs Launcher(300, 300, 275, 165, 300) rot 270 | etch | 0 |
| ConnectorPad vs BondPad(275, 300, 300, pad_gap 165 / 300) | etch | 81 675 / 202 500 |
| CpweBondPad(taper_type 0) vs Launcher(50, 500, 500, 300, 10) rot 180 +560 | etch | 0 (taper_type 3: 125 953) |
| metal:LaunchpadWirebond vs Launcher(80, 122, 80, 58, 58) rot 180 | etch | 300 (= the 25 µm lead) |
| metal:LaunchpadWirebond vs …Driven / …Coupled | etch | 0 / 3 383 |
| metal:TransmonPocket vs Pocket6 / PocketTeeth | etch, 2/0 | 0 / 4 133 |
| TransmonPocket vs Pocket6, one +1/+1 pad (Pocket6 pad_cpw_shift 5, pocket_rise 65 / own defaults) | etch | 0 / 4 316 |
| metal:TransmonCross vs TransmonCrossFL (bare / one claw) | etch | 222 / 222 |
| metal:TransmonCross vs TransmonStar(4 arms, 200 µm, junction arm 3) | etch, 2/0 | 0, 0 |
| metal:TransmonCross vs Xmon(claws [], arm 20, length 400, gap 20, No Squid) | etch | 0 (2/0: Metal footprint 400 vs none) |
| metal:Rectangle vs metal:MyQComponent | metal | 0 |
| TrilayerJunction vs TrilayerJunctionHSQ (defaults / bent_finger_y −2, bent_shift 0, hsq_extra 0.1) | 4/0; 50/0 | 31.5 / 0; 0.04 / 0.10 |
| TrilayerSquid vs TrilayerSquidHSQ | 2/0, 4/0 | 14.05, 31.0 |
| QuantcoreJunction vs TrilayerJunction(0.5, 0.6, clearer) | 2/0, 4/0, metal, 50–53/0 | all 0 |
| QuantcoreSquid vs TrilayerSquid(0.25, 0.6, clearer) | 2/0, 4/0, metal, 50–53/0 | all 0 |
| FluxHoleArray vs FluxHoles(20 centres) | etch | 0 |
| StripesTest vs StripesTestIncreasingWidth(step 0) | etch | 0 |
| DoublePads vs DoublePadsSplines | etch; junction layers | 19 891; 0 |
| metal:LineTee vs WaveguideCoplanarSplitter(50, 50, 50) | etch | 0 |
| CoupledResonator vs QubitResonator | etch | 27 827 |
| SpiralPath vs SpiralLine(archimedean, r = 1/π, π…10π, w 1, etched) rot 180 | etch | 2.4 of 155 |
| CircularTransmonSingleIsland vs ConcentricTransmon | etch | 175 878 |
| Manhattan vs ManhattanSingleJunction | 2/0 | 275 |

Coverage (at the audit): 144 entries = 120 in groups G1–G30 + 24 unique; since metal:MyQComponent (G27, other) was removed the catalog has 143 (119 in groups). Per category (in groups / unique):

| Category | Groups | Unique |
|---|---|---|
| qubit | 20 | 1 |
| junction | 14 | 4 |
| coupler | 9 | 0 |
| capacitor | 10 | 2 |
| resonator | 10 | 2 |
| launcher | 7 | 1 |
| termination | 4 | 1 |
| waveguide | 12 | 2 |
| airbridge | 4 | 0 |
| marker | 10 | 1 |
| test_structure | 8 | 2 |
| flip_chip | 0 | 3 |
| shape | 7 | 5 |
| other | 5 | 0 |
