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
cheese or rounding. Either way the holes stay in the ground plane (not in floating pads or islands), and no hole lands
on or next to a TSV, an indium bump, under-bump metal or an airbridge; these are not written on 3/0.

On 3/0, a whole KQC chip placed as one instance (for example `Stripes`, `JunctionTest` or `Empty` in
`examples/designs/kqc/test_chips`) gets its etch grown by the 9 µm margin. A keep-out of its bounding box would cover
nearly the whole die and leave the cheese only a thin band at the die edge. The same holds for any cell over more than
half the die.

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

- 105 example exports were compared after the latest 3/0 and cheese changes.
- Wafer assembly (dies on a wafer) is in [Wafer assembly](wafer.md); a mask set (several chips with test structures and
  per-layer reticles) is not built.
- The dashboard has no Fab step.
