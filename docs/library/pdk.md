# PDK

The PDK (process design kit, `src/quantcore_circuits/pdk/__init__.py`) holds the Quantcore fabrication process in one
place: the substrate, the fab layers, the die frame, the keep-outs, the cheese and the junction process. Every build,
simulation export and fab export reads it, so a rule changed here changes every design on the next build. You need
this page when a design must match the fab rules, or when you want to know why the layout puts something where it is.

```python
from quantcore_circuits.pdk import get_pdk
pdk = get_pdk()          # quantcore_nb_sapphire_v1 (default); quantcore_nb_si_v1 is kept for comparison
```

## What it fixes

| Item | Value |
|---|---|
| Stack | Nb film on sapphire 650 µm, eps_r 10.25 (silicon variant: `quantcore_nb_si_v1`) |
| Fab layers | QCT negative mask: 1-4, 50-53, 100, 300 / 301, 700, 800+, 500 / 501 (wafer level), 1000+ |
| Die frame | dicing L, alignment grids, optional device ID, brand `QCT` |
| Pad rule | the outer edge of a pad's etch is 100 µm from the die edge |
| Keep-outs (3/0) | route + 10 µm, component + 24 µm, other + 9 µm |
| Cheese | 5 µm squares, 20 µm gaps, 3 rows, 4 µm from the 3/0 keep-out; holes on 1/0 and 3/0 (the design's own cheese wins over the band) |
| Corner rounding | on by default in the fab export |
| Junction process | Nb trilayer, R_n 40-50 kOhm per device; cells Quantcore Junction and Quantcore Squid |
| Kinetic inductance | 0.116 pH per square; films Nb and NbN (`Pdk.film`) |

A design names its PDK in `design.json` (`pdk`); `Designer(pdk=...)` does the same. It writes nothing itself: the
rules show up in the layout, in the DRC and in the fab file.

Classes: `Pdk`, `Stack`, `DieFrame`, `KeepoutRule`, `CheeseRule`, `CornerRounding`, `JunctionProcess`,
`KineticInductance`. `register_pdk` adds another PDK.

Tutorial 0 prints the table from the live object with `T.pdk_md(pdk)`.

## Pictures

```{figure} ../images/pdk/frame_corner.png
:width: 50%

Die frame, lower-left corner: the dicing L and the 3 x 3 alignment grid.
```

```{figure} ../images/pdk/pads_chip12.png
:width: 60%

Twelve launchpads of tutorial 1, each placed with `edge="auto"` so its etch edge is 100 µm from the die edge. The
device ID `D12` sits at the lower left.
```

```{figure} ../images/pdk/junction.png
:width: 50%

A trilayer junction on the Xmon: lead layers and the junction sheet in the gap of the island.
```

```{figure} ../images/pdk/junction_leads.png
:width: 60%

The same junction zoomed to the leads (800 x 800 px render around `Q1`).
```

```{figure} ../images/pdk/squid.png
:width: 60%

A SQUID: two trilayer junctions in parallel (tutorial 1).
```

```{figure} ../images/pdk/fab_qubit.png
:width: 50%

Fab view of a qubit: the metal etch, the 3/0 keep-out and the cheese band around it.
```

```{figure} ../images/pdk/fab_corner.png
:width: 50%

Fab view of a bend: rounded corners and the cheese squares (5 µm squares on a 25 µm pitch).
```

## The rules in practice

- **Pad rule.** Bond pads and launchers sit with the outer edge of their etch 100 µm from the die edge. `edge="auto"`
  on `Designer.add` (or `place.edge` in `design.json`) slides the pad into place. `TaperedPad` rings count as bond pads
  for this rule too; a `TaperedPad` used as a probe pad inside the die gets a `pad_edge` warning, never an error.
- **Keep-outs (layer 3/0).** The metal etch is grown into a keep-out: 10 µm around a route, 24 µm around a component,
  9 µm around other shapes. Cells that draw their own keep-out get 4 µm more.
- **Cheese.** Ground holes (5 µm squares, 20 µm gaps) fill a band three rows wide around the components, kept at least
  4 µm from 3/0. The holes are on 1/0 and on 3/0. If the design already has its own cheese, its own wins and gets no
  PDK band. Cheese and corner rounding belong to the fab export only; simulation exports never get them.

## Design warnings

Margins against the PDK are DRC warnings of severity `design`, never errors, and they never block a build or an
export: `pad_edge`, `pdk_rn` (junction R_n outside 40-50 kOhm), `pdk_fq` (qubit frequency outside the band),
`pdk_claw`. In the plugin, Quantcore > Check > Fix pad edge warnings sets `edge = "auto"` on every pad the rule flags.

## Gaps

- The amplifier junction process only has a `pdk_rn` warning.
- NbN is not selectable per element (only through `Pdk.film`).
- Asymmetric SQUID drawn cells and a stored HFSS-versus-Palace bias are not built.
- The rules last changed on 2026-11-17 (3/0 keep-outs 4 µm wider, cheese 4 µm from 3/0); 105 example fab exports were
  compared then.
