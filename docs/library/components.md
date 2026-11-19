# Components

A component (a cell) is one drawn element of a chip: a qubit, a pad, a coupler, a capacitor, a junction. You place
one with `Designer.add("Q1", "Xmon", ...)`, with the KLayout plugin's component panel, or as a `cell` in
`design.json`. This page says where the 143 components come from, how to read a cell's page, and how to add your own.

## Three sources

| Source | How you name it | Count | Notes |
|---|---|---|---|
| Quantcore cells | the class name: `Xmon`, `BondPad` | 57 | Re-implementations of the legacy QWri macros and of QPDK and SQDMetal cells, drawn natively on KQCircuits. They know the Quantcore layers and rules |
| KQCircuits (KQC) classes | the bare class name: `Swissmon` | 45 | KQC's own library, used unchanged |
| Qiskit Metal | `metal:<Class>`: `metal:TransmonPocket` | 41 | Quantum Metal `qlibrary` components, with the Metal options as parameters. Metal is imported only when such a cell is built |

`layouts.registry.resolve_cell` accepts any of these, and also a dotted class path such as
`kqcircuits.qubits.swissmon.Swissmon`. The counts come from the [catalog](../components/CATALOG.md) of 2026-11-16;
109 of the 143 have a LOM model (see [LOM](lom.md)). `qcc components` lists them, and `qcc components Xmon` prints one
cell's ports.

## Read a cell page

The generated [component reference](../components/cells/index.md) has one page per cell. Each shows:

1. **The pins first.** The ports of a default instance: name, position (µm, in the cell's own frame), direction
   (degrees, pointing out of the cell) and the CPW width `a` and gap `b` it expects. A route refers to a pin as
   `INSTANCE.pin`, for example `Q1.claw_n`. A pin without a direction marks a point and cannot be snapped to.
2. The **parameters**, with defaults and units. Only changed ones are stored in `design.json`.
3. The **LOM model**, when there is one.
4. How to **place** the cell.

Two pins connect when their directions face each other and their `a` and `b` match; the DRC warns otherwise (see
[Routing and DRC](routing-drc.md)). The plugin's own status of each cell is on
[the plugin components page](../plugin/COMPONENTS_STATUS.md).

## Add your own

`examples/custom_component/pad_gap_capacitor.py` is a complete example: two pads facing across a gap in a CPW line.
Three things make a component:

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

## Maintainer pages

These lists record how the components were checked. Read them to find out which cells duplicate each other, where a
cell was migrated from, and what was audited.

| Page | What it holds |
|---|---|
| [Catalog](../components/CATALOG.md) | Every component with its reference, source, ports, LOM flag and origin |
| [Duplicates](../components/DUPLICATES.md) | Cells that draw the same thing, and what was decided |
| [Migration](../components/MIGRATION.md) | Each inventory item built as a one-instance probe: builds, ports, LOM, golden XOR tests |
| [Inventory](../components/INVENTORY.md) | What exists in Quantcore, KQC, Metal and the legacy macros |
| [Audit](../components/AUDIT.md) | The independent check of the migration |
| [Simulation export audit](../components/SIM_EXPORT_AUDIT.md) | Every cell exported for Q3D and eigenmode, and the geometry checked |

```{toctree}
:maxdepth: 1
:hidden:

../components/cells/index
../components/CATALOG
../components/DUPLICATES
../components/MIGRATION
../components/INVENTORY
../components/AUDIT
../components/SIM_EXPORT_AUDIT
```
