"""GUI ↔ design.json synchronisation, standard library + pya only (runs inside KLayout's own Python).

The GUI never becomes the source of truth: edits are written back into ``design.json`` and the chip is rebuilt by
``qcc``. Instances built by qcc carry their design name in the KQC ``id`` instance property.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

try:  # inside KLayout
    import pya  # type: ignore
except ImportError:  # standalone tests
    import klayout.db as pya  # type: ignore

TOL = 1e-3  # µm


def read_design(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_design(path, data: dict) -> None:
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def find_chip_cell(top: pya.Cell) -> pya.Cell:
    """The DesignChip cell under the written top cell (or the top cell itself)."""
    layout = top.layout()
    for inst in top.each_inst():
        cell = layout.cell(inst.cell_index)
        if cell.name.startswith("Design"):
            return cell
    return top


def placed_instances(chip: pya.Cell) -> dict[str, pya.DCplxTrans]:
    out = {}
    for inst in chip.each_inst():
        name = inst.property("id")
        if name:
            out[str(name)] = inst.dcplx_trans
    return out


def _place_from_trans(t: pya.DCplxTrans) -> dict:
    angle = t.angle % 360.0
    if abs(angle - round(angle)) < 1e-9:
        angle = float(round(angle)) % 360.0
    place = {"at": [round(t.disp.x, 4), round(t.disp.y, 4)], "rot": angle}
    if t.is_mirror():
        place["mirror"] = True
    return place


def sync_placements(design: dict, chip: pya.Cell, built: dict[str, pya.DCplxTrans] | None = None):
    """Write moved instances back to ``design['instances'][*]['place']``.

    ``built`` are the transforms of the last qcc build (to detect moves); if omitted every absolute placement is
    compared with its ``place`` entry. Snap-placed instances that were moved become absolute placements (reported).
    Returns ``(design, report_lines)``.
    """
    report = []
    current = placed_instances(chip)
    for name, trans in current.items():
        inst = design.get("instances", {}).get(name)
        if inst is None:
            continue  # routes (also tagged with id) and unknown cells
        place = inst.get("place", {})
        new = _place_from_trans(trans)
        if "snap" in place:
            ref = built.get(name) if built else None
            if ref is None or _same(ref, trans):
                continue
            report.append(f"{name}: was snapped to {place.get('to')}; now absolute at {new['at']} rot {new['rot']}")
            inst["place"] = new
            continue
        old_at = place.get("at", [0, 0])
        if (
            abs(old_at[0] - new["at"][0]) > TOL
            or abs(old_at[1] - new["at"][1]) > TOL
            or abs(place.get("rot", 0) - new["rot"]) > 1e-6
            or bool(place.get("mirror")) != bool(new.get("mirror"))
        ):
            report.append(f"{name}: {old_at} rot {place.get('rot', 0)} -> {new['at']} rot {new['rot']}")
            inst["place"] = {**{k: v for k, v in place.items() if k not in ("at", "rot", "mirror")}, **new}
            follow_hangers(design, name, (new["at"][0] - old_at[0], new["at"][1] - old_at[1]))
    return design, report


def _same(a: pya.DCplxTrans, b: pya.DCplxTrans) -> bool:
    return (a.disp - b.disp).length() < TOL and abs(a.angle - b.angle) < 1e-6 and a.is_mirror() == b.is_mirror()


def _json_value(v):
    if isinstance(v, (bool, int, float, str)) or v is None:
        return v
    if isinstance(v, (list, tuple)):
        return [_json_value(x) for x in v]
    if hasattr(v, "x") and hasattr(v, "y"):
        return [v.x, v.y]
    return str(v)


def new_pcell_instances(design: dict, cell: pya.Cell) -> tuple[dict, list[str]]:
    """Add PCell instances placed by hand in ``cell`` (no ``id`` yet) to the design as absolute instances."""
    report = []
    existing = set(design.get("instances", {})) | set(design.get("routes", {}))
    for inst in cell.each_inst():
        if inst.property("id") or not inst.is_pcell():
            continue
        decl = inst.pcell_declaration()
        cls_name = type(decl).__name__
        params = inst.pcell_parameters_by_name()
        defaults = {p.name: p.default for p in decl.get_parameters()}
        changed = {
            k: _json_value(v)
            for k, v in params.items()
            if not k.startswith("_") and k in defaults and v != defaults[k] and k != "display_name"
        }
        base = "".join(c for c in cls_name if c.isupper()) or "X"
        i = 1
        while f"{base}{i}" in existing:
            i += 1
        name = f"{base}{i}"
        existing.add(name)
        design.setdefault("instances", {})[name] = {
            "cell": cls_name,
            "params": changed,
            "place": _place_from_trans(inst.dcplx_trans),
        }
        inst.set_property("id", name)
        report.append(f"added {name} ({cls_name})")
    return design, report


def unique_name(design: dict, base: str) -> str:
    taken = set(design.get("instances", {})) | set(design.get("routes", {}))
    i = 1
    while f"{base}{i}" in taken:
        i += 1
    return f"{base}{i}"


def add_route(
    design: dict,
    name: str,
    src: str,
    dst,
    kind: str = "cpw",
    length: float | None = None,
    nodes: list | None = None,
    r: float | None = None,
    a: float | None = None,
    b: float | None = None,
) -> dict:
    """Add (or replace) route ``name``; ``dst`` is a port reference or a hanger/free-end dict. ``a`` / ``b`` give the
    route its own CPW width and gap (None: the ports')."""
    if isinstance(src, dict) and isinstance(dst, dict) and "hanger" not in dst:
        raise ValueError("a route needs at least one port or line end (both ends are free)")
    route = {"from": src, "to": dst, "type": kind}
    if kind == "meander":
        if not length:
            raise ValueError("meander routes need a length")
        route["length"] = float(length)
    if nodes:
        route["nodes"] = [[_r(x), _r(y)] for x, y in nodes]
    if r is not None:
        route["r"] = float(r)
    if a is not None:
        route["a"] = float(a)
    if b is not None:
        route["b"] = float(b)
    design.setdefault("routes", {})[name] = route
    return design


def _r(v: float) -> float:
    return round(float(v), 4)


def _node_xy(node) -> list[float]:
    return list(node["at"]) if isinstance(node, dict) else list(node)


def _with_xy(node, xy) -> object:
    """Keep waypoint extras (airbridge, a/b taper, params) when moving a node."""
    xy = [_r(xy[0]), _r(xy[1])]
    if isinstance(node, dict):
        return {**node, "at": xy}
    return xy


def refresh_free_end_dir(route: dict) -> None:
    """A free end's ``dir`` points from the end back along the segment that arrives at it (what the Connect tool wrote);
    after the node next to the end was moved, inserted or deleted it is derived from the new last node again."""
    from qcc_kplugin.geometry import free_end_dir  # pylint: disable=import-outside-toplevel

    end, nodes = route.get("to"), route.get("nodes") or []
    if isinstance(end, dict) and "hanger" not in end and end.get("dir") is not None and nodes:
        d = free_end_dir((float(end["at"][0]), float(end["at"][1])), tuple(_node_xy(nodes[-1])))
        if d is not None:
            end["dir"] = d


def move_route_node(design: dict, route: str, index: int, xy) -> dict:
    nodes = design["routes"][route].setdefault("nodes", [])
    nodes[index] = _with_xy(nodes[index], xy)
    if index == len(nodes) - 1:
        refresh_free_end_dir(design["routes"][route])
    return design


def _corner_indices(built: dict) -> tuple[list[int], dict[int, int]] | None:
    """(polyline index of every corner a user can edit, {polyline index: index in the design's own nodes}) of a built
    route: its own nodes plus the router's corners, without port stubs and the hanger coupler's approach."""
    pts = built.get("polyline") or []
    fixed = set(built.get("fixed_segments") or [])
    wp_idx = list(built.get("real_waypoint_index", built.get("waypoint_index")) or [])
    if len(pts) < 2 or len(wp_idx) != len(built.get("real_waypoints", built.get("waypoints")) or []):
        return None
    own = {k: i for i, k in enumerate(wp_idx)}
    generated = {k - 1 for k in fixed if k > 1} | ({1} if 1 in fixed else set())  # stub ends, coupler approach
    return [k for k in range(1, len(pts) - 1) if k in own or k not in generated], own


def editable_route(built: dict) -> dict:
    """The sidecar route as Route handles edits it: ``waypoints`` / ``waypoint_index`` / ``waypoint_r`` list every
    corner (the router's own too, see :func:`materialize_nodes`); the design's own nodes stay in ``real_*``."""
    out = dict(built)
    found = _corner_indices(built)
    if found is None:
        return out
    idx, own = found
    pts = built["polyline"]
    r_own = list(built.get("waypoint_r") or [])
    out["real_waypoints"] = list(built.get("waypoints") or [])
    out["real_waypoint_index"] = list(built.get("waypoint_index") or [])
    out["waypoints"] = [list(pts[k]) for k in idx]
    out["waypoint_index"] = idx
    out["waypoint_r"] = [r_own[own[k]] if k in own and own[k] < len(r_own) else None for k in idx]
    return out


def materialize_nodes(design: dict, route: str, built: dict) -> list[int] | None:
    """Make every corner of the built route (sidecar ``built``, or its :func:`editable_route`) a node in design.json,
    keeping the existing nodes (and their extras). The router adds its own corners only where the user gave none, so
    a node inserted there would otherwise replace them all and the route would no longer look like its preview.
    Port stubs and hanger couplers stay the router's. Returns the polyline index of each node, or None when the
    existing nodes cannot be matched to the polyline (left unchanged)."""
    found = _corner_indices(built)
    if found is None or route not in design.get("routes", {}):
        return None
    idx, own = found
    old = list(design["routes"][route].get("nodes") or [])
    if len(old) != len(own):
        return None  # design.json changed since the build: leave it
    pts = built["polyline"]
    nodes = [old[own[k]] if k in own else [_r(pts[k][0]), _r(pts[k][1])] for k in idx]
    if nodes:
        design["routes"][route]["nodes"] = nodes
    return idx


def insert_route_node(design: dict, route: str, index: int, xy) -> dict:
    nodes = design["routes"][route].setdefault("nodes", [])
    nodes.insert(index, [_r(xy[0]), _r(xy[1])])
    if index == len(nodes) - 1:
        refresh_free_end_dir(design["routes"][route])
    return design


def delete_route_node(design: dict, route: str, index: int) -> dict:
    nodes = design["routes"][route].get("nodes", [])
    was_last = index == len(nodes) - 1
    del nodes[index]
    if not nodes:
        design["routes"][route].pop("nodes", None)
    elif was_last:
        refresh_free_end_dir(design["routes"][route])
    return design


def set_route_options(design: dict, route: str, **options) -> dict:
    """Set ``type``/``length``/``r``/``meander_segment`` etc.; ``None`` removes the key."""
    r = design["routes"][route]
    for k, v in options.items():
        if v is None:
            r.pop(k, None)
        else:
            r[k] = v
    if r.get("type") != "meander":
        r.pop("length", None)
    return design


def set_place_at(design: dict, inst: str, at, rot: float | None = None, mirror: bool | None = None) -> dict:
    place = design["instances"][inst].get("place", {})
    keep_rot = place.get("rot", 0.0) if "snap" not in place else 0.0
    new = {"at": [_r(at[0]), _r(at[1])], "rot": float(keep_rot if rot is None else rot)}
    if mirror if mirror is not None else place.get("mirror"):
        new["mirror"] = True
    design["instances"][inst]["place"] = new
    return design


def set_place_snap(design: dict, inst: str, port: str, to: str, gap: float = 0.0) -> dict:
    """``place.snap``: ``inst.port`` sits on ``to`` facing it (the rebuild solves the rotation)."""
    if to.split(".", 1)[0] == inst:
        raise ValueError("cannot snap an instance to itself")
    place = {"snap": f"{inst}.{port}" if "." not in port else port, "to": to}
    if gap:
        place["gap"] = float(gap)
    if design["instances"][inst].get("place", {}).get("mirror"):
        place["mirror"] = True  # the snap keeps a mirrored component mirrored (the build turns it to face the target)
    design["instances"][inst]["place"] = place
    return design


def add_instance(
    design: dict,
    name: str,
    cell: str,
    at,
    rot: float = 0.0,
    params: dict | None = None,
    mirror: bool = False,
    extra: dict | None = None,
) -> dict:
    """Add instance ``name``; ``extra`` holds further entry keys (e.g. ``junction``) copied from a duplicated one."""
    inst = {"cell": cell, "place": {"at": [_r(at[0]), _r(at[1])], "rot": float(rot)}}
    if mirror:
        inst["place"]["mirror"] = True
    if params:
        inst["params"] = params
    for k, v in (extra or {}).items():
        inst.setdefault(k, v)
    design.setdefault("instances", {})[name] = inst
    return design


def delete_instance(design: dict, name: str) -> tuple[dict, list[str]]:
    """Remove an instance and every route touching it; returns the removed route names."""
    design.get("instances", {}).pop(name, None)
    gone = []
    for rname, route in list(design.get("routes", {}).items()):
        ends = [e for e in (route.get("from"), route.get("to")) if isinstance(e, str)]
        if any(e.split(".", 1)[0] == name for e in ends):
            del design["routes"][rname]
            gone.append(rname)
    return design, gone


def delete_route(design: dict, name: str) -> list[str]:
    """Remove route ``name`` and the routes that hang on it (their coupler sits on its line); returns the removed
    names, ``name`` first."""
    routes = design.get("routes", {})
    gone = []
    if name in routes:
        del routes[name]
        gone.append(name)
    again = True
    while again:  # a hanger on a hanger's route, and so on
        again = False
        for rname, route in list(routes.items()):
            ends = (route.get("from"), route.get("to"))
            if any(isinstance(e, dict) and e.get("hanger") in gone for e in ends):
                del routes[rname]
                gone.append(rname)
                again = True
    return gone


def route_from_path(points: list, ports: dict[str, dict], capture: float):
    """A drawn path → ``(from_port, to_port, waypoints)``: end points snap to the nearest ports within ``capture``.

    Interior vertices become waypoints (the rebuild bends each corner to the route radius). Waypoints that sit on the
    port stubs' axis are kept; the router then replaces the stub with them.
    """
    from qcc_kplugin.geometry import nearest  # pylint: disable=import-outside-toplevel

    pos = {n: tuple(p["pos"]) for n, p in ports.items()}
    src = nearest(pos, tuple(points[0]), capture)
    dst = nearest(pos, tuple(points[-1]), capture)
    if src is None or dst is None or src == dst:
        raise ValueError("path ends must lie on two different ports (within the capture radius)")
    return src, dst, [tuple(p) for p in points[1:-1]]


def angle_deg(v) -> float:
    return math.degrees(math.atan2(v.y, v.x))


def _fmt_num(v) -> str:
    if v is None:
        return "–"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"{v:.4g}"
    return str(v)


def results_rows(sidecar: dict, instance: str | None = None) -> list[tuple[str, str, str, str]]:
    """Panel rows from the sidecar's per-instance ``results``: ``(element, parameter, value, target · status)``.

    ``instance`` limits the rows to one element (the selected instance or route). Values computed for another
    revision of the design carry ``(stale)`` in the status column.
    """
    rows = []
    results = sidecar.get("results") or {}
    for name in sorted(results) if instance is None else [instance]:
        entry = results.get(name)
        if not entry:
            continue
        for p in entry.get("params") or []:
            unit = f" {p['unit']}" if p.get("unit") else ""
            value = f"{_fmt_num(p.get('value'))}{unit}"
            t = p.get("target") or {}
            target = f"{_fmt_num(t.get('value'))} ± {_fmt_num(t.get('tol'))}" if t else ""
            status = (p.get("status") or "") + (" (stale)" if entry.get("stale") else "")
            rows.append(
                (name, p.get("label") or p.get("key") or "", value, " · ".join(x for x in (target, status) if x))
            )
    return rows


def new_design(name: str, box=(0.0, 0.0, 7500.0, 7500.0), pdk: str = "quantcore_nb_sapphire_v1") -> dict:
    """An empty design: the PDK die (frame, pad-edge rule, cheese band come from the build) and nothing on it."""
    return {
        "schema": "qcc/0.1",
        "name": name,
        "pdk": pdk,
        "chip": {"box": [float(v) for v in box], "params": {"name_chip": name[:8].upper()}},
        "instances": {},
        "routes": {},
    }


def hanger_end(
    route: str, near, length: float, side: str = "left", end: str = "short", ground_gap: float = 6.0,
    direction: str = "forward", coupler_gap: float | None = None, line_gap: float | None = None,
) -> dict:
    """A hanger route end (``HangerEnd``): a ``length`` µm coupler on ``route`` centred at the point nearest ``near``.
    ``coupler_gap`` / ``line_gap``: the two facing gaps narrowed along the coupler (None: the CPW's own)."""
    if side not in ("left", "right") or end not in ("short", "open"):
        raise ValueError("side must be left/right and end short/open")
    if direction not in ("forward", "backward"):
        raise ValueError("direction must be forward or backward")
    out = {"hanger": route, "near": [_r(near[0]), _r(near[1])], "length": float(length), "side": side, "end": end,
           "ground_gap": float(ground_gap)}
    if direction != "forward":
        out["direction"] = direction
    for key, value in (("coupler_gap", coupler_gap), ("line_gap", line_gap)):
        if value is not None:
            out[key] = float(value)
    return out


def set_instance(design: dict, inst: str, params: dict, rot: float | None = None) -> dict:
    """Replace an instance's PCell ``params`` (only the values that differ from the cell defaults belong here) and,
    when the instance is placed by ``at``, its rotation."""
    entry = design["instances"][inst]
    if params:
        entry["params"] = params
    else:
        entry.pop("params", None)
    place = entry.setdefault("place", {})
    if rot is not None and "snap" not in place:
        place["rot"] = float(rot) % 360.0
    return design


def changed_params(schema: list[dict], values: dict) -> dict:
    """``values`` (name → value) minus those equal to the schema defaults."""
    defaults = {p["name"]: p["default"] for p in schema}
    return {k: v for k, v in values.items() if k not in defaults or v != defaults[k]}


JSON_DICT_PARAMS = ("options", "junction_params")  # str parameters (default "{}") that design.json keeps as a dict


def parse_value(text: str, default, name: str | None = None):
    """A table cell's text as a parameter value of the default's type (strings stay strings; others JSON). The JSON
    text of ``options`` (Quantum Metal components) and ``junction_params`` becomes the dict the notebooks write: the
    string form builds the same layout but the LOM export does not read Metal options from it."""
    text = text.strip()
    if isinstance(default, str):
        if name in JSON_DICT_PARAMS and default.strip() == "{}" and text.startswith("{"):
            try:
                obj = json.loads(text)
            except ValueError:
                return text
            if isinstance(obj, dict):
                return obj or default
        return text
    try:
        return json.loads(text)
    except ValueError:
        return text


def follow_hangers(design: dict, inst: str, delta) -> list[str]:
    """A component moved by ``delta``: the hanger couplers of its routes (``to: {"hanger": ..., "near": [x, y]}``)
    move with it, so a readout hanging from a feedline keeps its geometry instead of failing to route (a fixed
    coupler 100 µm off the claw needs an S-jog shorter than two bend radii)."""
    moved = []
    if not (delta[0] or delta[1]):
        return moved
    for rname, route in design.get("routes", {}).items():
        src = route.get("from")
        dst = route.get("to")
        for end, other in ((dst, src), (src, dst)):
            if isinstance(end, dict) and end.get("near") and isinstance(other, str) and other.split(".", 1)[0] == inst:
                end["near"] = [_r(end["near"][0] + delta[0]), _r(end["near"][1] + delta[1])]
                moved.append(rname)
    return moved


def free_end(at, direction: float | None = None, end: str = "open", gap: float = 6.0) -> dict:
    """A free route end (``FreeEnd``) at ``at``: ``open`` leaves a ``gap`` µm gap (KQC term), ``short`` grounds it
    (term 0). ``direction`` (degrees) points from the end into the route; None lets the route leave freely."""
    if end not in ("open", "short"):
        raise ValueError("a free end is 'open' or 'short'")
    out = {"at": [_r(at[0]), _r(at[1])], "term": 0.0 if end == "short" else float(gap)}
    if direction is not None:
        out["dir"] = float(direction)
    return out


def node_props(node) -> dict:
    """``{"at", "r", "airbridge", "a", "b"}`` of a route node (a plain ``[x, y]`` or a ``Waypoint`` dict); ``a`` / ``b``
    are the line width / gap from this node on (a taper), None = unchanged."""
    if isinstance(node, dict):
        return {"at": list(node["at"]), "r": node.get("r"), "airbridge": bool(node.get("airbridge")),
                "a": node.get("a"), "b": node.get("b")}
    return {"at": list(node), "r": None, "airbridge": False, "a": None, "b": None}


def set_node(design: dict, route: str, index: int, **props) -> dict:
    """Change node ``index`` of ``route``: ``at`` (x, y), ``r`` (this corner's bend radius; None = the route's) and/or
    ``airbridge``, ``a`` / ``b`` (line width / gap from this node on: a taper; None = removed). Other waypoint extras
    (params) are kept; a node left with only its position is written as a plain ``[x, y]``."""
    nodes = design["routes"][route].setdefault("nodes", [])
    node = dict(nodes[index]) if isinstance(nodes[index], dict) else {"at": list(nodes[index])}
    if props.get("at") is not None:
        node["at"] = [_r(props["at"][0]), _r(props["at"][1])]
    if "r" in props:
        if props["r"] is None:
            node.pop("r", None)
        else:
            node["r"] = _r(props["r"])
    if "airbridge" in props:
        if props["airbridge"]:
            node["airbridge"] = True
        else:
            node.pop("airbridge", None)
    for k in ("a", "b"):
        if k in props:
            if props[k] is None:
                node.pop(k, None)
            else:
                node[k] = _r(props[k])
    nodes[index] = node if set(node) - {"at"} else list(node["at"])
    if props.get("at") is not None and index == len(nodes) - 1:
        refresh_free_end_dir(design["routes"][route])
    return design


def set_meander_segment(design: dict, route: str, segment: int | None) -> dict:
    """Put the meander of ``route`` on polyline ``segment`` (1-based, the segment ending at node ``segment``)."""
    r = design["routes"][route]
    if segment is None:
        r.pop("meander_segment", None)
    else:
        r["meander_segment"] = int(segment)
    return design


def mirror_instance(design: dict, inst: str) -> bool:
    """Toggle ``place.mirror`` of ``inst`` (a mirror about its local x axis, applied before its rotation or snap).
    Returns the new state."""
    place = design["instances"][inst].setdefault("place", {})
    new = not place.get("mirror", False)
    if new:
        place["mirror"] = True
    else:
        place.pop("mirror", None)
    return new


def duplicate_spec(design: dict, inst: str) -> dict:
    """What a copy of ``inst`` needs: ``{"cell", "params", "rot", "extra"}`` (``extra`` = every entry key besides
    cell/params/place, e.g. ``junction``), for placing it again with the placement ghost."""
    entry = design["instances"][inst]
    place = entry.get("place", {})
    return {
        "cell": entry["cell"],
        "params": json.loads(json.dumps(entry.get("params", {}))),
        "rot": float(place.get("rot", 0.0)) if "snap" not in place else 0.0,
        "mirror": bool(place.get("mirror")),
        "extra": {k: json.loads(json.dumps(v)) for k, v in entry.items() if k not in ("cell", "params", "place")},
    }


# ---- targets (design.json ``targets``: {element: {key: number}}) -------------------------------------------------
QUBIT_TARGETS = {"f_q_GHz": "qubit frequency (GHz)", "alpha_MHz": "anharmonicity (MHz, negative)"}
RESONATOR_TARGETS = {
    "f_GHz": "resonator frequency (GHz)",
    "kappa_MHz": "linewidth κ (MHz)",
    "g_MHz": "qubit-resonator coupling g (MHz)",
    "chi_MHz": "dispersive shift χ (MHz)",
}
_QUBIT_WORDS = ("xmon", "transmon", "qubit", "squid", "gatemon", "flipmon", "fluxonium", "tunable", "swissmon")


def target_keys(kind: str, cell: str = "", existing: dict | None = None, category: str | None = None) -> dict[str, str]:
    """Target keys offered for an element, ``{key: description}``: ``kind`` is ``"route"`` (resonators and lines) or
    ``"instance"``. An instance gets them by its catalog class ``category`` (every ``qubit`` the qubit targets, every
    ``resonator`` the resonator targets); without a class, by its cell name. Keys already in ``existing`` are always
    kept."""
    if kind == "route":
        base = dict(RESONATOR_TARGETS)
    elif category == "qubit":
        base = dict(QUBIT_TARGETS)
    elif category == "resonator":
        base = {k: v for k, v in RESONATOR_TARGETS.items() if k in ("f_GHz", "kappa_MHz")}
    elif category:
        base = {}
    elif any(w in cell.lower() for w in _QUBIT_WORDS):
        base = dict(QUBIT_TARGETS)
    else:
        base = {}
    for k in existing or {}:
        base.setdefault(k, k)
    return base


def parse_targets(texts: dict[str, str]) -> dict[str, float]:
    """``{key: text}`` → numbers; empty texts are dropped, a non-number raises ``ValueError`` naming the key."""
    out = {}
    for key, text in texts.items():
        text = (text or "").strip()
        if not text:
            continue
        try:
            out[key] = float(text)
        except ValueError as e:
            raise ValueError(f"target {key}: {text!r} is not a number") from e
    return out


def set_targets(design: dict, element: str, values: dict[str, float]) -> bool:
    """Write ``values`` as ``design["targets"][element]`` (the schema's per-element ``{key: float}``); an empty dict
    removes the entry. Returns True when design.json changed."""
    old = (design.get("targets") or {}).get(element, {})
    if dict(old) == dict(values):
        return False
    if values:
        design.setdefault("targets", {})[element] = {k: float(v) for k, v in values.items()}
    else:
        design.get("targets", {}).pop(element, None)
        if not design.get("targets"):
            design.pop("targets", None)
    return True


# Target tolerances, ABSOLUTE in the target's own unit (design.json ``targets`` holds values only, no tolerances).
# This is a copy of ``quantcore_circuits.lom.builder.DEFAULT_TOL`` (the plugin cannot import the library), so the LOM
# tab calls a value "within tolerance" exactly as ``qcc analyse`` / the Results tab do; tests/test_kplugin.py checks
# that the two stay equal. Keys not listed: 1 % of the target.
TARGET_TOL = {"f_q_GHz": 0.02, "alpha_MHz": 10.0, "f_GHz": 0.01, "g_MHz": 10.0, "chi_MHz": 0.1, "kappa_MHz": 0.2}


def target_tolerance(key: str, target: float | None = None) -> float | None:
    """Absolute tolerance of target ``key`` (e.g. ``"f_q_GHz"`` or ``"Q1.f_q_GHz"``): :data:`TARGET_TOL`, else 1 % of
    ``target`` (None without one)."""
    k = key.split(".")[-1]
    if k in TARGET_TOL:
        return TARGET_TOL[k]
    return abs(target) * 0.01 if target is not None else None


def compare_targets(params: dict, targets: dict) -> list[dict]:
    """LOM ``params`` (keys like ``"Q1.f_q_GHz"``) against the design's ``targets``.

    Returns rows ``{key, element, name, value, target, tol, status}`` for every simulated parameter and for every
    target without a value (status ``"no value"``). Status: ``"within tolerance"``, ``"off"`` (beyond the absolute
    tolerance of :func:`target_tolerance`) or ``""`` when there is no target."""
    rows, seen = [], set()
    for key in sorted(params):
        element, _, name = key.partition(".")
        tgt = (targets.get(element) or {}).get(name)
        seen.add(key)
        value = params[key]
        status, tol = "", None
        if tgt is not None:
            tol = target_tolerance(name, tgt)
            status = "within tolerance" if abs(value - tgt) <= tol else "off"
        rows.append({"key": key, "element": element, "name": name, "value": value, "target": tgt, "tol": tol,
                     "status": status})
    for element, tg in sorted(targets.items()):
        for name, tgt in sorted(tg.items()):
            if f"{element}.{name}" not in seen:
                rows.append({"key": f"{element}.{name}", "element": element, "name": name, "value": None,
                             "target": tgt, "tol": target_tolerance(name, tgt), "status": "no value"})
    return rows


def netlist_rows(result: dict) -> list[tuple[str, str, str, str]]:
    """``(element, kind, nodes, value)`` rows of a LOM result's netlist (C in fF, L / Lj in nH, ...)."""
    out = []
    types = result.get("branches", {})
    for r in result.get("netlist", []):
        v, unit = r.get("value"), r.get("unit", "") or ""
        if isinstance(v, (list, tuple)):  # a pair such as a resonator's (C, L) with unit "fF, nH": one unit per value
            units = [u.strip() for u in unit.split(",")]
            if len(units) != len(v):
                units = [unit] * len(v) if len(units) == 1 else [""] * len(v)
            val = " ‖ ".join(f"{_fmt_num(x)} {u}".strip() for x, u in zip(v, units))
        elif isinstance(v, (int, float)):
            val = f"{v:.4g} {unit}".strip()
        else:
            val = f"{v} {unit}".strip()
        kind = (types.get(r["element"]) or {}).get("type") or r.get("qucat", "")
        out.append((r["element"], kind, " – ".join(map(str, r.get("nodes", []))), val))
    return out


FINGERPRINT_SKIP = ("targets", "sim_groups")  # design.json keys that change neither the layout nor its LOM


def design_fingerprint(design) -> str:
    """A short hash of the design (a dict, or the path of a design.json) without :data:`FINGERPRINT_SKIP`: the Flow
    strip compares it with the one recorded when a step ran, so writing a sim group or a target does not make the
    Check, LOM or Fab marks look out of date. "" when the file cannot be read."""
    import hashlib  # pylint: disable=import-outside-toplevel

    try:
        data = read_design(design) if not isinstance(design, dict) else design
    except (OSError, ValueError):
        return ""
    data = {k: v for k, v in data.items() if k not in FINGERPRINT_SKIP}
    return hashlib.sha1(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()[:16]  # noqa: S324


def marks_path(design_path) -> Path:
    """``<design folder>/build/<stem>.flow/marks.json``: the design fingerprint each Flow step last ran on."""
    design_path = Path(design_path)
    return design_path.parent / "build" / f"{design_path.stem}.flow" / "marks.json"


def read_marks(design_path) -> dict:
    try:
        return json.loads(marks_path(design_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_mark(design_path, step: str, fingerprint: str) -> None:
    """Record that ``step`` ran on the design with ``fingerprint`` (see :func:`flow_status`)."""
    path = marks_path(design_path)
    marks = read_marks(design_path)
    marks[step] = fingerprint
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(marks, indent=1), encoding="utf-8")
    except OSError:
        pass


def flow_status(design_path, sidecar: dict | None) -> dict[str, str]:
    """Which flow steps have been done for the design: ``{step: "done" | "warn" | "todo"}`` for
    ``design check lom simulate results fab`` (cheap file checks; ``warn`` = done but out of date or with issues).

    * check: the sidecar's fast DRC (the panel adds its full check on top);
    * lom: ``build/<stem>/lom.json``, out of date when the design changed since (fingerprint in :func:`marks_path`,
      else file times);
    * simulate: an analysed simulation (``build/<name>/flow.json``, written by the automatic run and by Import
      results), ``warn`` when the design changed since (stale results);
    * results: values in the sidecar's results, ``warn`` when stale or when a target fails (tune: Propose);
    * fab: ``build/<stem>_fab.oas``, ``warn`` when the design changed since the export."""
    status = {k: "todo" for k in ("design", "check", "lom", "simulate", "results", "fab")}
    if design_path is None:
        return status
    design_path = Path(design_path)
    build = design_path.parent / "build"
    stem = design_path.stem
    data = sidecar or {}
    marks = read_marks(design_path)
    now = design_fingerprint(design_path) if marks else ""

    def fresh(step, path):
        if marks.get(step):
            return marks[step] == now
        return design_path.exists() and path.stat().st_mtime >= design_path.stat().st_mtime

    if data.get("instances"):
        status["design"] = "done"
    if "drc" in data:
        issues = [i for i in data.get("drc", []) if i.get("severity") in ("error", "warning")]
        status["check"] = "warn" if issues else "done"
    lom = build / stem / "lom.json"
    if lom.exists():
        status["lom"] = "done" if fresh("lom", lom) else "warn"
    results = data.get("results") or {}
    stale = any(e.get("stale") for e in results.values())
    try:
        name = read_design(design_path).get("name") or stem
    except (OSError, ValueError):
        name = stem
    if (build / name / "flow.json").exists():
        status["simulate"] = "warn" if stale else "done"
    params = [p for e in results.values() for p in e.get("params") or []]
    if any(p.get("value") is not None for p in params):
        failing = any(p.get("status") == "fail" for p in params)
        status["results"] = "warn" if stale or failing else "done"
    fab = build / f"{stem}_fab.oas"
    if fab.exists():
        status["fab"] = "done" if fresh("fab", fab) else "warn"
    return status


# ---- junction values: L_J ↔ I_c ↔ R_n (Ambegaokar–Baratoff, T ≪ T_c; the library's circuit.bridges) ---------------
PHI0_2PI_NH_NA = 329.1059  # Φ0/2π in nH·nA: L_J (nH) = 329.1 / I_c (nA)


def ic_from_lj(lj_nh: float) -> float:
    """I_c (nA) of a junction (or a symmetric SQUID's sum) with L_J ``lj_nh``."""
    return PHI0_2PI_NH_NA / float(lj_nh)


def lj_from_ic(ic_na: float) -> float:
    return PHI0_2PI_NH_NA / float(ic_na)


def ic_from_rn(rn_kohm: float, gap_mev: float = 1.4) -> float:
    """I_c (nA) from the normal resistance: I_c·R_n = πΔ/2e (Δ = ``gap_mev``, the PDK's Nb gap 1.4 meV)."""
    return 3.141592653589793 * float(gap_mev) / 2.0 / float(rn_kohm) * 1e3


def rn_from_ic(ic_na: float, gap_mev: float = 1.4) -> float:
    return 3.141592653589793 * float(gap_mev) / 2.0 / float(ic_na) * 1e3


def junction_triplet(gap_mev: float = 1.4, lj_nh=None, ic_na=None, rn_kohm=None) -> dict:
    """``{"Lj_nH", "Ic_nA", "Rn_kohm"}`` from whichever one is given (the first that is not None)."""
    if lj_nh is not None:
        ic = ic_from_lj(lj_nh)
    elif ic_na is not None:
        ic = float(ic_na)
    elif rn_kohm is not None:
        ic = ic_from_rn(rn_kohm, gap_mev)
    else:
        return {"Lj_nH": None, "Ic_nA": None, "Rn_kohm": None}
    if ic <= 0:
        raise ValueError("L_J, I_c and R_n must be positive")
    return {"Lj_nH": lj_from_ic(ic), "Ic_nA": ic, "Rn_kohm": rn_from_ic(ic, gap_mev)}


# ---- a component's circuit as the LOM sees it (sidecar ``lom.branches``, with values) -----------------------------
def lom_rows(sidecar: dict, element: str) -> list[tuple[str, str, str]]:
    """``[(branch, type, value text)]`` of the LOM branches that belong to ``element`` (an instance or a route): its
    own nodes (``Q1``, ``Q1.claw_n``) or its name in the branch's (``C_Q1``, ``K_R1``, ``R1``)."""
    out = []
    for bname, b in ((sidecar or {}).get("lom") or {}).get("branches", {}).items():
        nodes = [str(n) for n in b.get("nodes", [])]
        mine = (bname == element or bname.endswith(f"_{element}") or f"_{element}_" in bname
                or any(n == element or n.startswith(element + ".") for n in nodes))
        if mine:
            out.append((bname, str(b.get("type", "")), branch_text(b)))
    return out


def branch_text(b: dict) -> str:
    """One line for a LOM branch value: C in fF, L_J / C_J, a resonator line, a hanger's κ, a port."""
    v, t = b.get("value") or {}, b.get("type", "")

    def num(x, unit="", fmt=".4g"):
        return "?" if x is None else f"{float(x):{fmt}}{(' ' + unit) if unit else ''}"

    if t == "C":
        src = str(v.get("estimate_source") or v.get("source") or "")
        return f"{num(v.get('estimate', v.get('C_fF')), 'fF')}" + (f"  ({src.split(' (')[0]})" if src else "")
    if t in ("JJ", "SQUID"):
        lj = v.get("Lj_nH")
        text = f"L_J {num(lj, 'nH')}, C_J {num(v.get('Cj_fF'), 'fF')}"
        return text if lj else text + "  (no L_J: Edit ▸ Edit selected component, junction rows)"
    if t == "L":
        return num(v.get("estimate", v.get("L_nH")), "nH")
    if t == "TLres":
        return (f"{v.get('kind', '')} {num(v.get('length_um'), 'µm', '.0f')} → {num(v.get('f_GHz'), 'GHz')}"
                f", Z0 {num(v.get('Z0_ohm'), 'Ω', '.1f')}")
    if t == "HANGER":
        return (f"coupler {num(v.get('coupling_length_um'), 'µm', 'g')}, strip {num(v.get('ground_gap_um'), 'µm', 'g')}"
                f" → κ {num(v.get('kappa_MHz'), 'MHz', '.3g')}")
    if t == "R":
        return num(v.get("R_ohm"), "Ω", "g")
    return ", ".join(f"{k} {x}" for k, x in v.items() if not isinstance(x, (dict, list)))[:120]


# ---- references to removed components (a delete, an undo, a sim group written earlier) ---------------------------
def scrub_references(design: dict, built: dict | None = None) -> list[str]:
    """Remove what refers to instances / routes that no longer exist, so design.json stays valid: routes ending on a
    removed instance or hanging from a removed route (repeatedly), names in sim groups (a group left empty goes),
    targets, couplings; an instance snapped to a removed one becomes an absolute placement at its last built position
    (``built`` = the sidecar's ``instances``). Returns what changed, one line each."""
    notes = []
    inst, routes = design.get("instances", {}), design.get("routes", {})
    changed = True
    while changed:
        changed = False
        names = set(inst) | set(routes) | {"chip"}
        for rname, r in list(routes.items()):
            for e in (r.get("from"), r.get("to")):
                gone = (isinstance(e, str) and "." in e and e.split(".", 1)[0] not in names) or (
                    isinstance(e, dict) and e.get("hanger") and e["hanger"] not in routes)
                if gone:
                    del routes[rname]
                    notes.append(f"route {rname} removed (its end {e if isinstance(e, str) else e['hanger']} is gone)")
                    changed = True
                    break
    names = set(inst) | set(routes) | {"chip"}
    for name, entry in inst.items():
        place = entry.get("place", {})
        target = place.get("to")
        if "snap" in place and isinstance(target, str) and target.split(".", 1)[0] not in names:
            trans = ((built or {}).get(name) or {}).get("trans")
            if trans:
                entry["place"] = {"at": [_r(trans["at"][0]), _r(trans["at"][1])], "rot": float(trans.get("rot", 0.0))}
                if trans.get("mirror"):
                    entry["place"]["mirror"] = True
                notes.append(f"{name}: was snapped to {target} (removed); now placed where it was")
    for gname, g in list((design.get("sim_groups") or {}).items()):
        sel = [n for n in g.get("select", []) if n in names]
        if sel != g.get("select", []):
            notes.append(f"sim group {gname}: {sorted(set(g.get('select', [])) - set(sel))} removed")
            if sel:
                g["select"] = sel
            else:
                del design["sim_groups"][gname]
                notes.append(f"sim group {gname} removed (empty)")
                continue
        if isinstance(g.get("ports"), dict):
            g["ports"] = {k: v for k, v in g["ports"].items() if k in names}
    if design.get("sim_groups") == {}:
        design.pop("sim_groups")
    for key in [k for k in (design.get("targets") or {}) if k not in names]:
        del design["targets"][key]
        notes.append(f"targets of {key} removed")
    for cname, c in list((design.get("couplings") or {}).items()):
        if any(str(e).split(".", 1)[0] not in names for e in c.get("between", [])):
            del design["couplings"][cname]
            notes.append(f"coupling {cname} removed")
    return notes
