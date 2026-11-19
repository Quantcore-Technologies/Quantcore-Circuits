"""``<name>.qcc.json`` next to every written layout: what the KLayout plugin needs to edit a design in the GUI.

The plugin runs in KLayout's own Python (pya + stdlib only), so instead of importing quantcore_circuits it reads this
file: the design path, every port (position, outward direction, CPW a/b), instance boxes and placements, and the
routes as built (sharp node polyline, user waypoints, bend radius, lengths). Coordinates are µm, chip frame.
"""

from __future__ import annotations

import json
import os
import tempfile
import warnings
from pathlib import Path

from kqcircuits.pya_resolver import pya

from quantcore_circuits.route.router import RoutingError

SIDECAR_SCHEMA = "qcc-sidecar/0.1"


def sidecar_path(layout_path: str | Path) -> Path:
    p = Path(layout_path)
    return p.with_name(p.stem + ".qcc.json")


def _plain(v):
    """``v`` as plain JSON (dicts, lists, numbers, strings; anything else as its string)."""
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return v if v == v and abs(v) != float("inf") else None
    return str(v)


def _xy(p) -> list[float]:
    return [round(p.x, 4), round(p.y, 4)]


def _end(end) -> object:
    return end if isinstance(end, str) else end.model_dump(mode="json")


def instance_results(design, run_root: str | Path = "build", layout_path: str | Path | None = None) -> dict:
    """Per-instance results for the plugin panel, from the design's run state (``<run_root>/<name>/state.json``).

    One entry per dashboard element that is an instance or a route of ``design`` (qubits, resonators, feedline,
    pads): ``{"kind", "status", "params": [{key, label, value, unit, status, target, source}], "updated",
    "stale"}``. ``stale`` is true when the state was computed for another revision of the design (hash differs), so
    the panel can grey it out. Empty when there is no run yet or the state cannot be read.
    """
    from quantcore_circuits.design import design_hash  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.track import run_dir_for  # pylint: disable=import-outside-toplevel

    candidates = [run_dir_for(design.name, run_root) / "state.json"]
    if layout_path is not None:  # the GUI runs the loop beside the layout (<design dir>/build/<name>/state.json)
        candidates.append(Path(layout_path).resolve().parent / design.name / "state.json")
    candidates = sorted((c for c in candidates if c.exists()), key=lambda c: c.stat().st_mtime, reverse=True)
    try:
        state = json.loads(candidates[0].read_text(encoding="utf-8"))
    except (IndexError, OSError, ValueError):
        return {}
    stale = (state.get("design") or {}).get("hash") != design_hash(design)
    keys = ("key", "label", "value", "unit", "status", "target", "source")
    out = {}
    for el in state.get("elements") or []:
        name = el.get("id")
        if name not in design.instances and name not in design.routes:
            continue
        out[name] = {
            "kind": el.get("kind"),
            "status": el.get("status"),
            "params": [{k: p.get(k) for k in keys} for p in el.get("params") or []],
            "updated": state.get("updated"),
            "stale": stale,
        }
    return out


def _failed_entry(design, name: str, f, pdk) -> dict:
    """A route left out of the build: why, the path the design asks for (``polyline``: its ends and nodes, in the
    shape of a built route so the plugin's route handles work on it) and the last good geometry, if any."""
    route = design.routes[name]
    waypoints = [tuple(n) if isinstance(n, tuple) else tuple(n.at) for n in route.nodes]
    attempt = [_xy(p) for p in f.attempt if p is not None]
    first = 1 if f.attempt and f.attempt[0] is not None else 0  # polyline index of the first node
    return {
        "error": f.error,
        "from": _end(route.from_),
        "to": _end(route.to),
        "type": route.type,
        "polyline": attempt,
        "waypoints": [list(w) for w in waypoints],
        "waypoint_r": [None if isinstance(n, tuple) else n.r for n in route.nodes],
        "waypoint_index": [first + i for i in range(len(waypoints))],
        "fixed_segments": [],
        "r": route.r if route.r is not None else pdk.turn_radius,
        "a": route.a if route.a is not None else pdk.cpw_a,
        "b": route.b if route.b is not None else pdk.cpw_b,
        "length": (f.last_good or {}).get("length"),
        "target_length": route.length if route.type == "meander" else None,
        "last_good": f.last_good,
    }


def instance_junction_entry(name: str, inst, pdk) -> dict | None:
    """``instances.<name>.junction`` of the sidecar: the junction the LOM and the eigenmode / driven exports take
    (:func:`~quantcore_circuits.lom.fragment.instance_junction`) — ``{"kind": "JJ" | "SQUID", "Lj0_nH", "Cj_fF",
    "flux_phi0", "asym", "Lj_eff_nH", "source"}`` (``Lj0_nH`` / ``Lj_eff_nH`` / ``source`` None: no value; ``"error"``
    when the flux leaves no finite L). None for a component without a junction."""
    from quantcore_circuits.lom.fragment import instance_junction  # pylint: disable=import-outside-toplevel

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ej = instance_junction(name, inst, pdk)
    except Exception:  # noqa: BLE001  (never block a build on the junction overlay)
        return None
    if ej is None or ej.kind is None:
        return None
    return _plain(ej.as_dict())


def sidecar_dict(result, layout_path: str | Path | None = None, overlays: bool = True) -> dict:
    """Sidecar content; ``overlays`` adds the fast DRC, the LOM node map and per-instance results (for the plugin)."""
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    design, plan = result.design, result.plan
    pdk = get_pdk(design.pdk)
    base = get_pdk(design.pdk.split("+substrate(", 1)[0])
    ports = {
        name: {
            "pos": _xy(p.pos),
            "dir": [round(p.dir.x, 6), round(p.dir.y, 6)] if p.dir is not None else None,  # some ports have none
            "a": p.a,
            "b": p.b,
        }
        for name, p in plan.all_ports().items()
    }
    gap = result.layout.layer(pya.LayerInfo(130, 1))  # 1t1_base_metal_gap_wo_grid
    boxes = {}
    for inst in result.cell.each_inst():
        name = inst.property("id")
        if name in design.instances:
            cell = result.layout.cell(inst.cell_index)
            b = cell.dbbox_per_layer(gap)
            b = (b if not b.empty() else cell.dbbox()).transformed(inst.dcplx_trans)
            boxes[name] = [round(b.left, 3), round(b.bottom, 3), round(b.right, 3), round(b.top, 3)]
    instances = {}
    for name, inst in design.instances.items():
        placed = plan.instances[name]
        t = placed.trans
        instances[name] = {
            "cell": inst.cell,
            "bbox": boxes.get(name),
            "place": inst.place.model_dump(mode="json", exclude_defaults=True),
            "trans": {"at": _xy(t.disp), "rot": round(t.angle, 6), "mirror": t.is_mirror()},
            "ports": sorted(placed.local_ports),
        }
        junction = instance_junction_entry(name, inst, pdk)
        if junction is not None:  # additive: only components with a junction (JJ / SQUID) carry it
            instances[name]["junction"] = junction
    routes = {}
    for name, route in design.routes.items():
        rp = plan.routes.get(name)
        if rp is None:  # failed (keep-going build): listed under failed_routes
            continue
        poly = rp.polyline()
        waypoints = [tuple(n) if isinstance(n, tuple) else tuple(n.at) for n in route.nodes]
        routes[name] = {
            "from": _end(route.from_),
            "to": _end(route.to),
            "type": route.type,
            "polyline": [_xy(p) for p in poly],
            "waypoints": [list(w) for w in waypoints],
            # per-corner bend radius of each waypoint (None = the route radius): the plugin's curvature handles
            "waypoint_r": [None if isinstance(n, tuple) else n.r for n in route.nodes],
            "waypoint_index": [
                min(range(len(poly)), key=lambda i, w=w: (poly[i] - pya.DPoint(*w)).length()) for w in waypoints
            ],
            "fixed_segments": sorted(rp.fixed_segments),
            "r": rp.params.get("r", pdk.turn_radius),
            "a": rp.params.get("a", pdk.cpw_a),
            "b": rp.params.get("b", pdk.cpw_b),
            "length": rp.length,
            "target_length": rp.target_length,
        }
    failed = {name: _failed_entry(design, name, f, pdk) for name, f in plan.failed.items()}
    drc, lom = [], {}
    try:
        if not overlays:
            raise LookupError("overlays off")
        from quantcore_circuits.assembly.drc import check  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.lom import lom_from_design  # pylint: disable=import-outside-toplevel

        drc = check(result, netlist=False).to_json()
        from quantcore_circuits.assembly.last_good import resolve  # pylint: disable=import-outside-toplevel

        with warnings.catch_warnings():  # the failed route is already reported (failed_routes, route_failed)
            warnings.simplefilter("ignore", RuntimeWarning)
            lb = lom_from_design(design, plan=resolve(plan))
        lom = {
            "nodes": {n: s.layout for n, s in lb.model.nodes.items()},
            "port_nodes": lb.port_map,
            # values and knobs too: the plugin shows each component's circuit (C, L_J, the line, the hanger) in its
            # dialog; plain JSON (numbers, strings, lists)
            "branches": {n: {"type": b.type, "nodes": list(b.nodes), "value": _plain(b.value), "knob": _plain(b.knob)}
                         for n, b in lb.model.branches.items()},
            "controls": lb.model.controls,
        }
    except LookupError:
        pass
    except RoutingError:  # a failed route without a last good one: no LOM overlay (the DRC names the route)
        lom = {}
    except Exception as e:  # noqa: BLE001  (never block a build on the overlays)
        drc = [
            {
                "severity": "warning",
                "rule": "drc_failed",
                "message": f"{type(e).__name__}: {e}",
                "where": [],
                "objects": [],
            }
        ]
    return {
        "schema": SIDECAR_SCHEMA,
        "design": str(result.source.resolve()) if getattr(result, "source", None) else None,
        "layout": str(Path(layout_path).resolve()) if layout_path else None,
        "name": design.name,
        "hash": result.hash,
        "chip_box": list(design.chip.box),
        "pdk": {
            "name": pdk.name,
            "cpw_a": pdk.cpw_a,
            "cpw_b": pdk.cpw_b,
            "turn_radius": pdk.turn_radius,
            "grid_um": pdk.design_grid_um,
            # the substrate (the design's own when its pdk name carries "+substrate(...)"): the plugin's estimates
            "substrate_height_um": pdk.stack.substrate_height,
            "substrate_eps_r": pdk.stack.substrate_permittivity,
            "substrate_tan_d": pdk.stack.substrate_loss_tangent,
            "substrate_material": pdk.stack.substrate_material,
            "junction_gap_meV": pdk.junction.gap_meV,  # I_c·R_n = πΔ/2e (the plugin's Junction values)
            "base": base.name,  # the PDK without the design's own substrate, and its substrate
            "base_substrate": {"h": base.stack.substrate_height, "eps_r": base.stack.substrate_permittivity,
                               "tan_d": base.stack.substrate_loss_tangent},
        },
        "ports": ports,
        "instances": instances,
        "routes": routes,
        **({"failed_routes": failed} if failed else {}),  # keep-going builds only: routes left out of the layout
        "drc": drc,
        "lom": lom,
        "results": instance_results(design, layout_path=layout_path) if overlays else {},
    }


def write_sidecar(result, layout_path: str | Path) -> Path:
    path = sidecar_path(layout_path)
    data = json.dumps(sidecar_dict(result, layout_path), indent=1)
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(data)
    os.replace(tmp, path)
    return path
