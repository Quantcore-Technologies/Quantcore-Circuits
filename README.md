# quantcore-circuits: Quantcore's KLayout plugin

This is the GUI front end for `design.json` designs. It's a Salt package that needs only KLayout's own Python, `pya`
and the standard library. It does **not** import KQCircuits or quantcore_circuits inside KLayout, so it doesn't depend
on the KQC Salt package or its version.

`design.json` holds the design. Every tool edits it, and `qcc` (in the conda env) rebuilds the
layout, which the plugin then reloads in place. The overlays (ports, handles, previews) come from the
`build/<name>.qcc.json` sidecar that every `qcc build` writes next to the OAS.

## Install

You need KLayout 0.30 or newer and the `quantcore-circuits` Python package in an environment that has the `qcc`
command (`pip install --pre "quantcore-circuits[all]"`).

1. In KLayout open **Tools ▸ Manage Packages**, then **Install New Packages**, search for `quantcore-circuits` and
   install it. The package is read from the repository's `klayout-plugin` branch,
   `git+https://github.com/Quantcore-Technologies/Quantcore-Circuits.git[klayout-plugin]` (<https://github.com/Quantcore-Technologies/Quantcore-Circuits/tree/klayout-plugin>).
2. Restart KLayout. A **Quantcore** menu appears next to Help, and three tool modes appear in the toolbar.
3. Optional: open **Quantcore ▸ Settings…** and set:
   - the **qcc executable**. Set the full path of `qcc` (`qcc.exe` on Windows) when it is not on PATH. If this is left
     empty, the plugin finds `qcc` on PATH, then in a conda env named `qcd`
     (`%USERPROFILE%\.conda\envs\qcd\Scripts\qcc.exe`);
   - the fallback grid (default 1 µm). Nodes and placements snap to **KLayout's editor grid** (`edit-grid`, set in
     KLayout's editor options), like KLayout's own shapes; this grid applies only when KLayout has none;
   - the capture radius (default 12 px);
   - the **height of the instance name labels** (TCT1, R1, … on the `instance_names` layer), default 70 µm, 0 = none.
     KQC draws them 280 µm tall, and `qcc build` without `--label-height` still does. The plugin's builds pass
     `--label-height`; it is an annotation layer, so the fab mask, the simulations and the design do not change. A new
     value rebuilds the layout;
   - **long dialogs in two columns** (on by default). Every dialog fits the screen: its rows scroll, OK / Cancel
     stay visible below them, and the window can be resized. When one column would be taller than the screen, the
     route, hanger and component dialogs put their rows in two columns (the component dialog: position and parameters
     left, targets, junction and circuit right). The circuit picture opens fitted to its window (Fit, 100 %, −, +);
   - *Live PCells* (off by default): the Quantcore cells in KLayout's Instance tool and PCell dialog (see
     [Live PCells](#live-pcells-experimental-off-by-default)).
4. Optional: the klive Salt package, for `qcc watch` / Jupyter pushes. The plugin itself doesn't need it.

**From a checkout (development).** Without installing anything, start KLayout with the plugin loaded straight from a
clone of the main repository: `klayout_app.exe -e -rm kplugin/load_dev.py`. `Designer(..., live=True)` and
`quantcore_circuits.live.klayout.open_klayout()` run the same command. To install the checkout as a package, link its
`kplugin/` folder into KLayout's Salt directory (a link, so a `git pull` updates it):

```bat
mklink /J "%USERPROFILE%\KLayout\salt\quantcore-circuits" "C:\path\to\Quantcore-Circuits\kplugin"
```

## Draw Q1 + R1 by hand (the `examples/q1_r1_feedline.json` layout)

Step by step, with every value: [TUTORIAL_q1_r1.md](TUTORIAL_q1_r1.md) (new design → pads → qubit → feedline →
hanger resonator → flux line with its taper → Check → LOM → design.py → Fab).

## Drawing a readout resonator

A readout resonator is a λ/4 line that is shorted at one end and coupled to the feedline along a straight stretch.
In the plugin the **hanger** is the coupler, so there is no separate coupler component to place.

1. Draw the feedline first (*Connect*: pad port, pad port).
2. Still in *Connect*, start the resonator **at the qubit's claw port** (`Q1.claw_n`) or, for a bare resonator, on
   **empty canvas** (a free open end). Click any nodes the meander should pass through.
3. **Click on the feedline** where the coupler goes. The hanger dialog sets the meander length (about 4300 µm for
   7 GHz), the coupler length, the side, *short* (λ/4) or open, and the ground strip. The coupler sits parallel to the
   feedline, and the meander fills the longest free straight. Route handles (*Route handles*) move its nodes later.

Tested in `gui_smoke.py` and `gui_smoke_components.py`: claw → feedline gives a built, DRC-clean λ/4 whose LOM has
the resonator, the claw capacitor and the hanger coupling.

Any qubit's port works, not only the Xmon claw (TwoPadTransmon `left`/`right`, Flipmon `coupler`, …). The router goes
around a port that faces sideways with extra corners when a direct path has no room for its bends. When the start
port is no CPW end (a Gatemon `readout` is the 150 µm island edge), the dialog presets the PDK line width and gap.

To merge instead of hang, press **Ctrl+Shift+J** (Quantcore ▸ Edit ▸ *Connect on a line: hang / merge*; plain T is
KLayout's *Tap*) and a
click on a line merges the route into it: the line is split into two routes joined by a T (KQC
`WaveguideCoplanarSplitter`, one conductor in the LOM), and the route ends on the T's stem. This is for a capacitor or
a stub galvanically on the feedline. The dialog's *Merge into … (T-junction)* checkbox decides per route. Later,
the same checkbox in the route's dialog (double-click it in Route handles) converts hang ↔ merge, removing or adding
the T. The functions are in `python/qcc_kplugin/joins.py`; tests are in `tests/test_kplugin_joins.py`.

The library cells for the same job do not work as a substitute in the GUI:
- `CoupledResonator` / `QubitResonator` (meander with a built-in coupler arm) and `CpwResonator` /
  `CpweQuarterWaveResonator` are placed by hand and their `end` port is the tail towards the qubit. A *Connect*
  route from that port builds, but `qcc design drc` reports it as galvanically open (the tail ends in an etched
  gap, a capacitive end), and the LOM needs a `d.couple(...)` call (script only, not in `design.json`) to know the
  feedline coupling, so `qcc circuit simulate` stops with "open or shorted". Use them in scripts, not in the GUI flow.
- `PadCoupler`, `CpweOpenEnd`, `CpweGapCapacitor` and the other couplers or terminations are parts for other
  circuits (qubit pads, CPWE lines). A claw-to-line or canvas-to-line *Connect* already gives the shorted end.

## Editing what is placed

- **KLayout's own tools work on components and routes.** After every build the plugin shows the chip cell
  (`Design…Chip`) as the view's cell, so each component and route is a top-level instance: select it, move it, rotate
  it (Edit ▸ Selection ▸ Rotate…), delete it, or change its position in KLayout's properties dialog. The plugin writes
  each change to `design.json` and rebuilds. The readout coupler of a moved qubit moves with it; deleting a component
  also removes its routes; deleting a route instance removes that route.
- **Parameters:** select a component and choose **Quantcore ▸ Edit selected component… (Ctrl+Shift+Q)**, or
  double-click it in *Move/Snap*. This edits its PCell parameters and rotation.
- **Junction (simulation and LOM only, not drawn, not in the fab mask).** A qubit's dialog has this section under the
  parameters. The lumped values are simulation values fixed per component in design.json (`junction`); the drawn
  junction (`junction_type`) is for fab only. Rows: **L_J, I_c, R_n** (one value, typing one fills the others) and
  **C_J**; for a SQUID also **flux Φ/Φ0** and **asymmetry d** (empty = 0: the sweet spot, L_J is its zero-flux value);
  then read-only **L at this bias** (L_J / √(cos² πΦ + d² sin² πΦ), recomputed while you type; Φ = ½ with d = 0 shows
  the library's error), the **source** (design, drawn junction with the PDK rule, or none) and, when the cell draws a
  trilayer junction, the **drawn junction (PDK)** value, so a fixed value that no longer matches the drawing is
  visible. When the design has no value but the drawn junction gives one, that value is the fields' placeholder
  ("PDK, drawn junction") and **nothing is written unless you type** (the same value the LOM and the HFSS export
  take). Saving merges into the existing `junction`: flux and asymmetry stay, and are written only when non-zero. The
  sidecar's `instances.<name>.junction` (kind, `Lj0_nH`, `Lj_eff_nH`, `source`, `error`) feeds the rows; the drawn value
  of a cell that also has a design value comes from `qcc design placement-junction` (`jfetch.py`). Edit ▸ Undo takes
  an edit back.
- **Placing a qubit fixes its junction at design time.** A component with a junction (panel double-click + click,
  Duplicate, KLayout's Instance tool with Live PCells) gets `junction = {Lj_nH, Cj_fF}` in design.json in the same
  undo step as the placement: a drawn trilayer junction's PDK value (a KQC qubit left at its default junction is
  drawn as the PDK Quantcore Squid, so it gets that), or for a chosen KQC junction type (Manhattan, ...) the
  PDK nominal SQUID (`"Quantcore Squid"`: L_J0 6.7344 nH, C_J 15 fF; asked from the library, not copied). The status
  bar says "Q1: junction L_J 6.73 nH (PDK nominal SQUID; simulation value, edit in the component dialog)". Existing
  instances are not changed, and a duplicate keeps its source's values. The library call starts in the background when
  the placement is armed (`jfetch.prefetch`), so the click does not wait.
- **Duplicate (Ctrl+Shift+U) / Mirror (Ctrl+Shift+F)** the component selected with KLayout's select tool (or under
  the *Move/Snap* cursor). The copy (same parameters, rotation, mirror, junction) follows the mouse; a click drops it.
- **Rotation while placing or moving:** **[** / **]**. Right-click cancels a placement or a move.
- **Route corners:** every corner is bent to the route's radius (double-click the route to change it), unless that
  node has its own radius (`"r"` in the node, set with the green curvature handle or the node dialog).
- **The tool stays on:** after each rebuild the view reloads, and the Quantcore tool you were using is switched on
  again.
- **Components and routes are cells the plugin rebuilds**, not live PCells: an edit made in KLayout lasts until the
  next build, which writes the same edit back from `design.json`. KLayout's PCell dialog does not apply to them; use
  *Edit selected component*. Settings ▸ *Live PCells* (below) makes the components library PCells.

## Live PCells (experimental, off by default)

**Quantcore ▸ Settings… ▸ Live PCells** registers a KLayout library **Quantcore** with the Quantcore PDK cells (57 of
them: `qcc components --source quantcore`). Then:

- **KLayout's Instance tool** places them: pick library *Quantcore*, a cell (e.g. `Xmon`), set its parameters in the
  tool's PCell tab, click in the chip. The plugin writes the instance to `design.json` (cell, the parameters that
  differ from the defaults, position, rotation, mirror), gives it its `id` and rebuilds. *Edit ▸ Undo* takes it back.
- **KLayout's PCell dialog** (the instance properties) edits a placed component's parameters; the change goes to
  `params` in `design.json` (keys the dialog does not show, such as shapes, stay as written) and is rebuilt.
- Moves, rotations and deletes with KLayout's tools, the palette, the Quantcore tools, the overlays and the DRC markers
  work as before. Routes stay plain cells (KQC's node editor does not apply to them; use *Route handles*).

The plugin does not import quantcore_circuits or KQCircuits inside KLayout, for these reasons. Tested with KLayout
0.30.3 on Windows: its Python is 3.11.6 built with MinGW (GCC 13.2, its extensions are `cp311-mingw_x86_64`); the
`qcd` env is 3.11.18 built with MSVC (`cp311-win_amd64`), so no compiled
package of the env (numpy 2.4, scipy 1.17, pydantic-core) loads in KLayout. KLayout ships numpy 1.26.1, scipy 1.11.3,
networkx 3.3 and tqdm 4.66.4 but no pydantic, and `quantcore_circuits.layouts` imports pydantic (through
`DesignChip` → `route` → `design.schema`). The development KQC (the one `qcc` builds with) imports in KLayout, but its
import opens a modal "Dependencies out of date" dialog that offers to pip-install networkx 3.6.1 / tqdm 4.67.1 into
KLayout. The KQC Salt package tested (4.8.2) is another version (119 files differ) and too old for
quantcore_circuits (no `kqcircuits.elements.quarter_wave_cpw_resonator`), and only one `kqcircuits` can be loaded per
process.

So each PCell is a light declaration, and its geometry is **what `qcc` built**:

- the parameters come from one `qcc components --source quantcore --schemas` call (about 1.2 s, in the background at
  startup or when the box is ticked);
- after every rebuild each component's built cell is cached under (cell, parameters), and its static instance is
  swapped for a library PCell instance with the same parameters, transform and `id` (about 40 ms for Q1 + R1). The
  geometry in the view is the build's, so the next rebuild draws exactly the same;
- a parameter set that has not been built yet (a value typed in the Instance tool or the PCell dialog) is drawn at once
  from the nearest cached geometry of that cell (13–32 ms in the UI thread), and `qcc components CELL --params P --oas F
  --design DESIGN` fetches the real geometry in the background (about 1.3 s; `--design` gives it the chip's inherited
  parameters and the PDK junction, so it equals the build). The library is then refreshed. A placed or edited
  instance is rebuilt anyway (about 1.3 s with `qcc build`).

The panel's Components tab uses the same idea (`qcache.py`): the list, a component's parameters and its outline come
from one cache that survives restarts (a library change refreshes it; *Refresh list* forgets it). On a miss `qcc` runs
in the background and the panel shows "loading…" (list), an empty table (parameters) or the status bar (outline), then
the result arrives; after the list loads, every Quantcore component's parameters are prefetched in one call, and the
outline of a selected component is prefetched, so a double-click usually arms the placement at once. Timings: a call
blocked for about 1.35 s without the cache and a few milliseconds with it (1.4 s until the result arrives on a miss,
1 to 8 ms on a hit).

A PCell calling `qcc` from `produce_impl` would stall KLayout about 1.2 s per parameter change (Python + KQC start-up
of each `qcc` call), so the fetch runs in the background and never blocks.

Limits: KLayout counts the view's layout as modified after the swap, so closing KLayout asks to save it (answer No:
the OAS is a build output). KLayout 0.30.3 crashes when a library is refreshed while its Instance tool shows a preview
of one of its PCells; the plugin switches the tool off for the refresh and on again (`pcells.safe_refresh`). An
instance whose `params` hold values outside the editable schema (shapes, layers) stays a static cell. Arrays placed
with the Instance tool are not design instances (the status bar says so). Turning the box off takes effect at the
next build; the library stays registered until KLayout restarts.

Importing the library inside KLayout instead would need: pydantic made optional in the
`layouts` import chain (a library change), a MinGW build of any compiled dependency, the development KQC loaded before
(or instead of) the KQC Salt package, and its dependency check answered. That is an environment change the plugin does not make, so the plugin's copies of library facts (`design_io.TARGET_TOL`, `flow`'s AEDT path limit, qubit detection by cell
name in `design_io.target_keys`) stay copies.

**Live PCells or the Quantcore panel: your choice.** Both write to the same design.json, so use whichever you like
(or switch between them): the Quantcore panel (double-click a component, Move/Snap, its edit dialog) or KLayout's own
Instance tool and PCell dialog on the library. The bridge is optional. What the bridge keeps:
a component placed or edited as a library PCell is a design instance (it has its `id`), so Rebuild, Check and Run LOM
work on it as on any other (checked: a `cross_length` changed in the PCell dialog reaches design.json, the rebuild
draws it and the LOM circuit export runs from it; converting the instance to a static cell with KLayout's own command
changes nothing, the next build makes it a library PCell again). What is lost is everything that never reaches design.json:
shapes drawn with KLayout's own tools and PCells of other libraries are not components, so they have no ports, no LOM
nodes and no DRC, and the next rebuild reloads the layout from design.json and removes them; the PCell dialog sets the
cell's parameters only (rotation, targets and junction values are edited in the Quantcore dialog). So a layout that is
taken on as plain KLayout shapes or PCells, with design.json no longer updated, no longer has Rebuild or LOM from the
panel.

## Tools (toolbar modes)

| Icon | Mode | What it does |
|---|---|---|
| ![](icons/qcc_connect.png) | **Connect** (pen tool) | **Start** on a port, or on empty canvas (a free end, open by default). **Each canvas click adds a node** on the grid. Without Shift the segment turns once with a square corner, and the click keeps exactly the corner the preview shows. With **Shift** it goes straight at the nearest of 0°, 45°, 90°, … from the previous point, or along the start port's own axis when that port faces an angle (a StarQubit pin, a ConcentricTransmon coupler: the node lands exactly on the port's direction). With **Ctrl** the node goes where you click (on the grid, any angle) and the segment to it is one oblique straight, with no square corner; finishing on a port with Shift or Ctrl runs straight into its stub. **Finish** on a port (route dialog: name, cpw or meander + length, bend radius, free-end termination), on a **line** such as the feedline (a hanger coupler: the dialog asks for the coupler length, the side, preset to the side you came from, short = λ/4 or open, the ground strip, the direction and the meander length), or by **clicking the last node again** (a free end there, pointing back along the last segment). The rubber band shows the CPW with every corner bent to the radius, and a cross marks the snapped point. **Right-click** removes the last node, or cancels. |
| ![](icons/qcc_route_edit.png) | **Route handles** | Every route shows its nodes as filled squares (every corner, including the corners the router drew by itself; their first edit writes the route's corners to design.json, so the shape stays) and, on each free straight segment, an insert handle (hollow square: it adds a node, it is not one). **Click a node** to select it and pick it up, move, click to drop it (grid, any angle, so a segment can be oblique; Shift aligns it with its neighbours at 0° / 45° / 90°, or onto an angled port's axis; Ctrl is the plain grid point). A **selected corner** shows a green **curvature handle** on its arc: pick it, move it along the bisector, drop it to set that corner's bend radius (rounded to the grid). The preview warns when a segment is too short for its bends. Right-click a node, or press **Ctrl+Shift+X**, to delete it. **Double-click** a node for its dialog (exact x, y, corner radius, airbridge, taper a / b from this node on; also **Ctrl+Shift+N**), or a route for its options (type, length, radius, meander segment preset to the segment you double-clicked, meander turns and first-turn side, the hanger's coupler length / side / end / ground strip / direction, merge or hang; the same dialog opens from a Move/Snap double-click on a route and from Edit selected with a route selected). **Ctrl+Shift+M** puts the meander on the straight under the cursor. |
| ![](icons/qcc_snap.png) | **Move/Snap** | Click an instance to pick it up, move it ([ ] rotate), click to drop it. A port that comes within the capture radius of a compatible port (same CPW a/b) snaps **and turns the component to face it** (see *Rotation snapping* below), and the placement is stored as `place.snap`; otherwise `place.at` is grid-rounded and the rotation stays on the 90° steps. After a double-click in the panel or **Duplicate**, the component's outline (its etched shape, bbox and port arrows, from `qcc components CELL --outline`) follows the mouse; **[** / **]** rotate it by 90°, a click drops it, right-click cancels. **Double-click a placed component** to edit its parameters and rotation (only values that differ from the defaults are written to `design.json`). |

Port stubs and hanger couplers are fixed segments and get no handles.

**Rotation snapping.** While you drag a placed component, or move a new one (armed with a double-click in the panel or
**Duplicate**), a port that comes within the capture radius of a compatible port (same CPW a / b) snaps, and the
component **turns by whatever angle makes the port face the target**: the preview shows the turned outline, the port
arrows and the label `snap SQ2.pin_cpl4 -> SQ1.pin_cpl2, turn -36.0° (rot 324.0°)`, and the green square marks the
target. It works for angled ports (a StarQubit's pins are 72° apart, a ConcentricTransmon's couplers 60°). The
rotation is solved exactly as the build solves `place.snap`, so the built component lies where the preview was
(`snap_trans` in `assembly/plan.py`; a mirrored component stays mirrored). The smallest turn wins when several of its
ports would fit (a symmetric Xmon). Without a nearby port the rotation stays on the 90° steps of **[** / **]**. Hold
**Ctrl** for **no rotation snap**: only ports that already face each other (within 2.5°) snap, as before. A snap to a
line (a route) is not offered: a design's `place.snap` targets ports only; routes attach to a line with the Connect tool.

![Dragging a StarQubit onto the pin of another: it turns by -36° to face it](../docs/images/plugin/rotation_snap_preview.png)
![After the click: the pins sit on each other, facing](../docs/images/plugin/rotation_snap_built.png)

**Oblique straights.** Between two ports that face an angle the router draws one oblique straight instead of a Manhattan
stair: straight from stub to stub when the ports face each other along one line (within 5° at each end, e.g. two
StarQubit pins), or one bend where an angled port's axis meets the other end's axis (a turn of at most 90°). The
preview shows the same path. Only where the bends fit; routes between axis-aligned ports are Manhattan as before. A
meander works on an oblique straight like on any other (the route dialog's *Meander on straight* lists it). A hanger
coupler or T-junction needs a horizontal or vertical straight: Connect refuses an oblique one with a message.

**Failed routes.** The plugin builds with `qcc build --keep-going`: a route that cannot be built (a bend too tight
for its straight, a KQC "Straight segment cannot fit", a missing hanger host) does not stop the design. Everything else
builds and shows; the route is left out, the status bar names it and the reason, and it is drawn **in red** (its last
good path, wide, when there is one; the path the design asks for now, dashed, with its nodes). In **Route handles** it
has its handles: move or delete its nodes, double-click it for its dialog (the reason on top; *Delete this route*), or
press Delete on its line (also **Edit ▸ Delete route…**). A route that hangs on a failed route fails with its own
reason. The sidecar lists `failed_routes` (`error`, the path asked for, `last_good`), and the DRC reports
`route_failed`. Each good build stores every route's polyline and length in `build/<name>.last_good_routes.json`; the
LOM (Run LOM, `qcc circuit export`) uses the last good route of a failed one and prints a warning naming it; without
one it says which route is missing. The fab export refuses while a route has failed. The default `qcc build` (scripts,
notebooks, tests, `qcc mask`) stays strict and fails on the first bad route.

## Menu

Six submenus that follow the flow, then the panel and Settings:

```
Quantcore
  Design           New design… · Open design… · Chip settings (label, die size)… · Rebuild (Ctrl+Shift+B) ·
                   Save as Python script (design.py)…
  Edit             Undo (Ctrl+Shift+Z) · Redo (Ctrl+Shift+Y) · Edit selected component… (Ctrl+Shift+Q) ·
                   Rename selected component… · Add coupling between components… · Delete route… ·
                   Rotate ± 90° ([ / ]) · Duplicate (Ctrl+Shift+U) · Mirror (Ctrl+Shift+F) ·
                   Delete route node (Ctrl+Shift+X) · Route node properties (Ctrl+Shift+N) · Meander here (Ctrl+Shift+M) ·
                   Connect on a line: hang / merge (Ctrl+Shift+J)
  Check and LOM    Check design (Ctrl+Shift+D) · Fix pad edge warnings (PDK 100 µm rule) ·
                   Run LOM simulation (Ctrl+Shift+O)
  Simulate         Simulate selected components (automatic, in AEDT)… · Open simulation layout… · Import results…
  Results          Results against targets… · Propose next revision…
  Fab              Export for fab (mask, netlist, design.py, PNG)…
  Quantcore panel (Ctrl+Shift+P)
  Settings…
```

**Not in the menu on purpose** (each is done by the panel, a dialog or KLayout itself, and
none is the only way to reach a shortcut):

| Removed item | Use instead |
|---|---|
| Place component… | double-click the component in the panel's Components tab |
| Selected path(s) → route | the Connect tool (it snaps to ports, lines and hangers) |
| Live rebuild on/off (`qcc watch`) | nothing: every edit already rebuilds with `qcc build --keep-going` (failed routes show in red; `qcc watch` is strict) |
| Write moved instances to design.json | moves, rotations and deletes with KLayout's own tools are written to design.json by themselves |
| Save view as PNG… | KLayout's File ▸ Screenshot |
| Junction values (Lj, Cj)… | the junction section (L_J / I_c / R_n, C_J, SQUID flux and asymmetry) of the component dialog (Edit selected component…) |
| Delete instance… | select it and press KLayout's Delete (its routes go too); Edit ▸ Delete route… stays because a failed route has nothing to select |
| Stop LOM simulation | the Stop button of the LOM tab |
| Export sim job… | *Export the job only* in the Simulate dialog |
| Open results file… | Import results… (pick "A results.json file") |

The functions behind them stay (the panel, the dialogs and the tests use them); only the menu entries went.

The panel's **Flow strip** (Design → Check → LOM → Simulate → Results → Fab) has one button per step, with a mark:
✓ done, ⚠ done but out of date or with issues, – not done yet; the line under it names the next step. Check and LOM
are out of date when the design changed since they ran, Simulate when the results belong to another revision, Results
when a target fails (Propose is the next step) and Fab when the mask is older than the design. Writing a sim group or a
target does not make a step out of date (the marks compare a fingerprint of the design without `sim_groups` and
`targets`, kept in `build/<name>.flow/marks.json`).

The strip through one design (the `q1_r1_feedline` example, screenshots from the GUI test): after Open,
after Run LOM, after Simulate (a target fails: Results ⚠, Propose is next), after applying the proposal (LOM, Simulate
and Results out of date, the old results marked stale) and after Fab.

| Open | Run LOM | Simulate | Apply a proposal | Fab |
|---|---|---|---|---|
| ![Flow strip after Open: Design done](../docs/images/plugin/flow_1_open.png) | ![After Run LOM: the LOM tab with the modes and the targets](../docs/images/plugin/flow_2_lom.png) | ![After Simulate: the Results tab, a target fails](../docs/images/plugin/flow_3_simulate.png) | ![After Apply: LOM, Simulate and Results out of date](../docs/images/plugin/flow_4_apply.png) | ![After Fab: Fab done](../docs/images/plugin/flow_5_fab.png) |

- **New design…**: a blank PDK die saved as a new `design.json`, opened and built. The dialog asks for the die width
  and height (default 7500 µm); *Square die* (on by default) makes the height follow the width.
- **Chip settings…**: the label written on the die (`chip.params.name_chip`), the die width and height (the
  same rows and *Square die* checkbox as New design), the KQC ground-plane grid (`with_grid`).
- **Rename selected component…**: the GUI names a placed component after its cell (`BP1`, `X1`, `TP2`); rename it to
  what the design calls it (`PAD_W`, `Q1`). Routes, snaps, targets, sim groups and couplings that name it follow. Route
  names are set in the route dialog (a rename there also updates the routes that hang off it).
- **Add coupling…** (Edit) writes a `couplings` entry (a C in fF or L in nH between two components or a route and a
  component, e.g. the capacitance between facing qubit arms); a FEM result can fill its value later. The qubit's
  junction (L_J, I_c or R_n, and C_J; a Quantum Metal qubit has none until you give it one, and the LOM then fails with
  an open circuit) is in the component dialog.
- **Fix pad edge warnings** sets `place.edge = "auto"` on every pad the PDK pad rule flags (outer etch edge 100 µm from
  the die edge): the build slides the pad perpendicular to the nearest die edge; its position along the edge stays.
- **Undo** keeps 50 levels. A route that cannot be built is left out and drawn in red (see Failed routes above); any
  other build error never replaces the layout: the message goes to the status bar and the console, the last good
  layout stays, and Undo gets you back.
- **Placing components**: double-click one in the panel's Components tab (parameters from its table). The tab
  has two drop-downs: the library (quantcore / kqc / metal / all) and the **class** (qubit, resonator, capacitor,
  launcher, …, from `qcc components --json --details`). The class also decides the targets the edit dialog offers:
  every `qubit` gets f_q / α (KQC `DoublePads` too), every `resonator` f / κ, and a junction cell none. A new
  component of your own: TUTORIAL_q1_r1.md section 13 and `examples/custom_component/`.
- **Edit** holds the editing actions. Each has a shortcut, so it works wherever the keyboard focus is (KLayout needs a
  menu entry for a shortcut). None of them clashes with KLayout's own shortcuts; the GUI smoke test checks.
- **Moves and deletes** with KLayout's own tools are written to design.json by themselves (the session compares the
  layout with the last build), and the rebuild follows; Quantcore Undo takes them back.
- **Simulate / Results / Fab** items (and *Save as Python script* in Design) come from `qcc_kplugin/flow.py`
  (`ACTIONS`, a list of `(submenu, name, title, func, shortcut)` with `submenu` one of `"design"`, `"simulate"`,
  `"results"`, `"fab"`). An empty Simulate / Results / Fab submenu shows a disabled "(coming soon)".
- **Run LOM** exports the circuit (`build/<name>.circuit.json`) and simulates it in the background; the LOM tab shows
  the modes, f_q, α, f_r, χ, κ against the targets, the netlist values and a picture of the circuit. A value is
  *within tolerance* by the same rule as `qcc analyse`: f_q ± 20 MHz, f_r ± 10 MHz, α ± 10 MHz, g ± 10 MHz,
  χ ± 0.1 MHz, κ ± 0.2 MHz, any other key ± 1 % (`DEFAULT_TOL` in `quantcore_circuits/lom/builder.py`; the plugin's
  copy is `design_io.TARGET_TOL`, and a test keeps them equal). design.json holds the target values only.
  While it runs, a progress bar shows the stage (export, read, QuCat + QuTiP, write, draw; `qcc circuit simulate`
  prints `[lom] …` stage lines on stderr) with the elapsed time, and a log shows what `qcc` prints. It stops by itself
  when a step fails (the error stays in the log, with a hint for a qubit without junction values) or after the time
  limit (**Settings… ▸ Run LOM time limit**, default 30 minutes; the `qcc` process tree is killed).
  **Stop** (next to Run LOM in the tab) kills only the LOM process
  this panel started, deletes that run's partial output and puts the tab back as it was before the run: Run LOM is
  enabled again, and the previous circuit, `lom.json`, picture, tables and status line are the same as before (files
  the run overwrote are restored, files it created are removed).
  When a route failed to build, the LOM uses its last good route and prints `WARNING: route R2 failed to build (...);
  using its last good route`: the tab shows that line under its status (and the status bar names the first), besides
  the log.

The menu is grouped by flow step. *Run DRC* (a message box) is now **Check design**,
the Check button of the panel (background process, shown in the DRC tab); the panel's Netlist tab is part of the LOM
tab. *Export LOM circuit* (Ctrl+Shift+E) is gone: Run LOM writes the same `circuit.json`, and the fab export bundles it.


## Dialogs

Every dialog fits the screen (`python/qcc_kplugin/dialogs.py`). Its rows sit in a scrolled body, OK / Cancel stay
below it, the window can be resized from its corner, and it opens at its content's size but never larger than about
90 % of the free screen area. When one column would be taller than 60 % of the screen, the long dialogs put their rows
in two columns. The screenshots below are from a 960 × 570 screen (a laptop at 200 % scaling), so they show two
columns.

**Settings** (Quantcore ▸ Settings…):

![The Settings dialog](../docs/images/plugin/dialog_settings.png)

| Row | What it does |
|---|---|
| qcc executable | The `qcc` the plugin runs. Empty: `qcc` on PATH, then the conda env `qcd` |
| Placement / waypoint grid µm | The fallback grid, used only when KLayout's editor grid is not set |
| Capture radius (pixels) | How close to a port a click or a dragged port must come to snap |
| Run LOM time limit (minutes) | Run LOM stops itself after this long (default 30) |
| Instance name labels: height µm | The component names (TCT1, R1, …) the build writes on the `instance_names` layer. Default 70 µm, 0 = none. KQC draws them 280 µm tall, and `qcc build` without `--label-height` still does. An annotation layer: the fab mask, the simulations and `design.json` do not change. A new value rebuilds the layout |
| Long dialogs in two columns | On (default): two columns when one would not fit. Off: one column, scrolled |
| Live PCells | See [Live PCells](#live-pcells-experimental-off-by-default) |

**Route dialog** (finish a route on a port, or double-click a route in Route handles):

![The route dialog of a hanger resonator: the route's rows left, the hanger coupler, targets and circuit right](../docs/images/plugin/dialog_route.png)

- *Name*, *Type* (cpw or meander), *Length µm* (meanders; the line under it is the bare λ/4 frequency), *Bend
  radius µm*.
- *Line width a* and *Line gap b*: **this route's own CPW**, the centre line and the gap on both sides, over its
  whole length. Empty takes the start port's.
- *Meander on straight*, *Meander turns*, *Meander first turn*: where the meander goes and how it folds.
- **Hanger coupler beside FL** (a route that ends beside a line): the coupler length on the line, the side, the end
  (short = λ/4, open), the *Ground strip* between the two lines, the open end's gap, and the direction.
  - The two **Coupler: … facing …** rows are not a second b. Each narrows one gap, along the coupler only: *this
    route's gap facing the line* (between its centre line and the ground strip) and *FL's gap facing this route*.
    Empty = that line's own b.
  - Narrower facing gaps bring the two centre lines closer by what they save: a stronger coupling (larger κ) at the
    same ground strip. The outer gaps keep b, and the line keeps its gap everywhere else.
  - Each must be > 0 and at most its line's b. A gap narrowed by more than the facing gap plus the ground strip is
    refused, because the etch would cut into the other line.
- *Merge into FL (T-junction)*: end on the line with a T instead of hanging beside it.
- *Targets* (f, κ, g, χ; empty = none) and the route's *Circuit* rows as the last build's LOM sees it.

**Hanger dialog** (Connect, finishing on a line): the same rows for a new resonator, the hanger coupler on the
right.

![The hanger dialog](../docs/images/plugin/dialog_hanger.png)

**Component dialog** (double-click a placed component, or Edit selected component): position, rotation and the
parameter table on the left; targets, the junction (simulation and LOM values, not drawn) and the circuit rows on the
right. The table scrolls on its own.

![The component dialog of an Xmon](../docs/images/plugin/dialog_component.png)

**Simulate** (Flow strip ▸ Simulate, or Simulate ▸ Simulate selected components): what is rendered, Q3D or
eigenmode, the solver settings (the fast values), and the run, export and Open simulation layout buttons, which stay
visible below the scrolled body.

![The Simulate dialog](../docs/images/plugin/dialog_simulate.png)

**Circuit picture** (LOM tab ▸ the circuit picture): opens fitted to its window. *Fit*, *100 %*, *−* and *+* zoom
it; it scrolls when it is larger than the window.

![The circuit picture window](../docs/images/plugin/circuit_window.png)


## Simulate, Results, Fab (`flow.py`, Flow strip steps 4 to 6)

**Simulate, automatic.** Select components with KLayout's own select tool, then *Simulate*. The **Simulate dialog**
(`flow.simulate_dialog`, logic in `simsetup.py`) shows what will be rendered and offers two analyses:
- **Q3D capacitance**: the selected qubits' islands and couplers as nets, the resonators cut to a stub port. This is
  preselected for qubits alone.
- **HFSS eigenmode**: exactly the selection (`guiflow.selection_group`, plus the routes joining selected parts and a
  line's end pads), junctions as lumped L‖C, pads and cut lines 50 Ω. This is preselected when a line, a resonator or
  a pad is selected (and when nothing is). **A junction without L_J blocks it**: the run and export buttons are
  disabled and the warning names the component, why, and where to set it (the component dialog's junction section).
  The rule is the library's (`guiflow.missing_junctions`: a design value, else the PDK value of a drawn trilayer
  junction): for a selection it reads the build sidecar's `instances.<name>.junction` (`Lj_eff_nH` empty, or an
  `error`), and with nothing selected it asks `qcc design junctions --default --json` about the default subset (the
  first qubit with its readout, `guiflow.resolve_selection`), in `jfetch.missing_default`.

**What will be simulated is drawn in the layout** (a *sim group overlay*, `simview.py`). While the Simulate dialog is open
the layout shows, for the chosen analysis: the **box** (purple, with group, analysis and size), the selected components
(green frames), the routes that stay in the simulation (green lines; grey where a route only passes through the box,
like a feedline it cuts), other components reaching into the box (grey, dashed) and the **ports**: junction (red), 50 Ω
terminations of pads and cut lines (blue), a cut resonator's stub port (orange, the stub from the component's port).
It follows the analysis you pick and goes away when the dialog closes. The panel's **Sim groups** tab lists the saved
`sim_groups` of design.json: click one to draw it (the analysis is a drop-down; *Hide* removes it). It is drawn again after each
rebuild and previewed again when the design changes. The overlay is plugin markers: never on a fab layer, never in any
export, and nothing is written to design.json. Its data come from `qcc sim preview DESIGN -i Q1,R1,FL -a hfss_eigenmode`
(or `-g GROUP`), the library's `guiflow.preview_groups`, which runs the same `build_simulation` as the export, so the
box, ports and routes equal the job folder's `job.json` and KQC json (`tests/test_kplugin_sim.py` compares them for an
eigenmode and two Q3D groups; about 2 s per call, in the background).

The dialog's solver settings (Q3D: ΔC %, passes, converged passes; eigenmode: modes, lowest frequency, Δf %, passes,
converged passes, refinement %, gap and junction-island mesh seeds) are filled with the library's fast values
(`simsetup.FAST`, checked against `sim_tools.export`), can be changed, are kept for the next run (*Reset to the fast
values*), and go to `qcc` as `--full --set key=value` (KLayout is for quick prototyping; driven / full-wave
S-parameter runs are for scripts). Simulate checks the exported geometry before AEDT starts
(`guiflow.check_export`, `sim_tools/geometry_check.py`). The dialog shows the last solve's convergence (`build/<name>/convergence.json`, written by
`guiflow.convergence_feedback` after each solve and each import) and can export the job only. For a converged run:
change the setup in AEDT and solve there, run the job's `scripts/qcc_collect.py` in that AEDT (exports what was solved,
no re-solve; or `qcc hfss collect JOB` in a new non-graphical AEDT), then *Import results* on the job folder: it is read
again when its AEDT outputs are newer than its results. Nothing selected: the default subset (the first qubit with its readout)
or the whole chip (slow, needs a lot of memory). `qcc sim auto` runs in the background (KLayout stays
usable; the status bar shows the step and AEDT's pass / mesh / convergence line): sim group written to design.json,
job exported with the fast solver settings, solved in a **new non-graphical AEDT** (tick the box for a visible window;
the AEDT you have open is never attached to or closed), then `qcc analyse`. When it ends the layout is rebuilt and the
Results window and tab show the values against the targets. Pressing Simulate while one runs offers to stop it (only the
AEDT it started). A small qubit + readout box takes about a minute.

**A run outlives KLayout.** The run is started detached (own process group, no console window, leaving the job
object KLayout may run in), with its output in `build/<name>.flow/sim_run.log` and a record
`build/<name>.flow/sim_run.json` (pid, start, state) next to the `sim_status.json` that `qcc` writes. Quitting KLayout
does not end it. When the design is opened again (or KLayout restarts with it), the plugin reads the record: a run that
ended meanwhile is imported at once (the layout is rebuilt and the Results tab filled; no question is asked, since
the run already analysed itself); a run still going is reported in the status bar and imported when it ends. A run
stopped from the panel (or ended without finishing) is shown as stopped or failed, with its log. When a run ends,
`qcc` also saves what the solve returned as `build/<name>/<name>_<group>_results.json`; **Import results…** (pick "A results.json file")
(Simulate menu) analyses any results file you pick, starting in that folder, without the job-folder question.

**Open simulation layout.** *Open simulation layout…* (Simulate menu, and a button of the Simulate dialog) shows exactly
what HFSS / Q3D import, without AEDT. It runs `qcc sim subset … --no-write-group -o <temp folder>` (the same library
path as *Export the job only*, with `--group` for a saved sim group) for the selection, the default subset, or, with
nothing selected, a choice between the default subset and a saved group; the analysis comes from the selection (as the
dialog recommends) or the group. The export goes to `%TEMP%\qcc_simlayout\<design>_<time>` (only the newest of a design
is kept) and the GDS that AEDT imports (`<sim>.gds`) opens in a **new layout tab**, not the design's view. Its layers
have readable names (`gap: etched, no metal`, `ground: metal`, `signal N: metal (net / port N)`), and the port polygons
of the job (`<sim>.json`) are added in memory as two layers: the junction sheet (lumped L‖C) and the 50 Ω / stub edge
ports. So you see the cut-out metal and gaps, the junction sheets and the port polygons. The design, its build and
`design.json` are never written (a saved group is exported as it is); closing the tab asks to save the in-memory port
layers (answer No). An eigenmode or driven layout runs the Simulate dialog's pre-check first (the selection, the
default subset or the group's qubits): a qubit without an L_J is not exported; a window names it, says where to set the
value (Edit selected component ▸ Junction) and offers **Open the Q3D layout instead**, which needs none.

**Simulate, manual.** *Export the job only* in the Simulate dialog writes the job folder (geometry, AEDT scripts, `simulation.bat`, `job.json`,
`results_template.json` and a `README.md` saying what to run and what to bring back). Solve it by hand in AEDT, or on
another machine. *Import results...* takes the solved folder or a `results.json`; the values are checked against the
design (net names, matrix shape) and analysed. The format, so you can write your own extraction script (`qcc results
template DESIGN` writes a skeleton with this design's net names; `--format` prints this):

```
{"analysis": "q3d_cmatrix",                       # or hfss_eigenmode / eigenmode_epr / hfss_driven
 "group": "gui_sim",                              # optional: the sim group; default the job's, else "chip"
 "cmatrix": {"labels": ["Q1.island", "Q1.claw_n"],# Maxwell capacitance matrix, one net per row / column:
             "unit": "fF",                        #   <instance>.island, <instance>.<port> or a route name
             "matrix": [[66.36, -3.18], [-3.18, 86.49]]},
 "eigenmodes": [{"mode": 1, "f_GHz": 5.31, "Q": 1.2e6}]}   # optional, for eigenmode runs
```

Command line: `qcc sim subset DESIGN -i Q1,R1 -o JOB` (export), `qcc sim auto DESIGN -i Q1` (automatic),
`qcc results import DESIGN JOB_OR_FILE`, `qcc results template DESIGN`.
Windows: the AEDT job folder must stay under about 140 characters (AEDT fails on paths over 260 characters). A deeper
design folder makes the automatic run use `%TEMP%\qcc_jobs` instead; *Export the job only* offers the same short folder
(or exports where you asked, for another machine), and `qcc sim subset` prints a `warning:` for such a folder.

**The sim group in design.json.** `qcc sim auto` and `qcc sim subset` write the group they simulate (`gui_sim`) into
design.json. The plugin notices any write to design.json made outside it: sim groups are kept as they are (Undo and
Redo carry them over, so undoing a drawing edit never drops the group the results belong to), and any other outside
change (a notebook, an editor) becomes one undo step and is rebuilt. *Apply* refuses to overwrite an edit made while
it ran.

**Results and tune.** *Results against targets* shows the latest values (the sidecar's `results`, the same rows as the
panel's Results tab; values from an older revision are marked stale). *Propose next revision* runs `loop.feedback` and
previews old -> new knob values; *Apply and rebuild* writes them to design.json through the session, so *Edit > Undo*
takes them back, and the layout rebuilds. It tunes every qubit that has a readout resonator in the circuit, for any
qubit class with a LOM model (Xmon, Swissmon, DoublePads, TwoPadTransmon, Flipmon, Gatemon, TransmonTaperedInsets, the
Metal pockets, crosses, star and concentric qubits, ...) and lambda/4 or lambda/2 readouts (shorted or open far end,
on a hanger or a free end): L_J for f_q, the class's island knob for alpha (Xmon `cross_length`, TransmonPocket
`pad_width`, ...), its coupler knob for g (Xmon `claw_length`, a pocket's `connection_pads.<pad>.pad_width`, a
PadCoupler's `pad_height`, ...) and the resonator length for f_r; only knobs whose target is set move. The table in
the docstring of `src/quantcore_circuits/codesign.py` lists the knobs per class. What cannot be tuned (a
junction drawn without an L_J in design.json, a readout drawn as a plain route without a length, a qubit with no
readout) is listed under *Not tuned* in the window instead of failing. The proposal is computed from the last
simulation's results, else from the layout's own LOM estimates; a second Propose, or one right after *Import results*,
reuses that analysis (`build/<name>/estimates_cache.json`) and takes a few seconds. Simulate again to check the result.

**Fab.** *Export for fab* writes the fab mask (`qcc mask`: negative mask on the Quantcore fab layers with the PDK frame,
100 um pad rule, cheese band and corner rounding), the netlist (`circuit.json`), `design.py` and a PNG into one folder (default `build/`, where the Flow strip looks for `<name>_fab.oas`).
*Design > Save as Python script* writes only `design.py` (`qcc design to-python DESIGN -o design.py`): the drawn chip as
a Designer script that writes the same design.json again (same `qcc design hash`), so a GUI prototype continues as
code. (The fab export puts the same script beside the mask, so the mask can always be traced to its source.)

## Icons

The artwork lives in `assets/` (`connect.png`, `Route Handles.png`, `move_snap.png`). `python kplugin/make_icons.py`
crops, squares and resizes each image to `icons/<tool-id>.png` (64×64). A menu item gets an icon automatically when
`icons/<menu-id>.png` exists. [icons/README.md](icons/README.md) lists the ids, with suggested pictures.

## Code

| File | Purpose |
|---|---|
| `python/qcc_kplugin/geometry.py` | Route preview, snapping and handle maths. Pure Python, unit-tested. |
| `python/qcc_kplugin/simview.py` | The sim-group overlay (Simulate dialog preview, panel's Sim groups tab) drawn from `qcc sim preview`. |
| `python/qcc_kplugin/design_io.py` | `design.json` edits: routes, waypoints, placements, snaps, instances, path → route. |
| `python/qcc_kplugin/session.py` | Design and sidecar tracking, commits and undo, the `qcc watch` / `qcc build` subprocesses (with a clean environment), view reload. |
| `python/qcc_kplugin/tools.py` | The three `pya.Plugin` tools and their factories. Structure follows KQC's `edit_node_plugin.py`. |
| `python/qcc_kplugin/server.py` | Command server. |
| `python/qcc_kplugin/dock.py` | Quantcore panel: Flow strip, component palette, LOM tab, DRC, results. |
| `python/qcc_kplugin/dialogs.py` | Dialogs that fit the screen: rows in one or two columns, a scrolled body with the buttons below it, resizable; windows capped to the screen. |
| `python/qcc_kplugin/jobs.py` | Background `qcc` subprocesses (status-bar progress, a chain of steps, `cancel()`, no modal dialogs from the timer). |
| `python/qcc_kplugin/qcache.py` | Cache (memory + one JSON file in the temp folder, keyed by the `qcc` path/time and the newest `src/quantcore_circuits/layouts` file) and background loading of the `qcc components` list, parameters and outline; the panel shows "loading…" instead of freezing. |
| `python/qcc_kplugin/jfetch.py` | Junction facts from the library through `qcc` (placement value with a background prefetch, the default subset's missing L_J). |
| `python/qcc_kplugin/simrun.py` | A `qcc sim auto` run that outlives KLayout: detached start, run record, pid / outcome checks (no pya). |
| `python/qcc_kplugin/menu.py`, `pymacros/qcc_kplugin.lym` | The menu (six submenus; `flow.ACTIONS` contract). |
| `python/qcc_kplugin/flow.py` | Simulate (automatic / manual export / import), Results, Propose / Apply, Fab export, Save as Python. |
| `python/qcc_kplugin/actions.py` | Menu actions. |
| `python/qcc_kplugin/pcells.py` | Live PCells (Settings): the `Quantcore` library, the build-backed geometry cache, the background `--oas` fetch, design.json sync. |

Tests: `tests/test_kplugin.py`, `tests/test_kplugin_flow.py`, `tests/test_kplugin_pcells.py`,
`tests/test_kplugin_junction.py` (the junction merge, the placement values, the pre-check, the sim-layout export).
`tests/test_instance_labels.py` checks
`qcc build --label-height`. Scripted smoke
tests drive the GUI in KLayout 0.30.3 and print PASS / FAIL per step:

- `gui_smoke.py` draws a Q1 + R1 chip with every tool: port → port, port → line, canvas → line, free ends, grid and
  Shift, node moves, the curvature handle, insert and delete, meander segment, undo / redo, duplicate, mirror, native
  moves and deletes; then the menu, the Flow strip, targets, Check and the LOM tab. Results:
  `%TEMP%\qcc_gui_smoke_*\smoke.txt`.
- `gui_smoke_flow.py`: Simulate (automatic, in a new non-graphical AEDT; stopping a run), the manual export / import,
  Propose / Apply / Undo and the fab export. Results: `%TEMP%\qcc_gui_flow_*\smoke.txt`.
- `gui_smoke_e2e.py`: the whole flow in one session through the menu paths and the Flow-strip buttons (Open → Check →
  LOM → Simulate → Results → Propose → Apply → Undo → Fab), checking the Flow marks after each step. Results:
  `%TEMP%\qcc_gui_e2e_*\smoke.txt`.
- `gui_smoke_pcell.py`: live PCells: the library, the swap after a build (geometry equal to the build), a Quantcore
  Xmon placed with KLayout's Instance tool, a parameter changed through the PCell API, undo / redo, native moves, the
  palette, off again. Results (with timings): `%TEMP%\qcc_gui_pcell_*\smoke.txt`.
- `gui_smoke_tutorials.py` (set `QCC_TUT`, default `t04,t02,t01,t03`): recreates the tutorial designs of
  `examples/tutorials/designs` through the GUI paths only (New design, the panel's component list, rotation, the edit
  dialog with its junction rows, Connect, Route handles, Rename, Chip settings, Add coupling), compares the result with the
  reference (design.json after the schema defaults, the built layers by XOR, the exported circuit) and runs Check,
  Run LOM, Save as Python and the Fab export on it. It never simulates. t03 is one part of the 17-qubit chip (two
  qubits with their coupler, airbridges and free-end readout routes). Results: `%TEMP%\qcc_gui_tut_*\smoke.txt`
  (PASS / FAIL, and GAP / DIFF for what the GUI cannot express or what differs from the reference).

Run each with its own `KLAYOUT_HOME` folder that holds a `klayoutrc` (an empty one stops at KLayout's tip dialog):
`klayout_app.exe -e -rm kplugin/load_dev.py -r kplugin/gui_smoke.py`.

KLayout notes for tool code: plugin tools get click and move events only (no press or release), and keys mostly go to
KLayout. So every key action is a Quantcore menu item with a shortcut, and right-click is the cancel gesture.

## Not done yet

- Freeform shapes → component capture (static OAS + ports + palette entry).
- Per-instance values on hover in the layout (the Results tab and window list them; the live dashboard, `qcc review`,
  shows the estimator spread).
- Snapping a component to a line (a route) while dragging: `place.snap` targets ports only.
- Node snapping offers the start port's angle; the end port's axis is not offered while drawing (use Ctrl and the node
  dialog).
- The termination of an existing free end is edited in the JSON (a new free end gets it in the route dialog; a
  node's taper a / b is in the node dialog).
- A node on a straight that sits closer to a corner than that bend's cut fails in KQC ("Straight segment cannot fit").
  The preview warns about it, but the router's own check does not catch it yet.

The status of the whole project is on the docs site (Overview ▸ Status).

Licence: GPL-3.0-or-later. The tool structure is derived from KQCircuits' `edit_node_plugin.py` (GPL-3.0).
