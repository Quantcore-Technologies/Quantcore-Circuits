"""Design → build plan: resolve classes, parameters, snaps and routes outside of any PCell.

The plan is plain JSON-able data that :class:`~quantcore_circuits.layouts.chips.design_chip.DesignChip` replays.
Every element cell is first
built in a scratch layout with *exactly* the parameters the chip will use, so port positions measured here are the
ports of the final layout.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field

from kqcircuits.elements.element import Element
from kqcircuits.elements.waveguide_composite import WaveguideComposite
from kqcircuits.pya_resolver import pya

from quantcore_circuits.design.schema import CHIP, Design, FreeEnd, HangerEnd, split_port_ref
from quantcore_circuits.layouts.ports import Port, check_cell, direction_vector
from quantcore_circuits.layouts.registry import cell_ref, create_cell, default_params, element_cell_ports, resolve_cell
from quantcore_circuits.route.router import RouteEnd, RoutePlan, RoutingError, fix_length, plan_route
from quantcore_circuits.route.waveguide import waveguide_class


class PlacementError(ValueError):
    pass


# Element parameters a KQC Chip passes down to children through ``add_element`` (parameter inheritance).
_INHERITED = ("a", "b", "n", "r", "margin", "face_ids", "protect_opposite_face", "opposing_face_id_groups")


@dataclass
class PlacedInstance:
    name: str
    cell: str  # canonical class path or "static:<path>"
    params: dict
    trans: pya.DCplxTrans
    local_ports: dict[str, Port]

    @property
    def ports(self) -> dict[str, Port]:
        return {n: p.transformed(self.trans) for n, p in self.local_ports.items()}


@dataclass
class FailedRoute:
    """A route that could not be built (``plan_design(keep_going=True)``): why, the path the design asks for, and the
    route's last successful geometry (``last_good``: ``polyline``, ``length``, ... from an earlier build) if any."""

    name: str
    error: str
    attempt: list = field(default_factory=list)  # [start, user nodes..., end] as the design gives them (None: unknown end)
    last_good: dict | None = None


@dataclass
class BuildPlan:
    design: Design
    chip_params: dict
    launchers: str | dict | None
    chip_ports: dict[str, Port]
    instances: dict[str, PlacedInstance] = field(default_factory=dict)
    routes: dict[str, RoutePlan] = field(default_factory=dict)
    frame: dict | None = None  # PDK die frame (asdict of DieFrame) when drawn
    device_id: str = ""
    pad_edge: float | None = None  # PDK pad rule: launcher indent from the die edge (DieFrame.pad_edge)
    cheese: dict | None = None  # PDK band cheese drawn in the build: {"pdk": name, "rule": asdict(CheeseRule)}
    metal: list = field(default_factory=list)  # extra ground (base_metal_addition polygons, chip µm): hanger gaps
    failed: dict[str, FailedRoute] = field(default_factory=dict)  # routes left out (keep_going builds only)
    keep_going: bool = False
    warnings: list = field(default_factory=list)  # last_good.resolve: failed routes replaced by their last good ones

    def port(self, ref: str) -> Port:
        inst, port = split_port_ref(ref)
        ports = self.chip_ports if inst == CHIP else self.instances[inst].ports
        if port not in ports:
            raise PlacementError(f"{ref!r}: no such port; available: {sorted(ports)}")
        return ports[port]

    def all_ports(self) -> dict[str, Port]:
        out = {f"{CHIP}.{n}": p for n, p in self.chip_ports.items()}
        for name, inst in self.instances.items():
            out.update({f"{name}.{n}": p for n, p in inst.ports.items()})
        return out

    def to_json(self) -> str:
        """Serialise what ``DesignChip.build`` needs."""
        data = {
            "launchers": self.launchers,
            "instances": {
                n: {
                    "cell": i.cell,
                    "params": i.params,
                    "trans": i.trans.to_s(),
                    **(
                        {"static_ports": [p.as_dict() for p in i.local_ports.values()]}
                        if i.cell.startswith("static:")
                        else {}
                    ),
                }
                for n, i in self.instances.items()
            },
            "routes": {
                n: {"nodes": r.node_strings(), "params": r.params, **({"joins": r.joins} if r.joins else {})}
                for n, r in self.routes.items()
            },
        }
        if self.frame:
            data["frame"], data["device_id"] = self.frame, self.device_id
        if self.pad_edge is not None:
            data["pad_edge"] = self.pad_edge
        if self.cheese:
            data["cheese"] = self.cheese
        if self.metal:
            data["metal"] = self.metal
        return json.dumps(data, sort_keys=True, default=_json_default)


def _json_default(o):
    if isinstance(o, (pya.DPoint, pya.DVector)):
        return [o.x, o.y]
    raise TypeError(f"not JSON serialisable: {type(o)}")


def chip_parameters(design: Design) -> dict:
    """Parameters of the generated ``DesignChip`` (KQC Chip params + qcc defaults)."""
    x0, y0, x1, y1 = design.chip.box
    params = {"box": pya.DBox(x0, y0, x1, y1), "name_chip": design.name[:16]}
    params.update(design.chip.params)
    if isinstance(params.get("cheese"), dict):  # a design-chosen cheese rule: the plan carries it (cheese_spec)
        params["cheese"] = "pdk"
    if die_frame(design) is not None:
        params.setdefault("frames_enabled", [])  # the PDK die frame replaces KQC's chip frame
    return params


def die_frame(design: Design):
    """The PDK :class:`~quantcore_circuits.pdk.DieFrame` drawn on this design's chip, or None."""
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    if not design.chip.params.get("die_frame", True):
        return None
    return get_pdk(design.pdk).frame


def pad_edge(design: Design) -> float:
    """PDK pad rule: distance of a pad's / launcher's outer etch edge from the die edge (µm). It applies with or
    without the drawn frame, so a simulation build (frame off) keeps the pads where the real chip has them."""
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    return get_pdk(design.pdk).frame.pad_edge


def has_own_cheese(design: Design) -> bool:
    """The design carries its own ground cheese: KQC's whole-area grid on the chip or on a chip-sized cell."""
    if design.chip.params.get("with_grid"):
        return True
    return any(bool((inst.params or {}).get("with_grid")) for inst in design.instances.values())


def pdk_cheese(design: Design) -> bool:
    """Whether the build draws the PDK band cheese (design rule, 2026-11-03: the original design wins).

    Chip parameter ``cheese``: ``"auto"`` (default) — the band unless the design has its own cheese
    (:func:`has_own_cheese`); ``"pdk"`` — the band always; ``"original"`` (or ``False``) — never (the design's own
    cheese, e.g. inside a static cell, or none); a dict — the original design's cheese *rule*, drawn instead of the
    PDK band (:func:`cheese_spec`)."""
    mode = design.chip.params.get("cheese", "auto")
    if isinstance(mode, dict):
        return True
    if mode in (False, "original", "none", "off"):
        return False
    if mode in (True, "pdk", "on"):
        return True
    return not has_own_cheese(design)


def cheese_spec(design: Design) -> dict | None:
    """What the build draws as cheese: ``{"pdk", "rule": asdict(CheeseRule), "edge"}`` or None (:func:`pdk_cheese`).

    ``chip.params.cheese`` as a dict reproduces an original design's own cheese rule (the original wins): any
    :class:`~quantcore_circuits.pdk.CheeseRule` field (``size``, ``gap``, ``rows``, ``clearance``) over the PDK's,
    plus ``edge`` (µm): no holes within that distance of the die edge. A whole-area cheese like Quantum Metal's GDS
    renderer (25 µm squares on a 100 µm pitch, 25 µm from all geometry, 200 µm from the edge) is
    ``{"size": 25, "gap": 75, "rows": 1000, "clearance": 25, "edge": 200}``."""
    from quantcore_circuits.pdk import CheeseRule, get_pdk  # pylint: disable=import-outside-toplevel

    if not pdk_cheese(design):
        return None
    rule = asdict(get_pdk(design.pdk).cheese)
    mode = design.chip.params.get("cheese")
    edge = None
    if isinstance(mode, dict):
        unknown = set(mode) - set(rule) - {"edge"}
        if unknown:
            raise ValueError(f"chip cheese rule: unknown field(s) {sorted(unknown)}; use {sorted(rule)} + 'edge'")
        rule.update({k: v for k, v in mode.items() if k != "edge"})
        edge = mode.get("edge")
        CheeseRule(**rule)  # validates the field types
    return {"pdk": design.pdk, "rule": rule, "edge": edge}


# PDK default junction (decision #36: every junction of the Quantcore PDK is the trilayer Quantcore junction): KQC /
# Metal junction defaults → the Quantcore cell; "Sim", "No Squid" and explicit choices are kept
_PDK_JUNCTION = {
    "Manhattan": "Quantcore Squid",
    "Manhattan Single Junction": "Quantcore Junction",
    "QCD1": "Quantcore Squid",
    "Metal": "Quantcore Junction",
}


def pdk_junction_type(cls, own: dict) -> str | None:
    """The PDK trilayer junction a cell draws when the instance's ``own`` parameters leave ``junction_type`` unset and
    the cell's default is a KQC / Metal junction (``"Manhattan"`` → ``"Quantcore Squid"``, ...), else None (the
    default is kept, the instance sets it, the cell is a junction cell or has no ``junction_type``). The build
    (:func:`element_params`) and the LOM / simulation junction (``lom.fragment.cell_params``) both use it."""
    schema = cls.get_schema()
    if "junction_type" not in schema or "junction_type" in own or getattr(cls, "qcc_category", "") == "junction":
        return None
    return _PDK_JUNCTION.get(schema["junction_type"].default)


def default_junction_type(cell: str) -> str | None:
    """The junction a cell draws when a design leaves ``junction_type`` unset (the PDK trilayer for KQC / Metal
    qubits), or None for cells without one."""
    if cell.startswith("static:"):
        return None
    try:
        cls = resolve_cell(cell)
    except Exception:  # noqa: BLE001
        return None
    schema = cls.get_schema()
    if "junction_type" not in schema:
        return None
    default = schema["junction_type"].default
    if getattr(cls, "qcc_category", "") == "junction":
        return default
    return _PDK_JUNCTION.get(default, default)


def inherited_params(chip_params: dict) -> dict:
    from quantcore_circuits.layouts.chips.design_chip import DesignChip  # pylint: disable=import-outside-toplevel

    base = default_params(DesignChip)
    return {k: chip_params.get(k, base[k]) for k in _INHERITED if k in base}


def pcell_params(cls: type[Element], own: dict) -> dict:
    """PCell parameters for a design's instance parameters.

    A wrapper cell (e.g. ``metal:<Class>``) whose user-facing parameters are not its PCell schema converts them with
    a classmethod ``qcc_params(params) -> dict``; for other cells they are the same.
    """
    hook = getattr(cls, "qcc_params", None)
    return hook(dict(own)) if hook is not None else dict(own)


def element_params(cls: type[Element], inherited: dict, own: dict) -> dict:
    """Full parameter set for a child element, matching KQC ``add_element`` inheritance."""
    schema = cls.get_schema()
    params = {k: v for k, v in inherited.items() if k in schema}
    if "name_brand" in schema:  # whole KQC chips used as cells draw a frame with a brand: Quantcore's (design rule)
        params["name_brand"] = "QCT"
    pdk_jt = pdk_junction_type(cls, own)
    if pdk_jt is not None:  # unset → the PDK trilayer junction
        params["junction_type"] = pdk_jt
    params.update(pcell_params(cls, own))
    return params


def snap_trans(own: Port, target: Port, mirror: bool = False, gap: float = 0.0) -> pya.DCplxTrans:
    """Transform that puts ``own`` (local) onto ``target`` (absolute), facing each other."""
    if own.dir is None or target.dir is None:
        raise PlacementError(f"cannot snap {own.name!r} to {target.name!r}: both ports need a direction (corner)")
    m = pya.DCplxTrans(1, 0, mirror, 0, 0)
    d_own = m * own.dir
    want = -target.dir
    angle = math.degrees(math.atan2(want.y, want.x) - math.atan2(d_own.y, d_own.x)) % 360.0
    if abs(angle - round(angle)) < 1e-9:
        angle = float(round(angle)) % 360.0
    rot = pya.DCplxTrans(1, angle, mirror, 0, 0)
    disp = (target.pos + target.dir * gap) - rot * own.pos
    return pya.DCplxTrans(1, angle, mirror, disp.x, disp.y)


def _etch_bbox(cell: pya.Cell) -> pya.DBox:
    """Local bounding box of a cell's etch (``base_metal_gap_wo_grid`` of every face), else of the whole cell."""
    from kqcircuits.defaults import default_faces  # pylint: disable=import-outside-toplevel

    layout = cell.layout()
    box = pya.DBox()
    for face in default_faces.values():
        info = face.get("base_metal_gap_wo_grid")
        li = layout.find_layer(info) if info is not None else None
        if li is not None:
            box += cell.dbbox_per_layer(li)
    return box if not box.empty() else cell.dbbox()


def edge_trans(name: str, trans: pya.DCplxTrans, local_box, chip_box, edge: str, gap: float) -> pya.DCplxTrans:
    """``trans`` slid perpendicular to die edge ``edge`` (n/s/e/w/auto) so the instance's etch ends ``gap`` µm from
    it (PDK pad rule, :attr:`~quantcore_circuits.pdk.DieFrame.pad_edge`)."""
    if local_box is None or local_box.empty():
        raise PlacementError(f"{name}: 'edge' placement needs a cell with an etch (not a static cell)")
    x0, y0, x1, y1 = chip_box
    b = local_box.transformed(trans)
    if edge == "auto":
        c = trans.disp
        dist = {"w": c.x - x0, "e": x1 - c.x, "s": c.y - y0, "n": y1 - c.y}
        edge = min(dist, key=dist.get)
    shift = {
        "w": pya.DVector(x0 + gap - b.left, 0),
        "e": pya.DVector(x1 - gap - b.right, 0),
        "s": pya.DVector(0, y0 + gap - b.bottom),
        "n": pya.DVector(0, y1 - gap - b.top),
    }[edge]
    return pya.DCplxTrans(shift) * trans


def _placement_order(design: Design) -> list[str]:
    """Topological order of instances by snap dependencies; raises on cycles."""
    deps = {}
    for name, inst in design.instances.items():
        deps[name] = set()
        if inst.place.is_snap:
            target, _ = split_port_ref(inst.place.to)
            if target != CHIP:
                deps[name].add(target)
    order, state = [], {}

    def visit(n, stack):
        if state.get(n) == "done":
            return
        if state.get(n) == "active":
            cycle = stack[stack.index(n) :] + [n]
            raise PlacementError("snap cycle: " + " -> ".join(cycle))
        state[n] = "active"
        for d in sorted(deps[n]):
            visit(d, stack + [d])
        state[n] = "done"
        order.append(n)

    for n in design.instances:
        visit(n, [n])
    return order


def _route_order(design: Design) -> list[str]:
    """Routes ordered so that hanger targets are planned before the routes hanging off them."""
    deps = {n: {e.hanger for e in (r.from_, r.to) if isinstance(e, HangerEnd)} for n, r in design.routes.items()}
    order, state = [], {}

    def visit(n, stack):
        if state.get(n) == "done":
            return
        if state.get(n) == "active":
            raise RoutingError("hanger cycle: " + " -> ".join(stack[stack.index(n) :] + [n]))
        state[n] = "active"
        for d in sorted(deps[n]):
            visit(d, stack + [d])
        state[n] = "done"
        order.append(n)

    for n in design.routes:
        visit(n, [n])
    return order


def _route_end(plan: BuildPlan, end, a, b, r) -> RouteEnd:
    if isinstance(end, FreeEnd):
        return RouteEnd.from_free(end)
    if isinstance(end, HangerEnd):
        return _hanger_end(plan, end, a, b, r)
    return RouteEnd.from_port(plan.port(end))


def _nearest_arclength(pts: list, near) -> float:
    """Arclength along polyline ``pts`` of its point nearest to ``near``."""
    best, best_s, acc = None, 0.0, 0.0
    for p, q in zip(pts[:-1], pts[1:]):
        v = q - p
        seg = v.length()
        u = 0.0 if seg == 0 else max(0.0, min(1.0, ((near.x - p.x) * v.x + (near.y - p.y) * v.y) / (seg * seg)))
        d = (p + v * u - near).length()
        if best is None or d < best - 1e-9:
            best, best_s = d, acc + u * seg
        acc += seg
    return best_s


def _hanger_end(plan: BuildPlan, h: HangerEnd, a: float, b: float, r: float) -> RouteEnd:
    """Coupler parallel to route ``h.hanger`` centred at arclength ``h.s`` along its node polyline."""
    if h.hanger in plan.failed:
        raise RoutingError(f"it hangs on route {h.hanger!r}, which failed: {plan.failed[h.hanger].error}")
    target = plan.routes[h.hanger]
    pts = target.polyline()
    s_c = h.s if h.s is not None else _nearest_arclength(pts, pya.DPoint(*h.near))
    acc = 0.0
    for p, q in zip(pts[:-1], pts[1:]):
        seg = (q - p).length()
        if acc - 1e-9 <= s_c <= acc + seg + 1e-9:
            if s_c - h.length / 2 < acc - 1e-6 or s_c + h.length / 2 > acc + seg + 1e-6:
                raise RoutingError(
                    f"hanger on {h.hanger!r}: coupler [{s_c - h.length / 2:.1f}, {s_c + h.length / 2:.1f}] µm must lie "
                    f"on one straight segment ([{acc:.1f}, {acc + seg:.1f}] µm)"
                )
            t = (q - p) / seg
            centre = p + t * (s_c - acc)
            break
        acc += seg
    else:
        raise RoutingError(f"hanger on {h.hanger!r}: s={s_c} µm is beyond the route length {acc:.1f} µm")
    n = pya.DVector(-t.y, t.x) if h.side == "left" else pya.DVector(t.y, -t.x)
    a_l, b_l = target.params["a"], target.params["b"]
    b_l_in = b_l if h.line_gap is None else float(h.line_gap)  # the facing gaps (narrowed: closer centre lines)
    b_r_in = b if h.coupler_gap is None else float(h.coupler_gap)
    d = a_l / 2 + b_l_in + h.ground_gap + b_r_in + a / 2
    if h.coupler_gap is not None or h.line_gap is not None:
        if not (0 < b_l_in <= b_l and 0 < b_r_in <= b):
            raise RoutingError(f"hanger on {h.hanger!r}: coupler_gap / line_gap must be > 0 and at most the CPW gaps "
                               f"({b:g} / {b_l:g} µm)")
        if b - b_r_in > b_l_in + h.ground_gap + 1e-9 or b_l - b_l_in > b_r_in + h.ground_gap + 1e-9:
            raise RoutingError(f"hanger on {h.hanger!r}: gaps narrowed by more than the facing gap + ground strip; "
                               "raise ground_gap or narrow less")
        # the ground strip between the narrowed gaps, over the coupler length: drawn as extra metal by the build
        u1, u2 = a_l / 2 + b_l_in, d - a / 2 - b_r_in
        ends = (centre - t * (h.length / 2), centre + t * (h.length / 2))
        plan.metal.append([[round(q.x, 4), round(q.y, 4)] for q in
                           (ends[0] + n * u1, ends[1] + n * u1, ends[1] + n * u2, ends[0] + n * u2)])
    c_minus = centre - t * (h.length / 2) + n * d
    c_plus = centre + t * (h.length / 2) + n * d
    first, last = (c_minus, c_plus) if h.direction == "forward" else (c_plus, c_minus)
    term = 0.0 if h.end == "short" else h.open_gap
    if not h.bend:  # straight entry: the route runs into the coupler along its own axis
        axis = (last - first) / (last - first).length()
        return RouteEnd(last, None, a, b, term=term, approach=[first - axis * r, first])
    return RouteEnd(last, None, a, b, term=term, approach=[first + n * r, first])


def launcher_spec(launchers) -> str | dict | None:
    """JSON form of ``Chip.launchers`` (a sample-holder name or a :class:`~quantcore_circuits.design.Launchers`)."""
    return launchers.model_dump(mode="json") if hasattr(launchers, "model_dump") else launchers


def _launcher_ports(launchers, chip_params: dict, edge: float | None = None) -> dict[str, Port]:
    """Chip-level launcher ports, measured from a launcher-only DesignChip (``edge``: the PDK pad rule)."""
    from quantcore_circuits.layouts.chips.design_chip import DesignChip  # pylint: disable=import-outside-toplevel

    layout = pya.Layout()
    params = {k: v for k, v in chip_params.items() if k in ("box", "a", "b", "r", "face_ids")}
    spec = {"launchers": launcher_spec(launchers), "instances": {}, "routes": {}}
    if edge is not None:
        spec["pad_edge"] = edge
    plan = json.dumps(spec)
    cell = check_cell(DesignChip.create(layout, plan=plan, frames_enabled=[], **params), "launchers")
    from kqcircuits.defaults import default_layers  # pylint: disable=import-outside-toplevel
    from kqcircuits.elements.element import get_refpoints  # pylint: disable=import-outside-toplevel

    refp = dict(get_refpoints(layout.layer(default_layers["refpoints"]), cell, pya.DTrans(), 0))
    # launcher refpoints are "<name>_port" / "<name>_port_corner" (inserted with inst_name)
    ports = {}
    for key, pos in refp.items():
        if key.endswith("_port") and f"{key}_corner" in refp:
            name = key[: -len("_port")]
            v = refp[f"{key}_corner"] - pos
            ports[name] = Port(name, pos, v / v.length(), chip_params.get("a"), chip_params.get("b"))
    return ports


def plan_design(
    design: Design, scratch: pya.Layout | None = None, keep_going: bool = False, last_good: dict | None = None
) -> BuildPlan:
    """Resolve a design into a :class:`BuildPlan`. Raises on any placement or routing problem.

    ``keep_going`` (the plugin's builds): a route that cannot be built does not stop the rest. It is left out of
    ``plan.routes`` and listed in ``plan.failed`` with the reason, the path the design asks for and, from ``last_good``
    (``{route: stored geometry}``, see :mod:`quantcore_circuits.assembly.last_good`), the route's last good geometry.
    A route hanging on a failed route fails with its own reason. Placement problems still raise.
    """
    from quantcore_circuits.layouts.chips.design_chip import ensure_registered  # pylint: disable=import-outside-toplevel

    ensure_registered()
    scratch = scratch or pya.Layout()
    chip_params = chip_parameters(design)
    inherited = inherited_params(chip_params)
    edge = pad_edge(design)
    chip_ports = _launcher_ports(design.chip.launchers, chip_params, edge) if design.chip.launchers else {}
    plan = BuildPlan(design, chip_params, launcher_spec(design.chip.launchers), chip_ports, pad_edge=edge)
    frame = die_frame(design)
    if frame is not None:
        plan.frame = asdict(frame)
        plan.device_id = str(design.chip.params.get("name_chip", design.name[:16]))
    plan.cheese = cheese_spec(design)

    # 1. element cells and local ports
    local = {}
    etch_boxes = {}  # local etch bounding boxes of the instances placed at a die edge (place.edge)
    for name, inst in design.instances.items():
        if inst.cell.startswith("static:"):
            ports = {
                p.name: Port(p.name, pya.DPoint(*p.at), direction_vector(p.dir), p.a, p.b) for p in inst.ports or []
            }
            local[name] = (inst.cell, {}, ports)
            continue
        cls = resolve_cell(inst.cell)
        params = element_params(cls, inherited, inst.params)
        cell = create_cell(scratch, cls, what=name, **params)
        local[name] = (cell_ref(cls), params, element_cell_ports(cls, cell, params))
        if inst.place.edge:
            etch_boxes[name] = _etch_bbox(cell)

    # 2. placements in dependency order
    for name in _placement_order(design):
        inst = design.instances[name]
        cell, params, ports = local[name]
        if inst.place.is_snap:
            own_name = inst.place.snap.split(".", 1)[1] if "." in inst.place.snap else inst.place.snap
            if own_name not in ports:
                raise PlacementError(f"{name}: no port {own_name!r}; available: {sorted(ports)}")
            target = plan.port(inst.place.to)
            trans = snap_trans(ports[own_name], target, inst.place.mirror, inst.place.gap)
        else:
            x, y = inst.place.at
            trans = pya.DCplxTrans(1, inst.place.rot, inst.place.mirror, x, y)
            if inst.place.edge:
                trans = edge_trans(name, trans, etch_boxes.get(name), design.chip.box, inst.place.edge, edge)
        plan.instances[name] = PlacedInstance(name, cell, params, trans, ports)

    # 3. routes, in dependency order (hanger targets first)
    route_defaults = {"a": inherited.get("a", 10), "b": inherited.get("b", 6), "r": inherited.get("r", 100)}
    plan.keep_going = keep_going
    for name in _route_order(design):
        route = design.routes[name]
        try:
            plan.routes[name] = _plan_one_route(plan, scratch, name, route, inherited, route_defaults)
        except Exception as e:  # noqa: BLE001  (KQC raises its own errors, e.g. "Straight segment cannot fit")
            if not keep_going:
                raise
            plan.failed[name] = FailedRoute(
                name, _error_text(e, name), _attempt_path(plan, route), (last_good or {}).get(name)
            )
    return plan


def _error_text(e: Exception, name: str) -> str:
    """The reason a route failed, as one line that starts with the route's name."""
    text = " ".join(str(e).split()) or type(e).__name__
    if not isinstance(e, (RoutingError, PlacementError, ValueError)):
        text = f"{type(e).__name__}: {text}"
    return text if text.startswith(f"route {name}") else f"route {name}: {text}"


def _attempt_path(plan: BuildPlan, route) -> list:
    """[start, the design's nodes..., end] of a route (an end that cannot be resolved is None)."""

    def at(end):
        try:
            if isinstance(end, FreeEnd):
                return pya.DPoint(*end.at)
            if isinstance(end, HangerEnd):
                return pya.DPoint(*end.near) if end.near is not None else None
            return plan.port(end).pos
        except Exception:  # noqa: BLE001
            return None

    return [at(route.from_)] + [pya.DPoint(*w.at) for w in route.waypoints()] + [at(route.to)]


def _plan_one_route(plan: BuildPlan, scratch, name: str, route, inherited: dict, route_defaults: dict) -> RoutePlan:
    start = _route_end(plan, route.from_, None, None, None)
    a_r = route.a if route.a is not None else (start.a if start.a is not None else route_defaults["a"])
    b_r = route.b if route.b is not None else (start.b if start.b is not None else route_defaults["b"])
    r_r = route.r if route.r is not None else route_defaults["r"]
    end = _route_end(plan, route.to, a_r, b_r, r_r)
    rplan = plan_route(name, route, start, end, route_defaults)
    rplan.params = {**{k: v for k, v in inherited.items() if k not in rplan.params}, **rplan.params}

    def measure(p):
        cls = waveguide_class(p.nodes)  # per-corner radii → WaveguideCompositeCorners
        cell = create_cell(scratch, cls, what=f"route {name}", nodes=p.nodes, **p.params)
        return cell.length()

    if rplan.target_length is not None:
        rplan = fix_length(rplan, measure, route.meander_segment, route.meanders, direction=route.meander_direction)
    else:
        rplan.length = measure(rplan)
    rplan.joins = _joins(plan, route)
    return rplan


def _joins(plan: BuildPlan, route) -> list:
    """The route's ends at a placed cell's port: ``[{"inst", "node": 0 | -1}]`` (first / last node)."""
    out = []
    for end, node in ((route.from_, 0), (route.to, -1)):
        if isinstance(end, str):
            inst, _ = split_port_ref(end)
            if inst != CHIP and inst in plan.instances:
                out.append({"inst": inst, "node": node})
    return out


__all__ = ["BuildPlan", "FailedRoute", "PlacedInstance", "PlacementError", "RoutingError", "plan_design", "snap_trans"]
