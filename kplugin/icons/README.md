# Plugin icons

Put the artwork in `assets/` and run `python kplugin/make_icons.py`. The script crops each image to its visible
content, pads it square and writes a 64×64 PNG here. The plugin picks up `icons/<id>.png` for every toolbar mode and
menu item, and items without a file just have no icon.

Style used so far: blue gradient fills (#185adb → light blue), navy outlines, square handles, transparent
background, readable at 24 px.

## Toolbar modes (done)

| id | file in `assets/` | tool |
|---|---|---|
| `qcc_connect` | `connect.png` | Connect two ports with a route |
| `qcc_route_edit` | `Route Handles.png` | Drag, insert and delete route waypoints (bends at the route radius) |
| `qcc_snap` | `move_snap.png` | Move an instance; ports snap to compatible ports |

## Menu items (optional, not made yet)

| id | menu item | suggested picture |
|---|---|---|
| `qcc_open` | Open design… | folder with a small chip/JSON brace |
| `qcc_rebuild` | Rebuild | circular arrow around a small chip |
| `qcc_live` | Live rebuild on/off | chip with a "live" dot or lightning |
| `qcc_undo` | Undo last design edit | curved back arrow |
| `qcc_place` | Place component… | component square with a plus |
| `qcc_path_route` | Selected path(s) → route | sharp polyline turning into a rounded CPW |
| `qcc_sync` | Write moved instances to design.json | square with an arrow into a document |
| `qcc_delete` | Delete instance… | component square with a cross |
| `qcc_dock` | Quantcore panel | side panel / list icon |
| `qcc_run_lom` | Run LOM simulation | small lumped circuit: capacitor + junction cross + inductor |
| `qcc_drc` | Run DRC | chip with a check mark |
| `qcc_shot` | Save view as PNG… | camera |
| `qcc_config` | Settings… | gear |

To add one, save the artwork as `assets/<anything>.png`, add `"<id>": "<anything>.png"` to `SOURCES` in
`kplugin/make_icons.py`, run it, and restart KLayout.

The Salt package icon (in the Salt package manager) is optional too. It's a 180×180 PNG embedded in `grain.xml` as
`<icon>…base64…</icon>`, the way the klive package does it.
