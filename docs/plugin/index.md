# KLayout plugin

The Quantcore plugin turns KLayout into a drawing board for `design.json`. You place components, connect their ports,
check the design, run the LOM and the simulations, and export the mask, all from KLayout's menu and a side panel.
Use it to build a chip by clicking. To work in code instead, see [scripted design with KLive](klive.md).

```{figure} ../images/plugin/window_overview.png
:width: 100%

KLayout with the plugin: the **Quantcore** menu, the three tools in the toolbar, and the Quantcore panel with the
Flow strip on the right.
```

## What it is

- A KLayout **Salt package** (the folder `kplugin/` of the repository, published on the repository's
  [`klayout-plugin` branch](https://github.com/Quantcore-Technologies/Quantcore-Circuits/tree/klayout-plugin), which holds the package alone). It uses only
  KLayout's own Python (`pya`) and the standard library.
- It is a front end for the library. Every action edits `design.json`, calls `qcc` (the command line of this
  library) to rebuild the layout, and reloads the result in place. The overlays (ports, handles, previews) come from
  the `build/<name>.qcc.json` file that every `qcc build` writes next to the OAS.
- It does not import `quantcore_circuits` or KQCircuits inside KLayout. Slow work (build, LOM, simulation) runs as
  `qcc` background jobs, so KLayout stays usable.
- Items the code marks as "coming soon" are named as such in these pages.

## Before you start

You need KLayout 0.30 or newer (the plugin was tested with 0.30.3) and the library installed in a Python environment
that has `qcc` (`pip install --pre "quantcore-circuits[all]"`, see [getting started](../getting-started.md)).

## Install into KLayout

The normal route is KLayout's package manager (Salt):

1. In KLayout open **Tools > Manage Packages**, then **Install New Packages**.
2. Search for `quantcore-circuits` and install it. The package comes from the repository's `klayout-plugin` branch
   (`git+https://github.com/Quantcore-Technologies/Quantcore-Circuits.git[klayout-plugin]`): KLayout downloads that branch only.
3. Restart KLayout. After a plugin update restart it again, because KLayout keeps the modules it loaded at start.

### From a checkout (for development)

Without installing anything, start KLayout with the plugin loaded straight from a clone of the repository:

```bat
klayout_app.exe -e -rm kplugin\load_dev.py
```

This is also what `quantcore_circuits.live.klayout.open_klayout()` runs, so `Designer(..., live=True)` opens a KLayout
with the plugin by itself (see [KLive](klive.md)). To keep the checkout installed as a package, link it into KLayout's
Salt folder (Windows):

```bat
mklink /J "%USERPROFILE%\KLayout\salt\quantcore-circuits" "C:\path\to\Quantcore-Circuits\kplugin"
```

## First launch

1. After the restart a **Quantcore** menu sits next to **Help**, and three tools appear in the toolbar.
2. Open **Quantcore > Settings...**. If **qcc executable** is empty, the plugin looks for `qcc` on the PATH, then in a
   conda env named `qcd` (`%USERPROFILE%\.conda\envs\qcd\Scripts\qcc.exe`). If `qcc` is neither, set the full path
   to `qcc` (or `qcc.exe`) by hand.
3. Open the panel with **Quantcore > Quantcore panel** (**Ctrl+Shift+P**). It docks on the right.
4. Start with **Quantcore > Design > New design...** or **Open design...**, and continue with the
   [tour](tour.md) or the [Q1 + R1 tutorial](TUTORIAL_q1_r1.md).

New to KLayout itself? Read [KLayout basics](klayout-basics.md) first.

## The Quantcore menu

The menu follows the flow: six submenus, then the panel and Settings. Shortcuts work anywhere in KLayout.

| Submenu | Items (shortcut) |
|---|---|
| Design | New design... · Open design... · Chip settings (label, die size)... · Rebuild (Ctrl+Shift+B) · Save as Python script (design.py)... |
| Edit | Undo last design edit (Ctrl+Shift+Z) · Redo design edit (Ctrl+Shift+Y) · Edit selected component... (Ctrl+Shift+Q) · Rename selected component... · Add coupling between components... · Delete route... · Rotate +90° (`[`) / −90° (`]`) · Duplicate selected component (Ctrl+Shift+U) · Mirror selected component (Ctrl+Shift+F) · Delete selected route node (Ctrl+Shift+X) · Route node properties... (Ctrl+Shift+N) · Meander on the segment under the cursor (Ctrl+Shift+M) · Connect on a line: hang beside it / merge into it (Ctrl+Shift+J) |
| Check and LOM | Check design (Ctrl+Shift+D) · Fix pad edge warnings (PDK 100 µm rule) · Run LOM simulation (Ctrl+Shift+O) |
| Simulate | Simulate selected components (automatic, in AEDT)... · Open simulation layout... · Import results... |
| Results | Results against targets... · Propose next revision... |
| Fab | Export for fab (mask, netlist, design.py, PNG)... |
| (top level) | Quantcore panel (Ctrl+Shift+P) · Settings... |

If a submenu could not be filled (for example when `flow.py` fails to import), it shows a disabled "(coming soon)"
item. A normal install does not show it.

These are not in the menu. Use the following instead:

| You want to | Do this |
|---|---|
| Place a component | Double-click it in the panel's Components tab |
| Draw a route | The **Connect** tool |
| Delete a component | Select it and press KLayout's Delete (its routes go too) |
| Stop a running LOM | The **Stop** button in the LOM tab |
| Export a simulation job without solving | **Export the job only** in the Simulate dialog |
| Save a picture | KLayout's File > Screenshot |

## The pages of this section

| Page | What you learn |
|---|---|
| [KLayout basics](klayout-basics.md) | The parts of the KLayout window, as far as the plugin needs them |
| [Plugin tour](tour.md) | A picture of every part of the plugin |
| [Place and route](place-and-route.md) | Placing components, snapping, connecting, route handles, hangers, sim groups |
| [The Flow strip](flow-strip.md) | Check, LOM, Simulate, Results, Tune and Fab from the panel |
| [Scripted design with KLive](klive.md) | Drive KLayout live from a Python script or notebook |
| [Tutorial: Q1 + R1](TUTORIAL_q1_r1.md) | Draw a qubit with a readout resonator, step by step |
| [Component status](COMPONENTS_STATUS.md) | Which library components were placed through the plugin |

The long reference is the plugin's README, `kplugin/README.md`, next to the code.

```{toctree}
:maxdepth: 1
:hidden:

quick-prototype
klayout-basics
tour
place-and-route
flow-strip
klive
TUTORIAL_q1_r1
COMPONENTS_STATUS
```
