# Routing and DRC

Questions about how routes are built, why one fails, and what the DRC counts as an error. The reference is
[routing and DRC](../library/routing-drc.md).

## Routes

### How is a meander given the right length?

The router's `fix_length` adds meander turns on one straight of the route until the line has the length you asked for.
Choose the straight in the route dialog ("Meander on straight": automatic is the longest free straight, or pick one by its
length). The dialog shows the bare lambda/4 frequency for the length and your substrate's permittivity; the real frequency
is lower because the claw and coupler load the line. See [routing and DRC](../library/routing-drc.md).

### Why did a route fail to build?

The usual causes, each reported with its reason:

- a straight leg shorter than the two bends at its ends need (leg 40 µm, bends needing 200 µm at r = 100 µm);
- a node closer to a corner than the bend's cut ("Straight segment cannot fit");
- a waypoint on a port axis between r and 2r;
- a meander that no longer fits on its straight (the router moves it to the next longest one).

Lower the bend radius, move a node, or add a corner. These router limits are listed as open items on
[routing and DRC](../library/routing-drc.md).

### What happens to a failed route?

`qcc build --keep-going` (what the plugin uses) leaves the route out, reports it, and keeps the last good path in
`build/<name>.last_good_routes.json`. Plain `qcc build` is strict and stops at the first bad route. A failed route is a
`route_failed` DRC error, and the plugin's fab export refuses while one exists.

### How do routes cross?

A line that crosses another is split into sections joined by `AirbridgeConnection` instances. The DRC error `crossing`
reports a crossing that has no bridge, and `airbridge_short` a bridge pad that lands on another line. Tutorial 3 (17 qubits) shows it.
See [routing and DRC](../library/routing-drc.md).

### Can a route start or end on empty canvas?

In the plugin, yes: a free end (open by default; shorted for a lambda/4). From Python the route has a free end too. A route
that starts on a port always snaps to that port first. See [place and route](../plugin/place-and-route.md).

### Can a bend have its own radius?

Yes. Each route node takes an optional radius, applied to that corner only; the route has one default radius otherwise.
In the plugin select a corner in Route handles and use the curvature handle or the node dialog.

## DRC

### What is the difference between a DRC error, a warning and a design warning?

| Class | Examples | Meaning |
|---|---|---|
| error | `outside_chip`, `crossing`, `route_overlap`, `route_self_overlap`, `route_over_component`, `route_failed`, `open_conductor`, `airbridge_short`, netlist opens and shorts | The layout is wrong; fix it before fab |
| warning | `dangling_port`, `no_lom`, `overlap`, `route_clearance`, `frame_margin`, `frame_keepout` | Probably unintended; check it |
| design | `pad_edge`, `pdk_rn`, `pdk_fq`, `pdk_claw` | A margin against the PDK. Never an error and never enforced; a chip can build and export with them |

Every rule and its severity is listed on [routing and DRC](../library/routing-drc.md).
The DRC runs on every build and is stored next to the layout; the plugin shows it in the DRC tab (click a line to zoom to
its marker).

### How do I run the DRC?

In Python `d.drc()`; on the command line `qcc design drc DESIGN` (add `qcc design netlist` for the geometric netlist);
in the plugin Check (Ctrl+Shift+D). The notebooks print the report as a table, for example
`DRC clean - 0 errors, 1 warnings, 0 PDK design warnings`.

### I get `pad_edge` warnings on every pad. How do I clear them?

A pad's outer etch edge must be 100 µm from the die edge. Set `edge="auto"` on the pad (the plugin's Check > Fix pad edge
warnings does it for every flagged pad). See [PDK and fab](pdk-fab.md).

### What is `dangling_port`?

A port with no route or snap. It is a warning, not an error, because a spare port is often meant. See
[components](components.md) for what an open pin does in the LOM.

### Can I validate or rebuild a design file from the command line?

`qcc design validate FILE` checks the schema, `qcc design hash FILE` gives its canonical hash, `qcc design to-python FILE`
writes a Python script that rebuilds it, and `qcc build FILE` builds the layout. See [the CLI reference](../reference/cli.md).
