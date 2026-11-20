# KLayout and the plugin

Questions about the Quantcore plugin for KLayout: installing it, placing and editing parts, drawing routes, and what to
do when something does not respond. The guided pages are the [plugin page](../plugin/index.md) and the
[Q1 + R1 tutorial](../plugin/TUTORIAL_q1_r1.md).

## Installing and starting

### How do I install the plugin?

Link the `kplugin/` folder into KLayout's Salt folder and restart KLayout:
`mklink /J "%USERPROFILE%\KLayout\salt\quantcore-circuits" "<repo>\kplugin"`. A link, not a copy, so `git pull` updates it.
A **Quantcore** menu appears next to Help, with the toolbar tools Connect, Route handles and Move/Snap. See the
[plugin page](../plugin/index.md).

### Can I try it without installing?

Yes. `Designer(..., live=True)` or `quantcore_circuits.live.klayout.open_klayout()` start KLayout with the plugin loaded
from the repository (`klayout_app.exe -e -rm kplugin/load_dev.py`). See [KLive](../plugin/klive.md).

### I changed the plugin or library code and nothing happened. Why?

KLayout loads the plugin once at start, so restart it after a code change. The `qcc` calls the plugin makes pick up
library changes at once, but a rebuild can fail once while a file is half-saved: repeat it.

### Where do I set the `qcc` path and the other options?

**Quantcore > Settings...**: the `qcc` executable (empty means `qcc` on PATH, then the `qcd` env), the fallback grid, the
capture radius, the Run LOM time limit (default 30 minutes), the label height of the instance names (default 70 µm, 0 =
none), two-column dialogs and Live PCells. See the [tour](../plugin/tour.md).

### Where is the plugin log?

`%TEMP%\qcc_kplugin.log` gets every plugin message and placement click. Errors also pop up in a message box instead of
failing silently. Send it with a bug report.

## Placing and editing

### How do I place a component? Drag and drop does not work.

It is not drag and drop. In the panel's Components tab, pick the library (`quantcore`, `kqc`, `metal`, `all`), click a
cell to see its parameters, then **double-click** it. An outline with its ports follows the mouse. Click once to drop it;
Esc cancels. After about two seconds the layout rebuilds. See [place and route](../plugin/place-and-route.md).

### How do I rotate a part? R starts the ruler.

KLayout keeps R for its ruler, so the plugin uses **[** and **]**: 90 degrees per press, while the outline follows the
mouse or while you drag a placed part. The angle is stored on the placed component (`place.rot`); change it later in the
component dialog. See [place and route](../plugin/place-and-route.md).

### Why do parts snap, and how do I change the grid?

Points snap to KLayout's own editor grid (set in KLayout's editor options). The grid in Settings is only a fallback for
when KLayout has none. A part dragged near a port snaps to it at the rotated angle (capture radius in Settings).

### How do I change a parameter after placing?

Select the component and press **Ctrl+Shift+Q** (Quantcore > Edit > Edit selected component...), or double-click it with
Move/Snap. The dialog holds position, rotation, the cell parameters, targets, the junction values and read-only circuit
rows. Only the values that differ from the defaults are written to `design.json`.

### Why do my components all sit in the top cell? Can I use KLayout's own tools?

The components and routes are cells the plugin rebuilds from `design.json`, not live PCells. Moves, rotations and deletes
made with KLayout's tools are written back to `design.json`; other edits last only until the next rebuild.
Settings > Live PCells (experimental, off by default) registers the Quantcore cells as a KLayout library for the
Instance tool. See the [plugin page](../plugin/index.md).

### A dialog is too big and I cannot see OK.

Every dialog scrolls, keeps OK and Cancel visible, can be resized, and opens in two columns when one column would not fit.
Turn two columns off in Settings if you prefer one.

## Routes

### How do I draw a route and edit its nodes?

Use **Connect**: click a port (or empty canvas for a free end), click nodes, finish on a port or on a line. Hold **Shift**
to snap segments to 0, 45, 90 degrees and so on. **Route handles** shows every corner as a filled square (move, delete,
or double-click it) and an insert handle as a hollow square on each straight. Delete a node with Ctrl+Shift+X; the node
dialog (Ctrl+Shift+N) sets its radius and airbridge. See [place and route](../plugin/place-and-route.md).

### The preview of a route was square but the placed route came out slanted.

The click keeps the corner the preview showed. Without Shift each segment turns once with a square corner; with Shift
it goes at the nearest 45 degrees. If the placed route still differs from the preview, restart KLayout.

### How do I edit a meander or hanger after drawing it?

A route is not a component, so it has its own dialog: double-click the route in Route handles or in Move/Snap, or select
it with KLayout's Select tool and press Ctrl+Shift+Q. It holds the meander length, coupler length, side, end, bend radius,
which straight carries the meander, and the gaps along the coupler.

### A route shows dashed red and is missing from the layout.

The plugin builds with `--keep-going`: a route that cannot be built is left out, drawn dashed in red with the reason next
to it (for example a leg shorter than its two bends need). Move a node or lower the bend radius. See
[routing and DRC](routing-drc.md).

### How do I put a resonator next to the feedline?

In Connect, start on a qubit port or on empty canvas, add nodes, then click **on the feedline**. The route dialog asks for
the meander length, coupler length, side and whether the end on the line is shorted (lambda/4) or open. You do not place
separate short or open parts. See [place and route](../plugin/place-and-route.md).

## Flow and results

### Where are the steps Check, LOM, Simulate, Results and Fab?

On the panel's Flow strip, one button per step with a mark (done, out of date or with issues, not done). The menu follows
the same order. See [the flow strip](../plugin/flow-strip.md).

### Can I start a simulation from KLayout?

Yes: Simulate selected components. Eigenmode from this dialog and a visible AEDT window were never run from the GUI; Q3D
of one qubit in a new non-graphical AEDT was. See [Simulation](simulation.md).
