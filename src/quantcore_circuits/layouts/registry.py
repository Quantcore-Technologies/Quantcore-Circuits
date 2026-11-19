"""Resolve ``design.json`` cell references to Element classes and introspect their ports."""

from __future__ import annotations

import importlib
import json
import math
from collections.abc import Mapping
from functools import cache

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya

from quantcore_circuits import layouts
from quantcore_circuits.layouts.ports import Port, cell_ports, check_cell

# KQC libraries searched for bare class names, as (library path, library name)
_KQC_LIBRARIES = (
    ("elements", "Element Library"),
    ("junctions", "Junction Library"),
    ("qubits", "Qubit Library"),
    ("chips", "Chip Library"),
    ("test_structures", "Test Structure Library"),
)


@cache
def resolve_cell(ref: str) -> type[Element]:
    """Resolve a cell reference.

    Accepts a dotted class path (``"kqcircuits.qubits.swissmon.Swissmon"``, ``"quantcore_circuits.layouts.Xmon"``),
    a bare class name of any quantcore_circuits/KQC PCell (``"Xmon"``, ``"Swissmon"``, ``"FingerCapacitorSquare"``),
    or ``"metal:<Class>"`` for a Quantum Metal qlibrary component (``"metal:TransmonPocket"``).
    """
    if ref.startswith("static:"):
        raise ValueError("static cells are not Element classes; handle them with quantcore_circuits.assembly")
    if ref.startswith("metal:"):
        from quantcore_circuits.layouts.metal import resolve  # pylint: disable=import-outside-toplevel

        return resolve(ref)
    if "." in ref:
        module_name, _, cls_name = ref.rpartition(".")
        try:
            module = importlib.import_module(module_name)
        except ImportError as e:
            raise ValueError(f"cannot import {module_name!r} for cell {ref!r}: {e}") from e
        cls = getattr(module, cls_name, None)
        if cls is None:
            raise ValueError(f"{module_name!r} has no cell {cls_name!r}")
        return cls
    import quantcore_circuits.layouts as comps  # pylint: disable=import-outside-toplevel

    cls = getattr(comps, ref, None)
    if isinstance(cls, type) and issubclass(cls, Element):
        return cls
    from kqcircuits.util.library_helper import element_by_class_name  # pylint: disable=import-outside-toplevel

    layouts.ensure_loaded()
    for path, name in _KQC_LIBRARIES:
        found = element_by_class_name(ref, path, name)
        if found is not None:
            return found
    raise ValueError(f"unknown cell {ref!r}")


def cell_ref(cls: type[Element]) -> str:
    """Canonical reference string for a class (inverse of :func:`resolve_cell`)."""
    return f"{cls.__module__}.{cls.__name__}"


def default_params(cls: type[Element]) -> dict:
    return {name: p.default for name, p in cls.get_schema().items() if not name.startswith("_")}


def _shape(value):
    """A JSON shape → KLayout object for a KQC ``TypeShape`` parameter.

    ``[[x, y], ...]`` or ``{"points": [[x, y], ...], "width": w}`` → ``pya.DPath``; ``{"polygon": [[x, y], ...]}`` →
    ``pya.DPolygon``; a KLayout string (``"(0,0;100,0) w=10 bx=0 ex=0 r=false"``) → ``pya.DPath.from_s``. Anything else
    (already a ``DPath``/``DPolygon``) passes through.
    """
    if isinstance(value, str) and value.strip().startswith("("):
        return pya.DPath.from_s(value)
    if isinstance(value, dict) and "polygon" in value:
        return pya.DPolygon([pya.DPoint(float(x), float(y)) for x, y in value["polygon"]])
    if isinstance(value, dict) and "points" in value:
        pts = [pya.DPoint(float(x), float(y)) for x, y in value["points"]]
        return pya.DPath(pts, float(value.get("width", 0.0)))
    if isinstance(value, (list, tuple)) and value and all(isinstance(p, (list, tuple)) and len(p) == 2 for p in value):
        return pya.DPath([pya.DPoint(float(x), float(y)) for x, y in value], 0.0)
    return value


def shape_params(cls: type[Element], params: dict) -> dict:
    """``params`` with JSON shapes converted for the class's ``TypeShape`` parameters (``design.json`` stores shapes as
    point lists; KQC expects ``pya.DPath``/``DPolygon``)."""
    from kqcircuits.util.parameters import pdt  # pylint: disable=import-outside-toplevel

    schema = cls.get_schema()
    return {k: _shape(v) if k in schema and schema[k].data_type == pdt.TypeShape else v for k, v in params.items()}


def create_cell(layout: pya.Layout, cls: type[Element], what: str = "", **params) -> pya.Cell:
    """``cls.create`` that raises :class:`CellBuildError` instead of silently producing an error cell."""
    unknown = set(params) - set(cls.get_schema())
    if unknown:
        raise ValueError(f"{what or cls.__name__}: unknown parameter(s) {sorted(unknown)} for {cls.__name__}")
    return check_cell(cls.create(layout, **shape_params(cls, params)), what or cls.__name__)


def _float_list(value, i: int, default: float) -> float:
    try:
        return float(list(value)[i])
    except (TypeError, ValueError, IndexError):
        return default


def _taper_b(p: dict) -> dict:
    a2, b2 = float(p.get("a2", -1)), float(p.get("b2", -1))
    return {"b": (p["a"] if a2 < 0 else a2, p["b"] if b2 < 0 else b2)}


def _airbridge_connection(p: dict) -> dict:
    # the right taper is WaveguideCoplanarTaper(a=bridge_width, b=bridge_gap_width) with its own a2/b2 defaults
    if not p.get("with_right_waveguide", True):
        return {}
    from kqcircuits.elements.waveguide_coplanar_taper import (  # pylint: disable=import-outside-toplevel
        WaveguideCoplanarTaper,
    )

    schema = WaveguideCoplanarTaper.get_schema()
    a, b = float(p.get("bridge_width", 20)), float(p.get("bridge_gap_width", 12))
    return _taper_b({"a": a, "b": b, "a2": schema["a2"].default, "b2": schema["b2"].default})


def _fluxline_straight(p: dict) -> dict:
    g = float(p.get("fluxline_gap_width", 3))
    return {"flux": (float(p["a"]) / float(p["b"]) * g, g)}


def _quarter_wave(p: dict) -> dict:
    return {"resonator_b": (float(p.get("res_a", 10)), float(p.get("res_b", 10)))}


def _swissmon(p: dict) -> dict:
    # coupler ports sit in the qubit's own gap (wider than b): only the centre width is the port's
    return {f"cplr{i}": (_float_list(p.get("port_width"), i, p["a"]), p["b"]) for i in range(3)}


def _circular_couplers(p: dict) -> dict:
    n = len(list(p.get("couplers_a") or []))
    return {
        f"coupler_{i + 1}": (_float_list(p.get("couplers_a"), i, p["a"]), _float_list(p.get("couplers_b"), i, p["b"]))
        for i in range(n)
    }


# Port CPW widths of KQC classes whose ports are not drawn at the element's a/b (audit issue 4), by exact class
# (``module.qualname``): {port: (a, b)} from the full parameter dict, as a Quantcore class's ``qcc_port_widths``
KQC_PORT_WIDTHS = {
    "kqcircuits.elements.waveguide_coplanar_taper.WaveguideCoplanarTaper": _taper_b,
    "kqcircuits.elements.airbridge_connection.AirbridgeConnection": _airbridge_connection,
    "kqcircuits.elements.fluxlines.fluxline_straight.FluxlineStraight": _fluxline_straight,
    "kqcircuits.elements.quarter_wave_cpw_resonator.QuarterWaveCpwResonator": _quarter_wave,
    "kqcircuits.qubits.swissmon.Swissmon": _swissmon,
    "kqcircuits.qubits.circular_transmon_single_island.CircularTransmonSingleIsland": _circular_couplers,
    "kqcircuits.qubits.concentric_transmon.ConcentricTransmon": _circular_couplers,
}


def port_width_hook(cls: type[Element]):
    """``qcc_port_widths`` of a class, or the :data:`KQC_PORT_WIDTHS` entry of a KQC class, or None."""
    hook = getattr(cls, "qcc_port_widths", None)
    return hook if hook is not None else KQC_PORT_WIDTHS.get(f"{cls.__module__}.{cls.__qualname__}")


def _unit(dx: float, dy: float) -> pya.DVector:
    length = math.hypot(dx, dy)
    x, y = dx / length, dy / length
    # exact axis directions stay exact (as ports.direction_vector)
    return pya.DVector(*(round(v) if abs(v - round(v)) < 1e-12 else v for v in (x, y)))


def x_coupler_arms(p: dict) -> dict[str, list[tuple[float, float]]]:
    """Centre lines of the four arms of KQC ``CapacitiveXCoupler`` (its ``build``): arm-end refpoint name →
    ``[end, (bend), capacitor centre]`` in µm. Each arm is a CPW (the element a/b) from its end through a
    FingerCapacitorSquare (at the last point) to the centre splitter at the origin. '+': p11 S, p21 E, p31 N, p41 W;
    'x': the corners (p11 lower left, counter-clockwise), with a straight lead along the longer side when the box is
    not square."""
    length, height = float(p.get("x_coupler_length", 500)), float(p.get("x_coupler_height", 500))
    center, lead = min(length, height), abs(length - height) / 2
    if str(p.get("x_coupler_variant", "+")) == "x":
        if height > length:
            base = [(-center / 2, -lead - length / 2), (-length / 2, -center / 2), (-length / 4, -center / 4)]
        else:
            base = [(-lead - center / 2, -height / 2), (-center / 2, -height / 2), (-center / 4, -height / 4)]
        signs = {"p11": (1, 1), "p21": (-1, 1), "p31": (-1, -1), "p41": (1, -1)}
        arms = {k: [(sx * x, sy * y) for x, y in base] for k, (sx, sy) in signs.items()}
    else:
        v = [(0.0, -height / 2), (0.0, -height / 3), (0.0, -height / 4)]
        h = [(length / 2, 0.0), (length / 3, 0.0), (length / 4, 0.0)]
        arms = {"p11": v, "p21": h, "p31": [(-x, -y) for x, y in v], "p41": [(-x, -y) for x, y in h]}
    # a square 'x' box has no bend (KQC drops the coinciding node)
    return {k: [q for i, q in enumerate(pts) if i == 0 or q != pts[i - 1]] for k, pts in arms.items()}


def _x_coupler_ports(refpoints: dict, p: dict) -> dict[str, Port]:
    """KQC ``CapacitiveXCoupler`` draws no port refpoints, only its arm ends ``p11``..``p41`` (the refpoints of
    KQC's own ``get_sim_ports``): each is a flush CPW end (element a/b) facing out along its arm."""
    ports = {}
    for name, pts in x_coupler_arms(p).items():
        if name in refpoints and len(pts) > 1:
            (x0, y0), (x1, y1) = pts[0], pts[1]
            ports[name] = Port(name, refpoints[name], _unit(x0 - x1, y0 - y1), p.get("a"), p.get("b"))
    return ports


def _curved_ports(refpoints: dict, p: dict) -> dict[str, Port]:  # noqa: ARG001
    """KQC ``WaveguideCoplanarCurved`` (origin at the arc centre, arc of radius r from angle 0 to ``alpha``) draws no
    ports: ``a`` at (r, 0) and ``b`` at angle ``alpha``, both flush CPW ends facing out along the tangent."""
    r, alpha = float(p.get("r", 100)), float(p.get("alpha", math.pi))
    s = 1.0 if alpha >= 0 else -1.0
    c, si = math.cos(alpha), math.sin(alpha)
    return {
        "a": Port("a", pya.DPoint(r, 0), pya.DVector(0, -s), p.get("a"), p.get("b")),
        "b": Port("b", pya.DPoint(r * c, r * si), _unit(-s * si, s * c), p.get("a"), p.get("b")),
    }


# Ports of KQC classes that draw no port refpoints although their CPW ends are well defined, by exact class
# (``module.qualname``): ``fn(refpoints, full params) -> {name: Port}`` (local frame). A port the cell itself declares
# (``port_<name>`` refpoint) wins over the override. Metadata only: the drawing is not touched.
KQC_EXTRA_PORTS = {
    "kqcircuits.elements.capacitive_x_coupler.CapacitiveXCoupler": _x_coupler_ports,
    "kqcircuits.elements.waveguide_coplanar_curved.WaveguideCoplanarCurved": _curved_ports,
}


def element_cell_ports(cls: type[Element], cell: pya.Cell, params: dict) -> dict[str, Port]:
    """Ports of an already created element cell, with CPW widths.

    ``a``/``b`` come from the element parameters; a class may override them per port with a classmethod
    ``qcc_port_widths(params) -> {port_name: (a, b)}`` (e.g. the Xmon claw tails); KQC classes get theirs from
    :data:`KQC_PORT_WIDTHS`. KQC classes without port refpoints get theirs from :data:`KQC_EXTRA_PORTS`.
    """
    full = {**default_params(cls), **params}
    ports = cell_ports(cell, full.get("a"), full.get("b"))
    extra = KQC_EXTRA_PORTS.get(f"{cls.__module__}.{cls.__qualname__}")
    if extra is not None:
        from kqcircuits.defaults import default_layers  # pylint: disable=import-outside-toplevel
        from kqcircuits.elements.element import get_refpoints  # pylint: disable=import-outside-toplevel

        refp = dict(get_refpoints(cell.layout().layer(default_layers["refpoints"]), cell, pya.DTrans(), 0))
        for name, port in extra(refp, full).items():
            ports.setdefault(name, port)
    hook = port_width_hook(cls)
    if hook is not None:
        for name, (a, b) in hook(full).items():
            if name in ports:
                ports[name].a, ports[name].b = a, b
    return ports


def element_ports(cls: type[Element], layout: pya.Layout | None = None, **params) -> dict[str, Port]:
    """Ports of an element in its local frame (builds the cell in ``layout`` or a scratch layout)."""
    layout = layout or pya.Layout()
    cell = create_cell(layout, cls, **params)
    return element_cell_ports(cls, cell, params)


# KQC base-element parameters a designer does not set by hand (faces, protection, EPR preview, simulation junction pads)
_SCHEMA_SKIP = {
    "n", "margin", "face_ids", "display_name", "protect_opposite_face", "opposing_face_id_groups",
    "duplicate_face_ids", "duplicate_layers", "etch_opposite_face", "etch_opposite_face_margin",
    "junction_total_length", "junction_upper_pad_width", "junction_upper_pad_length", "junction_lower_pad_width",
    "junction_lower_pad_length", "include_background_gap",
}


def element_schema(cls: type[Element]) -> list[dict]:
    """The parameters a designer edits, for the KLayout panel: ``[{"name", "default", "type", "description",
    "unit", "choices"}]`` (JSON-safe defaults; internal / face / EPR parameters left out)."""
    out = []
    for name, p in cls.get_schema().items():
        if name.startswith("_") or name in _SCHEMA_SKIP or getattr(p, "hidden", False):
            continue
        default = p.default
        try:
            json.dumps(default)
        except TypeError:
            continue  # layers, shapes, points: not edited as text
        kw = getattr(p, "kwargs", None) or {}
        choices = kw.get("choices") or getattr(p, "choices", None) or []
        out.append({
            "name": name,
            "default": default,
            "type": type(default).__name__,
            "description": p.description,
            "unit": kw.get("unit") or getattr(p, "unit", None) or "",
            "choices": [c[1] if isinstance(c, (list, tuple)) else c for c in choices],
        })
    return out


def element_outline(cls: type[Element], max_points: int = 400, **params) -> dict:
    """A light outline of an element in its local frame, for a placement preview (the KLayout plugin's ghost):
    ``{"bbox": [x0, y0, x1, y1], "outline": [[[x, y], ...], ...], "ports": [...]}`` in µm.

    The outline is the merged etched shape (the ``base_metal_gap`` layers; else every drawn layer), smoothed so the preview stays a few hundred points; a
    shape too fine to keep (junction fingers) is dropped, the bbox always stays."""
    layout = pya.Layout()
    cell = create_cell(layout, cls, **params)
    ports = element_cell_ports(cls, cell, params)
    region = pya.Region()
    names = {li: layout.get_info(li).name or "" for li in layout.layer_indexes()}
    gap = [li for li, n in names.items() if "base_metal_gap" in n]  # the etched shape: what the component looks like
    skip = ("avoidance", "refpoints", "ports", "spacer", "SIS_junction")
    for li in gap or [li for li, n in names.items() if not any(k in n for k in skip)]:
        region.insert(cell.begin_shapes_rec(li))
    region.merge()
    bbox = cell.dbbox()
    out: list = []
    if not region.is_empty():
        size = max(bbox.width(), bbox.height(), 1.0)
        for frac in (0.002, 0.005, 0.01, 0.02, 0.05):
            d = int(size * frac / layout.dbu)
            simple = region.hulls().smoothed(d).merged() if d else region.hulls()
            polys = [poly for poly in simple.each() if poly.area() * layout.dbu**2 >= (size * frac) ** 2]
            if sum(poly.num_points() for poly in polys) <= max_points:
                out = [[[round(pt.x * layout.dbu, 2), round(pt.y * layout.dbu, 2)] for pt in poly.each_point_hull()]
                       for poly in polys]
                break
    return {
        "bbox": [round(bbox.left, 2), round(bbox.bottom, 2), round(bbox.right, 2), round(bbox.top, 2)],
        "outline": out,
        "ports": [p.as_dict() for p in ports.values()],
    }


def trilayer_junction(cell_ref: str, lj_nH: float | None = None, squid: bool = False, pdk=None) -> tuple[dict, dict]:
    """``(params, junction)`` that make a qubit's junction the Quantcore trilayer junction (design decisions #6 / #21).

    ``params`` are the instance parameters to merge: ``junction_type`` = ``"Quantcore Junction"`` (``squid``:
    ``"Quantcore Squid"``) plus, when ``lj_nH`` is given, the sizing for that L_J (SQUID: the parallel total) on the
    PDK junction rule — ``junction_params: {"lj_nH": ...}`` for cells that forward one (Xmon, ``metal:<Class>``, the
    QPDK / SQDMetal qubits), KQC's ``junction_width`` (straight finger, µm; bent finger at the PDK 0.6 µm) for KQC
    qubits. ``junction`` is the drawn junction's ``{"Lj_nH", "Cj_fF"}`` for the instance's ``junction`` (LOM).
    Without ``lj_nH`` the PDK nominal device is drawn: a 0.5 × 0.6 µm junction (45 kΩ) or a SQUID whose parallel
    R_n is 45 kΩ (two 0.25 × 0.6 µm junctions of 90 kΩ; the window is for the whole SQUID, 2026-11-13).

    >>> params, junction = trilayer_junction("Swissmon", lj_nH=12.0)
    >>> d.add("QB", "Swissmon", junction=junction, **params)  # doctest: +SKIP
    """
    from quantcore_circuits.circuit.bridges import (  # pylint: disable=import-outside-toplevel
        fingers_for_lj,
        junction_from_fingers,
        junction_process,
        lj_from_rn,
    )

    cls = resolve_cell(cell_ref)
    schema = cls.get_schema()
    if "junction_type" not in schema:
        raise ValueError(f"{cell_ref}: no junction_type parameter (not a qubit with a junction)")
    proc = junction_process(pdk)
    n = 2 if squid else 1
    params: dict = {"junction_type": "Quantcore Squid" if squid else "Quantcore Junction"}
    straight, bent = proc.nominal_fingers_um
    if squid and not lj_nH:  # the R_n window is for the whole SQUID (2026-11-13): nominal device, not junction
        straight, bent, _ = fingers_for_lj(lj_from_rn(proc.rn_nominal_kohm * 1e3, proc.gap_meV), n, proc)
    if lj_nH:
        straight, bent, _ = fingers_for_lj(float(lj_nH), n, proc)
        if "junction_params" in schema:
            params["junction_params"] = {"lj_nH": float(lj_nH)}
        elif "junction_width" in schema:
            if abs(bent - proc.bent_finger_um) > 1e-9:  # below the minimum finger the bent finger carries the area
                raise ValueError(
                    f"{cell_ref}: L_J {lj_nH} nH needs a {bent} µm bent finger; KQC qubits only set the straight "
                    "finger (junction_width)"
                )
            params["junction_width"] = straight
        else:
            raise ValueError(f"{cell_ref}: no way to size its junction (no junction_params / junction_width)")
    drawn = junction_from_fingers(straight, bent, n, proc)
    return params, {"Lj_nH": round(drawn.lj_nH, 4), "Cj_fF": round(drawn.cj_fF, 3)}


class _LazyComponents(Mapping):
    """``ref → Element class``; classes are resolved on access (Metal entries import Quantum Metal)."""

    def __init__(self, refs: list[str]):
        self._refs = list(refs)

    def __getitem__(self, ref: str) -> type[Element]:
        if ref not in self._refs:
            raise KeyError(ref)
        return resolve_cell(ref)

    def __iter__(self):
        return iter(self._refs)

    def __len__(self) -> int:
        return len(self._refs)

    def __repr__(self) -> str:
        return f"<{len(self._refs)} components: {', '.join(self._refs[:8])}{', ...' if len(self._refs) > 8 else ''}>"


def list_components(category: str | None = None, source: str | None = None, chips: bool = False) -> Mapping:
    """Components usable as ``cell`` (``ref → class``, resolved lazily), from :func:`.catalog.catalog`.

    Quantcore cells, KQC elements and Quantum Metal components (``metal:<Class>``); whole chips only with
    ``chips=True`` (or ``category="chip"``).
    """
    from quantcore_circuits.layouts.catalog import catalog  # pylint: disable=import-outside-toplevel

    entries = catalog(category=category, source=source, chips=chips or category == "chip")
    return _LazyComponents([c.ref for c in entries])
