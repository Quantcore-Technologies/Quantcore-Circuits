# KLayout basics

KLayout is a free viewer and editor for chip layouts. The Quantcore plugin runs inside it, so a few KLayout habits
matter. This page covers those; for everything else see KLayout's own manual (Help menu).

## What you see

| Part | Where | What it is for |
|---|---|---|
| Layout view | Centre | The drawing. One tab per open layout |
| Layers panel | Left | One row per layer. Tick or untick a row to show or hide the layer |
| Cells panel | Left, below or in a tab | The cell tree: the chip cell and the cells inside it |
| Toolbar | Top | The tools: Select, Move, Ruler and, after the install, the three Quantcore tools |
| Status bar | Bottom | Cursor position in µm and hints. The plugin writes its messages here |
| Quantcore panel | Right | The Flow strip and the tabs Components, LOM, DRC, Results, Sim groups |
| Quantcore menu | Menu bar, next to Help | Every plugin action |

## Moving around

- Zoom with the mouse wheel. Pan by dragging with the middle mouse button (or hold the wheel and drag).
- **F2** zooms to fit the whole layout. Use it after every New design or Open design.
- Zoom in before you click on a port. The plugin picks the nearest compatible port within the **capture radius**
  (12 pixels by default), so two ports that are close on screen are hard to tell apart.

## Cells, layers and the chip cell

- A **cell** is a group of shapes. A chip is a cell that contains other cells (instances). Here an instance is a
  placed component or a route.
- After every build the plugin shows the **chip cell** as the view's top cell. So each component and each route is a
  top-level instance you can select with KLayout's own tools.
- A **layer** is a mask layer. On a Quantcore chip the metal and etch layers follow the
  [fab layer map](../library/fab.md). KLayout draws them with colours, so a layer panel with many rows is normal.
  Layer `instance_names` carries the component names. It is an annotation layer and is not part of the fab mask.

## Editing mode

KLayout opens in viewer mode unless it is started in editing mode (`klayout_app.exe -e`). The plugin's command
`load_dev.py` starts it that way (see [install](index.md#install-into-klayout)). If you start KLayout yourself, switch
editing mode on before you use the tools that move things.

## The grid

KLayout has an **editor grid**. Nodes and placements snap to it, as KLayout's own shapes do. The plugin has a fallback
grid (default 1 µm) that applies only when KLayout has none. Set it in **Quantcore > Settings...** (*Placement /
waypoint grid*). Clicks need not be exact: every component and every route node has a dialog with exact x and y.

## KLayout's own tools on a Quantcore chip

These work on components and routes, and the plugin writes each change to `design.json` and rebuilds:

| Do this | Result |
|---|---|
| Select with KLayout's Select tool, then drag | Moves the component |
| Edit > Selection > Rotate... | Rotates it |
| Delete key | Deletes the component. Its routes go too. Deleting a route instance deletes that route |
| KLayout's properties dialog on the selection | Changes the position |
| File > Screenshot | Saves the view as a picture |

Quantcore **Undo** (Ctrl+Shift+Z) takes these back, and the plugin keeps 50 undo levels.

```{warning}
Components and routes are cells that the plugin **rebuilds** from `design.json`. A shape drawn with KLayout's own
shape tools is not a component: it has no ports, LOM nodes or DRC, and the next rebuild removes it. Draw components
and routes with the Quantcore tools.
```

## Closing KLayout

The plugin reloads the layout after each build, so KLayout may ask whether to save a modified layout when you close
it. Answer **No**: the OAS file is a build output, and `design.json` holds your design.

## Next

The three Quantcore tools and the panel are described in [place and route](place-and-route.md). A picture of every
dialog is on the [tour](tour.md).
