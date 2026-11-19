# Fab export

The fab export turns a built design into the mask file the fab expects: only the PDK's fab layers, with the layer
polarity, the cheese, the 3/0 keep-outs and rounded corners. Use it when a design is final. It writes one OAS file
(and, from the plugin, a bundle). The layer map and the rules are on the [PDK page](pdk.md).

`layouts/wafers/fab_export.export_fab(result, out, polarity, report=, cheese=, rounding=)` writes the mask and fills
`report` with the layers it dropped.

| Route | How |
|---|---|
| Python | `export_fab(T.built(d), "build/t00_quickstart_fab.oas", report=report)` |
| CLI | `qcc mask DESIGN [-o OUT] [--positive LAYER] [--no-cheese] [--no-round] [--grid]` |
| Plugin | Quantcore > Fab > Export for fab: a bundle with `<name>_fab.oas`, `circuit.json`, `design.py` and a PNG. It refuses while a route has failed |

The cheese is the build's own; if the design has none, the PDK band is used (also on 3/0). Simulation exports never get
cheese or rounding.

```python
report = {}
fab = export_fab(T.built(d), "build/t00_quickstart_fab.oas", report=report)
T.md(T.fab_report_md(report, fab))          # which layers were written, which dropped
```

```{figure} ../images/fab/mask_t04.png
:width: 80%

The fab mask of the tutorial 4 chip (headless render of `build/t04_two_qubit_user_fab.oas`): two pads, feedline, two
readouts and qubits, device ID `QS2`, frame marks at the corners. Pink and blue hatching are different layers; the dots
are the cheese band.
```

```{figure} ../images/pdk/fab_qubit.png
:width: 45%

Close-up of a qubit in the fab file: etch, 3/0 keep-out and cheese.
```

```{figure} ../images/pdk/fab_tips.png
:width: 45%

The facing arm tips of the two Xmons (tutorial 4): rounded corners and the cheese band between them.
```

## Limits

- 105 example exports were compared on 2026-11-17 after the 3/0 and cheese changes.
- Wafer assembly (dies on a wafer) is in [Wafer assembly](wafer.md); a mask set (several chips with test structures and
  per-layer reticles) is not built.
- The dashboard has no Fab step.
