"""Shared QPDK (gdsfactory/quantum-rf-pdk, MIT) replica settings for the notebooks in this folder.

Values are read from the QPDK cell defaults (``qpdk/cells/*.py``, depth-1 clone 2026-11-03); see each spec in
``docs/designs/qpdk/``. Coordinates in the notebooks are Designer coordinates (lower-left chip corner at (0, 0)).
"""

from __future__ import annotations

# QPDK ``launcher``: 200 µm straight wire-bond section (CPW 200/110 µm) + 100 µm taper to the 10/6 µm ``cpw``.
# BondPad's ``pad_gap`` also runs behind the pad, so a launcher takes 410 µm from the chip edge to its port.
LAUNCHER = dict(pad_width=200, pad_height=200, pad_gap=110, taper_length=100)
LAUNCHER_DEPTH = 410.0

# QPDK ``double_pad_transmon_with_bbox`` rotated 90°: two 400 × 250 µm pads, 15 µm apart, in an 800 × 915 µm
# etched pocket (200 µm ``bbox_extension``), + the 394 × 20 µm ``plate_capacitor_single`` coupler (KQC DoublePads).
DOUBLE_PAD = dict(
    island1_extent=[400, 250],
    island2_extent=[400, 250],
    island1_r=0,
    island2_r=0,
    island_island_gap=15,
    ground_gap=[800, 915],
    ground_gap_r=0,
    coupler_extent=[394, 20],
    coupler_r=0,
    coupler_offset=35,
)
DOUBLE_PAD_HALF_H = 915 / 2  # qubit centre → coupler port (pocket edge)

# QPDK ``interdigital_capacitor`` defaults: 4 fingers, 20 µm long, 2 µm gap, 5 µm thick (KQC FingerCapacitorSquare).
IDC = dict(finger_number=4, finger_length=20, finger_gap=2, finger_width=5)

# QPDK ``cpw``: 10 µm centre, 6 µm gap, 100 µm bend radius. ``coupler_straight`` gap 16 µm edge to edge, so the
# KQC hanger ground strip is 26 − 5 − 6 − 6 − 5 = 4 µm.
CPW_R = 100.0
HANGER_GROUND_GAP = 4.0

# Quantcore PDK rebuild. Junctions: no QPDK sample states one, and QPDK's evaporated Al junctions are another
# process, so every SQUID is the Quantcore trilayer SQUID on the PDK rule (Nb Δ 1.4 meV): two 0.25 × 0.6 µm junctions
# (KQC's ``junction_width`` = the straight finger) → R_n 45 kΩ in parallel, L_J 6.73 nH at zero flux, C_J 15 fF.
# ``JJ_PARAMS`` = {"junction_type": "Quantcore Squid", "junction_width": 0.25}; ``JUNCTION`` = its {Lj_nH, Cj_fF}.
from quantcore_circuits.layouts.registry import trilayer_junction  # noqa: E402

LJ_PDK = trilayer_junction("DoublePads")[1]["Lj_nH"]  # PDK nominal L_J (a 0.5 × 0.6 µm junction, R_n 45 kΩ)
JJ_PARAMS, JUNCTION = trilayer_junction("DoublePads", lj_nH=LJ_PDK, squid=True)

# Frame: the Quantcore die frame (the PDK default), so the chip dicts carry no frame settings. The QPDK test chips
# (4.25 × 6.2 and 4.8 × 5.6 mm) sit centred on the 7.5 × 7.5 mm Quantcore die: ``die_box`` keeps their coordinates.
DIE = 7500.0


def die_box(w: float, h: float) -> tuple[float, float, float, float]:
    """The 7.5 mm Quantcore die centred on a QPDK chip box (0, 0, w, h)."""
    return (w / 2 - DIE / 2, h / 2 - DIE / 2, w / 2 + DIE / 2, h / 2 + DIE / 2)


# ---- PDK conformance (notebooks-rest part 1, 2026-11-03) ------------------------------------------------------------
# The Quantcore pad rule puts every launcher ``frame.pad_edge`` (100 µm) from the die edge (``edge="auto"`` in ``d.add``), so on the 7.5 mm
# die the QPDK launchers leave the source's chip area. The centring check therefore measures the *circuit*: every
# instance and route except the bond pads and the lead routes that end on one (the pads would pull the box towards
# whichever edges carry launchers).
def circuit_box(d):
    """Bounding box (µm, ``pya.DBox``) of the circuit: instances and routes without the pads and their lead routes."""
    import sys  # pylint: disable=import-outside-toplevel

    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.assembly import build  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.assembly.sidecar import sidecar_dict  # pylint: disable=import-outside-toplevel

    common = sys.modules.get("_common")
    pads = set(common._pad_instances(d)) if common else set()  # pylint: disable=protected-access
    side = sidecar_dict(build(d.design), overlays=False)
    box = pya.DBox()
    for name, inst in side["instances"].items():
        if name not in pads and inst.get("bbox"):
            box += pya.DBox(*inst["bbox"])
    for name, route in side["routes"].items():
        spec = d.data["routes"][name]
        ends = [spec.get("from"), spec.get("to")]
        if any(isinstance(e, str) and e.split(".", 1)[0] in pads for e in ends):
            continue  # a lead from a pad to the circuit
        for x, y in route.get("polyline") or []:
            box += pya.DPoint(x, y)
    return box


def center_circuit(d, tol: float = 50.0) -> tuple[float, float]:
    """Centre the circuit (:func:`circuit_box`) in the die; returns the shift (µm). Pads placed with ``edge="auto"``
    follow the shift along their edge and stay ``frame.pad_edge`` (100 µm) from it; hangers given by ``s`` follow their
    feedline."""
    import sys  # pylint: disable=import-outside-toplevel

    x0, y0, x1, y1 = d.design.chip.box
    box = circuit_box(d)
    dx = round((x0 + x1) / 2 - box.center().x, 1)
    dy = round((y0 + y1) / 2 - box.center().y, 1)
    if abs(dx) <= tol and abs(dy) <= tol:
        return (0.0, 0.0)
    sys.modules["_common"].translate_design(d, dx, dy)
    return (dx, dy)


def vortex_fill(d, size: float = 15.0, gap: float = 70.0, keepout: float = 80.0):
    """QPDK's ``fill_magnetic_vortices(rectangle_size=(size, size), gap=gap, stagger=2)`` (``qpdk/utils.py``; default
    exclusion 80 µm from M1_ETCH / M1_DRAW / WG) as a PDK :class:`~quantcore_circuits.pdk.CheeseRule` for
    ``export_fab(..., cheese=rule)``: ``size`` µm squares on a ``size + gap`` µm pitch over the whole design area,
    ``keepout`` µm from every route's CPW (the 3/0 keep-out already adds the PDK route margin). The 2 µm row stagger
    is not representable (a CheeseRule is a square grid)."""
    import sys  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    margin = get_pdk(d.design.pdk).keepout.route_margin
    return sys.modules["_common"].original_cheese(size, size + gap, clearance=max(keepout - margin, 0.0), d=d)


def center_content(d, tol: float = 0.5, max_iter: int = 10) -> tuple[float, float]:
    """Centre the *whole layout* in the die, pads included: the content box that ``pdk_report`` measures
    (``_common.content_box``: every instance and route, free text left out) gets its centre on the die centre. Unlike
    :func:`center_circuit`, which leaves the pads out, this one counts them.

    Pads placed with ``edge="auto"`` stay ``frame.pad_edge`` (100 µm) from their die edge and move only along it (a pad
    on the west edge follows the shift in y, not in x), so the content box centre moves by less than the shift of the
    circuit: the step is repeated, each time scaled by the fraction the last one achieved, until the centre is within
    ``tol`` µm. Each pad's edge is fixed to the die edge it sits on before the shift (``"auto"`` would pick the nearest
    edge again, and a pad that slides far along its edge can end up nearer to another one). Returns the total shift
    (dx, dy) of the circuit (µm)."""
    import sys  # pylint: disable=import-outside-toplevel

    common = sys.modules["_common"]
    x0, y0, x1, y1 = d.design.chip.box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    pads = {}
    for name in common._pad_instances(d):  # pylint: disable=protected-access
        at = d.data["instances"][name]["place"].get("at")
        if at is not None:  # the die edge a pad sits on decides along which axis it follows the circuit
            dist = {"w": at[0] - x0, "e": x1 - at[0], "s": at[1] - y0, "n": y1 - at[1]}
            pads[name] = (min(dist, key=dist.get), list(at))
    with d._change("pads: fix the die edge"):  # pylint: disable=protected-access
        for name, (edge, _) in pads.items():
            d.data["instances"][name]["place"]["edge"] = edge
    total, last = [0.0, 0.0], None
    for _ in range(max_iter):
        box = common.content_box(d)
        err = [cx - box.center().x, cy - box.center().y]
        if max(abs(err[0]), abs(err[1])) <= tol:
            break
        step = list(err)
        if last is not None:  # the content moved by a fraction of the last step only (pads stay on their edge)
            for k in (0, 1):
                moved = last[1][k] - err[k]
                if abs(last[0][k]) > 1e-9 and abs(moved) > 1e-9:
                    step[k] = err[k] * last[0][k] / moved
        step = [round(v, 3) for v in step]
        total = [total[0] + step[0], total[1] + step[1]]
        common.translate_design(d, *step, skip_pads=True)
        with d._change(f"pads follow ({step[0]:g}, {step[1]:g}) along their edges"):  # pylint: disable=protected-access
            for name, (edge, at0) in pads.items():
                d.data["instances"][name]["place"]["at"] = [
                    at0[0] + (total[0] if edge in "ns" else 0.0), at0[1] + (total[1] if edge in "we" else 0.0)]
        last = (step, err)
    return (round(total[0], 1), round(total[1], 1))
