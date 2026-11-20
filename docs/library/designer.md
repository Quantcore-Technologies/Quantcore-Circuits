# The Designer API

`Designer` (`src/quantcore_circuits/designer.py`) is the way to design a chip in Python. You add components, connect
them with routes, and ask for the layout, the checks and the simulations. Every change is validated at once, and the
result is an ordinary `design.json` that the KLayout plugin, the command line and the dashboard read unchanged.
Use it when you prefer a script or a notebook to clicking in KLayout; the [tutorials](../tutorials/index.md) use it
throughout.

## Create a chip

```python
from quantcore_circuits.designer import Designer

d = Designer("t00_quickstart", box=(0, 0, 7500, 7500), chip={"name_chip": "QS1"}, live=False)
```

| Argument | Meaning |
|---|---|
| `name` | Design name; the layout is written to `build/<name>.oas` (`out=` changes it) |
| `box` | Die box `(x0, y0, x1, y1)` in µm |
| `pdk` | PDK name; the default is the sapphire PDK (see [PDK](pdk.md)) |
| `chip` | Chip parameters, for example `{"name_chip": "QS1"}` (the device ID) |
| `launchers` | A launcher preset, when you want the chip's own pads (`d.chip_ports` lists them as `chip.<name>`) |
| `live` | `True`: every change is rebuilt and redrawn in KLayout through klive |

With `live=True` and KLayout installed, `Designer` starts KLayout if it is not running. With `live=False` nothing is
drawn until you call `d.show()`. To open a saved design use `Designer.load("examples/my_chip.json")`; it does not
rewrite the file unless `live=True` or you pass `autosave=True`.

## Add components

```python
pw = d.add("PAD_W", "BondPad", at=(1125, 3750), rot=270, edge="auto")
pe = d.add("PAD_E", "BondPad", at=(6375, 3750), rot=90, edge="auto")
q1 = d.add("Q1", "Xmon", at=(2975, 2100), cross_length=450, arm_width=25, gap=25, claws=["n"],
           junction={"Lj_nH": 12, "Cj_fF": 2})
```

- The second argument is a cell name (`Xmon`), a KQC class name, or `metal:<Class>`; see
  [Components](components.md). An unknown cell or parameter raises an error that lists the valid names.
- `at=` and `rot=` place the instance in µm and degrees. `mirror=True` flips it.
- `edge="auto"` (or `"n"`, `"s"`, `"e"`, `"w"`) applies the PDK pad rule: the instance slides until its etch edge is
  100 µm from that die edge.
- `snap="port"` with `to="other.port"` places the instance by joining two ports; the build solves the rotation.
  `snap_gap` adds a distance.
- `junction={...}` holds the lumped junction values (`Lj_nH`, `Cj_fF`, `flux_phi0`, `asym`). Without `Lj_nH` the
  PDK value of the drawn trilayer junction is used.
- Any other keyword is a cell parameter. `d.array(...)` places a grid of copies.

The handle that `add` returns gives the ports as attributes: `q1.claw_n`, `pw.a`. Change an instance later with
`q1.set(cross_length=500)` or `q1.move(at=(3000, 2100))`; each change is one rebuild. `d.remove("Q1")` removes it
and the routes that end on it.

## Connect with routes

`d.route(name, start, end, ...)` draws a coplanar waveguide (CPW) between two ports and returns a handle.

```python
fl = d.route("FL", pw.a, pe.a)                                   # a plain CPW
r1 = d.route("R1", q1.claw_n, fl.hanger(near=(3125, 3750), length=300, side="right"), meander=4500, r=50)
```

| You want | Write |
|---|---|
| A plain waveguide | `d.route("FL", a, b)`; `nodes=[(x, y), ...]` adds waypoints |
| A resonator of a given length | `meander=<length in µm>`: the route gets exactly that length |
| A hanger readout on a feedline | the end is `fl.hanger(s=..., length=..., side="left" or "right")`, or `near=(x, y)` instead of `s` |
| A free end | the end is `Designer.free_end((x, y), dir=..., term=...)` |
| Another bend radius or line width | `r=`, `a=`, `b=` |
| Airbridges | `airbridges=...`, or `Designer.waypoint(at, airbridge=True)` as a node |
| The first turn the other way | `meander_direction=-1` |

A hanger (`RouteHandle.hanger`) is a lambda/4 coupler that runs along another route. Its `length` is the coupler
length, `end="short"` shorts the far end, and `coupler_gap` / `line_gap` narrow the facing gaps to couple more
strongly. After a build, `r1.length` is the drawn length in µm. `r1.set(meander=4400)` changes it.

```{note}
Length fixing: if the path as drawn is within 0.01 µm of the target, no meander is added. If it is slightly short,
the radius of its free corners is trimmed by up to 5 %. Otherwise a KQC meander is inserted, with no more turns than
keep it at least one bend radius wide, so it never flattens into a zigzag. A target shorter than the shortest path
raises an error. More on [Routing and DRC](routing-drc.md).
```

## Batch several changes

```python
with d.batch():
    d.add("Q2", "Xmon", at=(4400, 2100), claws=["n"])
    d.add("Q3", "Xmon", at=(5400, 2100), claws=["n"])
```

Inside `batch()` the layout is rebuilt once, when the block ends. With `live=True` this keeps KLayout from redrawing
after every line.

## Couplings and targets

- `d.couple("K12", "Q1", "Q2", C_fF=5.0)` declares a lumped coupling that no route or snap carries, for example two
  qubit arms facing each other. Use `L_nH=` for an inductance, or `wire=True` for a galvanic join of two ports.
  `d.couple("K_R1", "R1", "FL")` names a hanger coupling against its feedline; a C-matrix fills the value later.
- `d.targets(Q1={"f_q_GHz": 5.5}, R1={"f_GHz": 7.0})` stores what you want. The analysis compares results with it.

## Sim groups

A sim group is the part of the chip that one simulation solves. See [Simulation](simulation.md).

```python
group = d.sim_subset("Q1R1", pairs=[("Q1", "R1")], margin_um=300, analyses=["q3d_cmatrix", "eigenmode_epr"])[0]
d.sim_group("pair", select=["Q1", "Q2", "R1", "R2"], margin_um=300)       # chosen by hand
```

`sim_subset` picks each qubit with its readout chain and cuts the feedline at the box; `sim_group` takes exactly the
instances and routes you name. Both only record the group in the design. Export the job with
`sim_tools.export.export_job` or `qcc sim subset`.

## Save, load, build, show

```python
d.save("examples/my_chip.json")        # design.json (schema qcc/0.1)
result = d.show()                       # build, write build/<name>.oas (+ sidecar), redraw KLayout if live
```

`d.design` is the validated design object, `d.result` the last build, and `d.history` lists the changes made. To
draw a picture without KLayout, render the built layout headless:

```python
from quantcore_circuits.live.snapshot import snapshot
snapshot(d.result, "chip.png", size=(1200, 1200), box=(2425, 1550, 3525, 2650))   # box in µm zooms in
```

In a live session, `gui_snapshot(png, size, layout=d.out)` screenshots the KLayout window instead, and falls back to
the headless render when the plugin cannot be reached.

Both hide the helper layers of every face (`HIDE` in `quantcore_circuits.live.snapshot`: the KQC centre lines
`waveguide path`, `ground grid avoidance`, port texts, refpoints and annotations), so a flip-chip or TSV picture has no
centre lines drawn over the `2b1`, `1b1` or `2t1` routes. The Quantcore layer properties (`layer_props_path()` in the
same module, also loadable in KLayout with File > Load Layer Properties) show every face the way they show `1t1`, with
the cheese visible. To leave out a whole face as well, pass `hide=HIDE + ("1b1",)` to `snapshot`.

## Check, LOM, simulations

| Call | What it gives |
|---|---|
| `d.drc()` | A `DrcReport` of errors, warnings and PDK design warnings ([Routing and DRC](routing-drc.md)) |
| `d.lom()` | The layout as a lumped circuit; `.model` is the netlist ([LOM](lom.md)) |
| `sim_tools.export.export_job` | A job folder for Q3D, HFSS, Elmer, Palace or Sonnet ([Simulation](simulation.md)) |
| `loop.analyse`, `loop.feedback` | Results into one consensus, then the next revision ([Feedback](feedback.md)) |
| `layouts.wafers.fab_export.export_fab` | The mask file ([Fab export](fab.md)) |

The tutorials run the LOM simulation with their helper module: `res = C.simulate_lom(d.lom(), d.design)` (`C` is
`_common`); the library function behind it is `lom.simulate.simulate`.

```{tip}
Design warnings (`pad_edge`, `pdk_rn`, `pdk_fq`, `pdk_claw`) never block a build or an export. A change that fails
validation is rolled back with the reason. A change that is valid but cannot be routed yet (a route to a component
you have not placed) is kept, and a live session keeps the last good layout on screen and prints why.
```

See also the [first chip in Python](../getting-started.md) and the [flow](../overview/flow.md).
