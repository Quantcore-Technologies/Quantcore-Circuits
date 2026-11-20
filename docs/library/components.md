# Components

A component (a cell) is one drawn element of a chip: a qubit, a pad, a coupler, a capacitor, a junction. You place
one with `Designer.add("Q1", "Xmon", ...)`, with the KLayout plugin's component panel, or as a `cell` in
`design.json`. This page says where the 145 components come from, how to read a cell's page, and how to add your own.

## Three sources

| Source | How you name it | Count | Notes |
|---|---|---|---|
| Quantcore cells | the class name: `Xmon`, `BondPad` | 59 | Re-implementations of the legacy QWri macros and of QPDK and SQDMetal cells, drawn natively on KQCircuits. They know the Quantcore layers and rules |
| KQCircuits (KQC) classes | the bare class name: `Swissmon` | 45 | KQC's own library, used unchanged |
| Qiskit Metal | `metal:<Class>`: `metal:TransmonPocket` | 41 | Quantum Metal `qlibrary` components, with the Metal options as parameters. Metal is imported only when such a cell is built |

`layouts.registry.resolve_cell` accepts any of these, and also a dotted class path such as
`kqcircuits.qubits.swissmon.Swissmon`. The counts come from the catalog below;
113 of the 145 have a LOM model (see [LOM](lom.md)). `qcc components` lists them, and `qcc components Xmon` prints one
cell's ports.

## Read a cell page

The generated [component reference](../components/cells/index.md) has one page per cell. Each shows:

1. The pins first. The ports of a default instance: name, position (µm, in the cell's own frame), direction
   (degrees, pointing out of the cell) and the CPW width `a` and gap `b` it expects. A route refers to a pin as
   `INSTANCE.pin`, for example `Q1.claw_n`. A pin without a direction marks a point and cannot be snapped to.
2. The parameters, with defaults and units. Only changed ones are stored in `design.json`.
3. The LOM model, when there is one.
4. How to place the cell.

Two pins connect when their directions face each other and their `a` and `b` match; the DRC warns otherwise (see
[Routing and DRC](routing-drc.md)). The plugin's own status of each cell is on
[the plugin components page](../plugin/COMPONENTS_STATUS.md).

## Flip-chip and TSV cells

A KQC chip stack has four metal faces: `1t1` (the bottom chip's front), `1b1` (its back), `2b1` (the top chip's front,
facing down) and `2t1` (the top chip's back). Three cells carry a CPW line from one face to another. Each of their
ports records its face, and `qcc components <cell>` prints it (`face 1b1`; the JSON has a `face` key).

| Cell | Joins | Ports |
|---|---|---|
| `CpwTsvTransition` | the two faces of one chip through TSVs: `1t1` to `1b1`, or `2b1` to `2t1` | `a` on `face_ids[0]`, facing −x; `b` on the other side of the same chip, facing +x |
| `FlipChipConnectorRf` (KQC) | the two chips through an indium bump: `face_ids[0]` to `face_ids[1]` (default `1t1` to `2b1`) | `a` on `face_ids[0]` (CPW `a`/`b`), `b` on `face_ids[1]` (CPW `a2`/`b2`, turned by `output_rotation`) |
| `QcFlipChipConnectorRf` | the same, with the bump size as parameters | as `FlipChipConnectorRf` |

`CpwTsvTransition` follows QPDK's `tsv_transition_double_sided` and is drawn from KQC parts. Two pads of
`pad_width` × `pad_length` with gap `pad_gap` sit on top of each other at the origin, one on each face, each closed by
its gap on the far side. A taper of `taper_length` leads from the front CPW (`a`/`b`) into the front pad, one of
`taper_length_back` from the back pad to the back CPW (`a2`/`b2`); with a taper length of 0 the port is the pad edge.
`n_signal_vias` KQC TSVs (`tsv_type`, default `Tsv Ellipse`, `tsv_diameter` across the line and
`tsv_elliptical_width` along it) join the pads, and `n_ground_vias_per_side` TSVs on each side join the two ground
planes. The defaults are QPDK's: 40 × 30 µm pads with a 24 µm gap, 100 µm tapers, two 10 × 20 µm signal vias 20 µm
apart and four ground vias per side, 30 µm apart and 15 µm from the pad gap. The front face is the instance's
`face_ids[0]`: the chip's front face unless you set it, `face_ids=["2b1"]` for a TSV through the top chip. Its 3/0
keep-out is the box around both pads, both tapers and every via, grown by the PDK component margin.

KQC's `FlipChipConnectorRf` always draws a 25 µm bump on a 40 µm under-bump metal and four ground bumps around the
transition. `QcFlipChipConnectorRf` is KQC's cell with three more parameters: `bump_diameter`, `ubm_diameter` and
`n_ground_bumps` (4, KQC's, or 0). QPDK's `bump_transition` is `connector_a=30, connector_b=6, bump_diameter=15,
n_ground_bumps=0`.

A line that goes down through the bottom chip, back up, across to the top chip and through it:

```python
d.add("P1", "BondPad", at=(500, 1000), rot=270)                          # on 1t1
d.add("TDN", "CpwTsvTransition", at=(1200, 1000))                        # 1t1 → 1b1
d.add("TUP", "CpwTsvTransition", at=(1800, 1000), rot=180)               # 1b1 → 1t1
d.add("FC", "QcFlipChipConnectorRf", at=(2400, 1000), connector_a=30, connector_b=6,
      bump_diameter=15, ubm_diameter=20, n_ground_bumps=0)               # 1t1 → 2b1
d.add("TT", "CpwTsvTransition", at=(3000, 1000), face_ids=["2b1"])       # 2b1 → 2t1
d.route("FEED", "P1.a", "TDN.a")       # on 1t1
d.route("UNDER", "TDN.b", "TUP.b")     # on 1b1, the face of both ports
d.route("UP", "TUP.a", "FC.a")         # on 1t1
d.route("TOP", "FC.b", "TT.a")         # on 2b1
```

A route that starts on a port with a recorded face is drawn on that face; one that only ends on such a port takes
the end port's face when none of its waypoints changes face (`face_id`). A route's own `face_ids` are kept, and the
build stops with a `RoutingError` when the route starts on another face than its start port, or ends (after its last
`face_id` waypoint) on another face than its end port. Ports of other cells record no face, so routes between them
are built as before.

The LOM treats each of the three cells as one conductor between `a` and `b`: a pass-through section that extends the
line it joins, so a resonator through a transition stays one line and its length includes the transition's in-plane
length (tapers and pad for the TSV, pad to pad for the bump). The netlist check (`qcc design netlist`) sees both ends
of each cell. `CpwTsvTransition` and `QcFlipChipConnectorRf` draw port texts named `a` and `b`; KQC's
`FlipChipConnectorRf` labels both of its ends `""`, so the check names each end after the face of the route piece
it meets.

Not modelled or not supported yet:

- The via height (the substrate thickness), the bump and the width steps are not in the LOM: a transition adds no
  lumped L or C.
- A route that changes face at a `face_id` waypoint still gets KQC's own `FlipChipConnectorRf` with its default
  bump. Place a `QcFlipChipConnectorRf` and route to its ports to set the bump.
- `n_ground_bumps` is 4 or 0; other counts are refused.
- Routes to cells whose ports record no face are not checked for their face: give such a route its `face_ids`.

## Add your own

`examples/custom_component/pad_gap_capacitor.py` is a complete example: two pads facing across a gap in a CPW line.
A component needs:

- A class that derives from KQC's `Element`, with `Param` parameters and a `build()` that draws the etched shapes on
  `base_metal_gap_wo_grid` (a negative mask: draw what is removed), adds the protection region and calls
  `add_port(name, position, direction)`.
- `qcc_category = "capacitor"` (or `qubit`, `coupler`, `resonator`, `launcher`, ...). The panel's class filter, the
  DRC and the fab export read it.
- Optional: a LOM model registered with `@register_lom("PadGapCapacitor")` that returns a `Fragment`. Without it,
  Run LOM notes that the component has no circuit model.

Copy the file into `src/quantcore_circuits/layouts/others/` (any folder of `layouts/` works; files whose names start
with `_` are skipped) and restart KLayout. The cell then appears in the panel, in `qcc components`, in `design.json`,
in the DRC, the fab export and the LOM. The walk-through is in the
[plugin tutorial](../plugin/TUTORIAL_q1_r1.md).

## Catalog

The [catalog](../components/CATALOG.md) lists every component with its reference, source, ports, LOM flag and origin.

```{toctree}
:maxdepth: 1
:hidden:

../components/cells/index
../components/CATALOG
```
