# Scripted design with KLive

`Designer` (`src/quantcore_circuits/designer.py`) is the code-first route to a chip. You add components and routes in
Python, in a script or a notebook, and KLayout shows the chip as you go. Use it when you prefer code to clicking or
when a loop generates the design. It writes the same `design.json` as the [plugin](index.md), so you can switch
between the two.

Ports are attributes (`pw.a`, `q1.claw_n`), every change is validated, and with `live=True` KLayout redraws after each
change (about 0.1 s per change when measured). The full API is a guided walk-through on the
[Designer page](../library/designer.md).

## A first chip

These steps are Tutorial 0 ([quickstart tutorial](../tutorials/00-quickstart.md)). Each one gives a picture.

```python
from quantcore_circuits.designer import Designer

d = Designer("t00_quickstart", box=(0, 0, 7500, 7500), chip={"name_chip": "QS1"}, live=True)
```

```{figure} ../images/klive/t00_die.png
:width: 50%

An empty 7.5 x 7.5 mm die: the PDK frame (dicing L at the corners, alignment grids) and the device ID `QS1`.
```

```python
pw = d.add("PAD_W", "BondPad", at=(1125, 3750), rot=270, edge="auto")   # edge="auto": the 100 um pad rule
pe = d.add("PAD_E", "BondPad", at=(6375, 3750), rot=90, edge="auto")
fl = d.route("FL", pw.a, pe.a)                                         # CPW, PDK default 10/6 um
```

```{figure} ../images/klive/t00_pad.png
:width: 50%

A bond pad after `edge="auto"`: it slid out until the outer edge of its etch is 100 µm from the die edge.
```

```python
q1 = d.add("Q1", "Xmon", at=(2975, 2100), cross_length=450, arm_width=25, gap=25, claws=["n"], junction=junction, **params)
r1 = d.route("R1", q1.claw_n, fl.hanger(near=(3125, 3750), length=300, side="right"), meander=L_R1, r=50)
d.targets(Q1={"f_q_GHz": 5.5}, R1={"f_GHz": 7.0})
```

```{figure} ../images/klive/t00_qubit.png
:width: 50%

The Xmon with its trilayer junction and one readout claw.
```

```{figure} ../images/klive/t00_chip.png
:width: 60%

The finished chip: two pads, the feedline, the Xmon and its lambda/4 readout hung on the feedline.
```

`junction` and `params` come from `layouts.registry.trilayer_junction("Xmon", lj_nH=...)`; `L_R1` is the bare lambda/4
length. See the tutorial for both.

## What you can call

| Call | What it does |
|---|---|
| `Designer(name, box=, chip=, live=)` | Start an empty die. `Designer.load(path, out=)` opens a saved `design.json` |
| `d.add(name, cell, at=, rot=, edge=, **params)` | Place a component; returns a handle with its ports |
| `d.route(name, a, b, meander=, r=, nodes=)` | CPW between two ports; `fl.hanger(...)` is a lambda/4 coupler on a line |
| `d.waypoint`, `d.free_end`, `d.couple` | Waypoints, free line ends, couplings |
| `d.targets(...)` | Targets the LOM and the dashboard compare against |
| `d.sim_group(...)`, `d.sim_subset(...)` | Simulation groups (see [simulation](../library/simulation.md)) |
| `d.batch()` | Many edits, one rebuild |
| `d.lom()`, `d.drc()` | The lumped netlist and the DRC report |
| `d.save(path)`, `d.show()` | Write `design.json`; build and send to KLayout |

Handles also have `.set(...)`: `q1.set(junction=junction, **params)` is one change and one rebuild.

## KLive and the command line

- klive is a small KLayout Salt package that listens on port 8082. `live=True` sends each rebuild to KLayout through the klive package (port 8082). `live.klayout.open_klayout()`
  starts KLayout with the plugin if no window is open and brings it to the front.
- `qcc build DESIGN --show` builds a design and opens it in KLayout. `qcc watch DESIGN` rebuilds on every save, with a
  debounce, and keeps the last good layout when a save is broken.
- Switches: `QCC_LIVE=0` turns live off (builds are headless), `QCC_KLAYOUT_GUI`, `QCC_KLAYOUT` (path).
- `live.snapshot.snapshot(oas, png, size=, box=)` renders a layout headless; `gui_snapshot()` asks the plugin's command
  server (port 8083) for a picture of the real window.

```{figure} ../images/klive/t00_klayout_view.png
:width: 50%

What the notebooks call "the KLayout window": a headless render of the view with KQC colours, made by
`live.snapshot.snapshot`. It is not a screenshot of the KLayout window; for that, see the [plugin tour](tour.md).
```

## Limits

- There is no screenshot of KLayout open next to a Jupyter notebook during a live session yet.
- `Designer.load(..., live=True)` does not autosave to its source file.
- Verified: the live loop, and opening, reopening and raising the KLayout window. "KLayout in front" still needs a
  check on an unlocked desktop.
- klive needs its Salt package in KLayout. Without it KLayout is open but nothing listens on port 8082, and the
  rebuild is not shown. The plugin itself does not need klive.
