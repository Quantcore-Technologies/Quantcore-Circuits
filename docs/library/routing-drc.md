# Routing and DRC

This page covers three things: the `design.json` file, how a design becomes a layout with its routes, and the design
rule check (DRC) that reports what is wrong. You need it when a route fails, when the DRC shows a warning you do not
understand, or when you want to read or write `design.json` yourself.

## design.json

`design.json` (pydantic schema `qcc/0.1`, `design/schema.py`) holds `instances` (cell, params, `place`, junction),
`routes` (CPW or meander, nodes, hanger and free ends), `chip`, `targets` and `sim_groups`. `qcc design validate` checks
a file, `qcc design hash` gives its canonical hash, and `qcc design to-python` writes a Python script that rebuilds it
(a round trip, checked on 105 examples on 2026-11-15). A field reference is not written yet (a table can be generated
from `Design.model_json_schema()`).

## Build and routing

`assembly.build(design, keep_going=, last_good=)` solves the snaps in dependency order, applies the pad rule and
junction defaults, and gives a KQC `DesignChip`. `route/router.py` plans routes: waveguides, meanders (`fix_length`),
hangers, free ends, T-merges, airbridges and per-corner radii. `qcc build DESIGN [--keep-going --label-height --show]`
is the command.

```{figure} ../images/routing/t04_pair.png
:width: 50%

Two lambda/4 readouts, each a meandered route from a qubit claw to a hanger on the shared feedline (tutorial 4).
```

```{figure} ../images/routing/t02_buses.png
:width: 55%

Lambda/2 bus resonators with tees and individual readout lines (tutorial 2, the IBM bowtie).
```

```{figure} ../images/routing/t02_triangle.png
:width: 50%

One triangle of the bowtie: two pockets, the tee and its stubs, the bus meander.
```

```{figure} ../images/routing/t03_bridge.png
:width: 50%

Airbridges (orange) over a crossing: a line crossing another is split into sections joined by `AirbridgeConnection`
instances (tutorial 3).
```

```{figure} ../images/routing/t03_module.png
:width: 50%

A readout module of the 17-qubit chip: hairpin readout, Purcell filter and tee with bridged lines.
```

Angled ports and the rotation snap are shown on the [plugin tour](../plugin/tour.md); failed routes are shown there too.
With `--keep-going` (what the plugin uses) a route that cannot be built is left out and reported, and the last good
path is kept in `build/<name>.last_good_routes.json`. Plain `qcc build` is strict and stops at the first bad route.

### Length fixing

A route with a target length (a meander) goes through `route/router.fix_length`, which compares the target with the
path as drawn:

- within 0.01 µm: the path is kept and gets no meander;
- slightly short: the radius of its free corners is trimmed by up to 5 %;
- otherwise: a KQC meander on the longest free straight, with no more turns than keep it at least one bend radius
  wide, so it never flattens into a zigzag. If fewer turns than you asked for fit, a warning says so.

A target shorter than the shortest path is an error.

### Known limits

A node closer to a corner than the bend's cut fails in KQC ("Straight segment cannot fit"), and a waypoint on a port
axis at a distance between r and 2r fails. Both are open items of the router; a route that hits one is reported and, with `--keep-going`, left out.

## DRC and netlist

`assembly.drc.check(source, netlist=True)` returns a `DrcReport` of `DrcIssue(severity, rule, message, where,
objects)`. The fast DRC runs on every build and is stored in the sidecar; `netlist=True` adds the KQC geometric netlist.

| Severity | Rules |
|---|---|
| error / warning | `dangling_port`, `no_lom`, `outside_chip`, `overlap`, `crossing`, `route_overlap`, `route_clearance`, `route_self_overlap`, `route_over_component`, `route_failed`, `open_conductor`, `airbridge_short`, `frame_keepout`, netlist opens and shorts |
| design (never enforced) | `pad_edge`, `pdk_rn`, `pdk_fq`, `pdk_claw` |

Commands: `qcc design drc`, `qcc design netlist`, `Designer.drc()`, the plugin's Check. In the notebooks the report is a
Markdown table:

```text
DRC clean - 0 errors, 1 warnings, 0 PDK design warnings
| severity | rule | count | example |
| warning | dangling_port | 1 | Q1.claw_n is not connected (no route or snap) |
```

(tutorial 0, section 5). The DRC tab with markers is shown on the [plugin tour](../plugin/tour.md).

Design warnings never block a build or an export; they tell you where the design is outside the PDK margins (see the
[PDK page](pdk.md)). The `pad_edge` rule counts `Launcher`, `LauncherDC` and `TaperedPad` cells as bond pads. Errors
and warnings are the checks of the design itself: a dangling port, an overlap, a route over a component. The cheese is
not part of the DRC: it is added at build and fab time ([Fab export](fab.md)).
