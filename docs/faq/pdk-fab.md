# PDK and fab

Questions about the Quantcore process rules and the mask the fab receives. The pages are [PDK](../library/pdk.md) and
[fab export](../library/fab.md).

## The PDK

### What does the PDK fix?

One place for the Quantcore process: the stack (Nb on 650 µm sapphire, relative permittivity 10.25; a silicon variant
`quantcore_nb_si_v1` is kept for comparison), the fab layers, the die frame, the pad rule, the keep-outs, the cheese,
corner rounding, the trilayer junction process and the kinetic inductance. `get_pdk()` returns it; every build uses it
unless the design names another. See [PDK](../library/pdk.md).

### Which layers does the fab mask use?

The Quantcore negative-mask layers: 1 to 4, 50 to 53, 100, 300 / 301, 700, 800+, 500 / 501 (wafer level) and 1000+ (layer/datatype pairs such as 1/0 and 3/0). `qcc mask --positive LAYER` inverts one layer. The export writes only the PDK fab layers,
flat, and reports the layers it dropped. See [fab export](../library/fab.md).

### What is on the die frame?

A dicing L, alignment grids, an optional device ID and the brand `QCT`. The device ID is optional. Components and routes that touch a frame marker area or the ID raise a `frame_keepout` warning.

### What is the 100 µm pad rule?

The outer edge of a pad's etch sits 100 µm from the die edge. Place a pad with `edge="auto"` and it moves there. A pad
that is off the rule is a `pad_edge` design warning; in the plugin, Check > Fix pad edge warnings sets `edge="auto"` on
all flagged pads. When a design's own pad position and the rule disagree, the PDK rule wins. See
[PDK](../library/pdk.md).

### Why is a design warning not an error?

Margins against the PDK (`pad_edge`, `pdk_rn`, `pdk_fq`, `pdk_claw`) are flagged, never enforced, so a chip outside the
band still builds and exports. Read them as "check this on purpose". See [routing and DRC](routing-drc.md).

## Keep-outs, cheese and rounding

### What are the 3/0 keep-outs?

Layer 3/0 is the etch around the metal. Around a route it extends 10 µm, around a component 24 µm, and around any other
shape 9 µm; a cell's own keep-out grows by the same 4 µm step. 3/0 comes from the extended bounding box, and the 1/0 metal
stays in the middle when the mask is exported: think of it as etching the features of 1/0 plus a margin.

### What is the cheese?

Small squares that thin out the metal (flux-trapping holes): 5 µm squares, 20 µm gaps, three rows, in a band 4 µm outside
the 3/0 keep-out. The holes are put on both 1/0 and 3/0. If a design carries its own cheese, the original cheese wins
over the PDK band. See [PDK](../library/pdk.md).

### Why do the KQC example chips have no cheese?

Cheese belongs to the fab export, not to the layout or to simulation: simulation exports never get cheese or rounding.
The PDK band is added when you export for fab (unless the design has its own cheese), so a chip does not need it in its layout.

### Are corners rounded?

Yes, by default in the fab export (`--no-round` switches it off). Simulation exports never round. Routes can also have
their own radius per corner. See [fab export](../library/fab.md).

### How do I export for fab?

| Route | How |
|---|---|
| Python | `export_fab(T.built(d), "build/<name>_fab.oas", report=report)` |
| CLI | `qcc mask DESIGN [-o OUT] [--positive LAYER] [--no-cheese] [--no-round]` |
| Plugin | Quantcore > Fab > Export for fab: a bundle with `<name>_fab.oas`, `circuit.json`, `design.py` and a PNG |

The plugin refuses while a route has failed. See [fab export](../library/fab.md).

### Can I still rebuild old designs after a PDK change?

That is the goal: the library and PDK must rebuild every existing design. When a rule changed (3/0 keep-outs, cheese on
3/0), all example fab exports were compared before and after. Wafer assembly (dies on a wafer) is
described in [Wafer assembly](../library/wafer.md); a mask set is not built. See [status](../overview/status.md).
