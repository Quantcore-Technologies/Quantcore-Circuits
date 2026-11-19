"""Helpers for legacy-b's notebooks in ``examples/designs/legacy/`` (owned by legacy-b; legacy-a owns ``_legacy.py``).

The functions re-derive the legacy chips' own numbers in closed form, exactly as the legacy sources compute them,
so the layout cells stay short and the rebuilt chip cannot drift from the source:

* :func:`d14_plan` — design 14 (``components/python/14.0 Two_feedline_resonator_chip.ipynb``, Quantum Metal): the
  length ↔ frequency calibration (§2), the resonator plan (§5, ``budget()``) and the placement rules (§6).
* :data:`D12_QUBITS`, :data:`D12_RES`, :data:`D12_LINES` — design 12 (``components/python/12.0
  Coupled_chip_layout.ipynb``, Quantum Metal): the qubit, resonator and flux/drive-line tables, and
  :func:`d12_metal_reference`, which rebuilds the legacy design headless in Quantum Metal from the legacy options
  (copied here, nothing is imported from ``components/``) for the comparison.
* :data:`C07_RES` & co. — ``chip_07_resonators.py``; :func:`legacy_chip` / :func:`chip07_reference` draw the legacy
  chip with the legacy PCells through ``tests/legacy_ref`` (read-only), reusing legacy-a's ``_legacy.LegacyChip``
  (imported read-only; legacy-a owns it).

All lengths here are µm, in the legacy (0, 0)-centred frame; the notebooks shift by (+W/2, +H/2).
"""

from __future__ import annotations

import math

# ---- design 14 ---------------------------------------------------------------------------------------------------
# §2: design length (µm) vs simulated f_res (GHz); R7, R8 excluded (they break the monotonic trend)
D14_SIM_TABLE = [
    ("R1", 4740, 6.761),
    ("R2", 4920, 6.525),
    ("R3", 5590, 5.787),
    ("R4", 6000, 5.253),
    ("R5", 5200, 6.188),
    ("R6", 4250, 7.365),
    ("R7", 5840, 4.616),
    ("R8", 4500, 6.443),
]
D14_EXCLUDE = {"R7", "R8"}
D14_FREQS = [6.50, 6.00, 5.50, 5.00, 5.25, 7.00]  # GHz, left → right along each feedline

# §3: layout parameters (legacy mm values, here in µm)
D14 = dict(
    chip=10000.0,
    half=5000.0,
    lp_offset=1900.0,  # launchpad offset from the centre of each edge; feedlines at y = ±1900
    lp_back=940.0,  # launchpad etch behind the taper tip (400 pad + 300 taper + 240 pad gap)
    edge_margin=100.0,
    lead_length=500.0,
    res_gap=36.0,  # short end (coupler centre-line) from the feedline centre-line
    coupler=500.0,  # straight coupling section next to the feedline
    end_straight=150.0,
    fillet=70.0,
    min_pitch=150.0,
    pitch_x=1300.0,
    keepout=1000.0,
    col_half=470.0,
    corridor_margin=60.0,
    qubit_back=623.0,  # claw pin → far edge of the Xmon
    claw_offset=383.0,  # claw pin offset from the Xmon centre
    centre_gap=150.0,
    cheese_size=5.0,
    cheese_pitch=25.0,
    cheese_clear=30.0,
)
D14["lp_inset"] = D14["half"] - D14["edge_margin"] - D14["lp_back"]  # 3960: taper tip
D14["lead_corridor"] = D14["lp_inset"] - D14["lead_length"]  # 3460: launchpad tie (feedline end)
D14["y_limit"] = D14["half"] - D14["keepout"]  # 4000

# the legacy option strings verbatim (with units): the metal: wrapper reads bare trace_width / trace_gap as mm
D14_LAUNCHPAD = dict(
    pad_width="400um",
    pad_height="400um",
    pad_gap="240um",
    taper_height="300um",
    trace_width="20um",
    trace_gap="12um",
    lead_length="500um",
)
D14_XMON = dict(
    cross_width=50,
    cross_length=220,
    cross_gap=20,
    connection_pads=dict(
        a=dict(
            connector_type="0",
            connector_location="90",
            claw_length=150,
            claw_width=35,
            ground_spacing=2,
            claw_gap=6,
            claw_cpw_width=10,
            claw_cpw_length=100,
        )
    ),
)


# §7 printout: centre-line extents of the built Metal resonators, legacy frame, mm (x0, x1, y0, y1)
D14_LEGACY_EXTENTS = {
    "R_T0": (-3.804, -2.696, 1.936, 3.017),
    "R_T1": (-2.901, -0.999, 1.033, 1.864),
    "R_T2": (-1.342, 0.042, 1.936, 3.017),
    "R_T3": (0.260, 1.040, 0.433, 1.864),
    "R_T4": (1.215, 2.685, 1.936, 3.017),
    "R_T5": (2.896, 3.494, 0.433, 1.864),
    "R_B0": (-3.804, -2.696, -1.864, -0.783),
    "R_B1": (-2.901, -0.999, -2.767, -1.936),
    "R_B2": (-1.342, 0.042, -1.864, -0.783),
    "R_B3": (0.260, 1.040, -3.367, -1.936),
    "R_B4": (1.215, 2.685, -1.864, -0.783),
    "R_B5": (2.896, 3.494, -3.367, -1.936),
}


def d14_calibration():
    """§2: closed-form least-squares line through 1/f vs L (the legacy fit). Returns (a, b): 1/f = a·L + b."""
    pts = [(L, 1.0 / f) for n, L, f in D14_SIM_TABLE if n not in D14_EXCLUDE]
    n = len(pts)
    sx = sum(x for x, _ in pts)
    sy = sum(y for _, y in pts)
    sxx = sum(x * x for x, _ in pts)
    sxy = sum(x * y for x, y in pts)
    a = (n * sxy - sx * sy) / (n * sxx - sx * sx)
    return a, (sy - a * sx) / n


def d14_lengths() -> list[float]:
    """§2: resonator lengths (µm) for :data:`D14_FREQS`, rounded to 5 µm like the legacy notebook."""
    a, b = d14_calibration()
    return [round((1.0 / f - b) / a / 5) * 5 for f in D14_FREQS]


def d14_plan() -> list[dict]:
    """§5 + §6: one dict per resonator index i = 0..5 (legacy frame, µm).

    Keys: ``f`` (target GHz), ``L`` (length), ``xc`` (open end / tail x), ``side`` (+1 above / −1 below the
    feedline), ``dirx`` (coupler direction from the short end: −1 on the left half), ``N`` (meander arms), ``dy``
    (short → open height), ``pitch``, ``lp`` (Metal length_perp), ``open_dx`` (tail offset from the short end),
    ``x_short`` and ``in_column`` (sits under an edge-launchpad pocket).
    """
    p = D14
    lengths = d14_lengths()
    xc = [(i - 2.5) * p["pitch_x"] for i in range(6)]
    side = [+1, -1, +1, -1, +1, -1]
    out = []
    for i in range(6):
        s, x = side[i], xc[i]
        in_column = abs(abs(x) - p["lp_offset"]) < p["col_half"]
        caps = []
        for feed_y, has_qubit in ((+p["lp_offset"], False), (-p["lp_offset"], True)):
            y0 = feed_y + s * p["res_gap"]
            outward = (s > 0) == (feed_y > 0)
            if outward:
                limit = (p["lead_corridor"] - p["corridor_margin"]) if in_column else p["y_limit"]
                room = limit - abs(y0)
            else:
                room = abs(y0) - p["centre_gap"]
            caps.append(room - (p["qubit_back"] if has_qubit else 0.0))
        cap = min(caps)
        dy = cap - 10.0
        n_arms = int(math.floor((dy - p["end_straight"]) / p["min_pitch"] - 0.5))
        pitch = (dy - p["end_straight"]) / (n_arms + 0.5)
        lp = (lengths[i] - p["coupler"] - dy) / (2 * n_arms + 2)
        dirx = -1 if x < 0 else +1
        open_dx = p["coupler"] - lp
        out.append(
            dict(
                i=i,
                f=D14_FREQS[i],
                L=float(lengths[i]),
                xc=x,
                side=s,
                dirx=dirx,
                N=n_arms,
                dy=dy,
                pitch=pitch,
                lp=lp,
                open_dx=open_dx,
                x_short=x - dirx * open_dx,
                in_column=in_column,
            )
        )
    return out


def d14_plan_md(plan: list[dict]) -> str:
    """The legacy §5 plan table (to compare with the legacy notebook output)."""
    rows = [
        "| i | f (GHz) | L (µm) | xc (µm) | side | pocket | N | dy (µm) | pitch (µm) | lp (µm) | open_dx (µm) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in plan:
        rows.append(
            f"| {r['i']} | {r['f']:.2f} | {r['L']:.0f} | {r['xc']:.0f} | {'above' if r['side'] > 0 else 'below'} | "
            f"{r['in_column']} | {r['N']} | {r['dy']:.1f} | {r['pitch']:.1f} | {r['lp']:.1f} | {r['open_dx']:.1f} |"
        )
    return "\n".join(rows)


def etch_region(d):
    """Everything etched in the built chip ``d.result`` (face-0 gaps, without the ground grid) as a merged
    ``pya.Region`` in dbu."""
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    ly = d.result.layout
    region = pya.Region()
    for li in ly.layer_indexes():
        if ly.get_info(li).name in ("1t1_base_metal_gap_wo_grid", "1t1_base_metal_gap"):
            region.insert(d.result.top.begin_shapes_rec(li))
    return region.merged()


def flux_hole_runs(d, rows, size: float = 5.0, pitch: float = 25.0, clear: float = 30.0) -> list[tuple]:
    """Legacy ``hole_row`` + ``_accept`` (design 14 §8) on the built chip: holes of ``size`` on a ``pitch`` grid
    centred on each straight row, dropped when the hole comes within ``clear`` of anything already etched.

    ``rows`` are ``(axis, fixed, lo, hi)`` with ``axis`` "x" (row along x at y = fixed) or "y". Returns runs of
    consecutive surviving holes ``(x, y, nx, ny)`` (first hole centre, counts) for ``FluxHoleArray``.
    """
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    dbu = d.result.layout.dbu
    forbidden = etch_region(d).sized(int(round((clear - 1e-3) / dbu)))
    h = int(round(size / 2 / dbu))
    runs = []
    for axis, fixed, lo, hi in rows:
        n = int(math.floor((hi - lo) / pitch))
        start = lo + 0.5 * ((hi - lo) - n * pitch)
        pts = [(start + k * pitch, fixed) if axis == "x" else (fixed, start + k * pitch) for k in range(n + 1)]
        cen = [(int(round(x / dbu)), int(round(y / dbu))) for x, y in pts]
        holes = pya.Region()
        for cx, cy in cen:
            holes.insert(pya.Box(cx - h, cy - h, cx + h, cy + h))
        bad = {(p.bbox().center().x, p.bbox().center().y) for p in holes.interacting(forbidden).each()}
        ok = [c not in bad for c in cen]
        k = 0
        while k < len(pts):
            if not ok[k]:
                k += 1
                continue
            j = k
            while j + 1 < len(pts) and ok[j + 1]:
                j += 1
            m = j - k + 1
            runs.append((*pts[k], m, 1) if axis == "x" else (*pts[k], 1, m))
            k = j + 1
    return runs


def route_extents(d, names, origin=(0.0, 0.0), shrink: float = 0.0) -> dict:
    """Bounding box ``(x0, x1, y0, y1)`` in mm of each built route's gap geometry, relative to ``origin`` (µm), shrunk
    by ``shrink`` µm (a/2 + b gives the centre-line extent)."""
    ly, cell = d.result.layout, d.result.cell
    li = next(i for i in ly.layer_indexes() if ly.get_info(i).name == "1t1_base_metal_gap_wo_grid")
    out = {}
    for inst in cell.each_inst():
        name = inst.property("id")
        if name in names:
            bb = inst.dcplx_trans * inst.cell.dbbox_per_layer(li)
            out[name] = tuple(
                round(v / 1000, 3)
                for v in (
                    bb.left + shrink - origin[0],
                    bb.right - shrink - origin[0],
                    bb.bottom + shrink - origin[1],
                    bb.top - shrink - origin[1],
                )
            )
    return out


def extents_md(built: dict, legacy: dict) -> str:
    """Rebuilt vs legacy extents (mm) with the differences in µm."""
    rows = [
        "| route | legacy x (mm) | rebuilt x (mm) | legacy y (mm) | rebuilt y (mm) | max abs Δ (µm) |",
        "|---|---|---|---|---|---|",
    ]
    for n, lg in legacy.items():
        b = built.get(n)
        if b is None:
            rows.append(f"| {n} | – | missing | – | – | – |")
            continue
        dmax = max(abs(u - v) for u, v in zip(b, lg)) * 1000
        rows.append(
            f"| {n} | [{lg[0]:.3f}, {lg[1]:.3f}] | [{b[0]:.3f}, {b[1]:.3f}] | [{lg[2]:.3f}, {lg[3]:.3f}] | "
            f"[{b[2]:.3f}, {b[3]:.3f}] | {dmax:.0f} |"
        )
    return "\n".join(rows)


# ---- design 12 ---------------------------------------------------------------------------------------------------
D12_FEED_LAUNCHPAD = dict(
    pad_width="400um",
    pad_height="400um",
    pad_gap="240um",
    taper_height="300um",
    trace_width="20um",
    trace_gap="12um",
)
D12_LINE_LAUNCHPAD = dict(  # flux / drive pads: "50 ohm matched pad / line"
    pad_width="400um",
    pad_height="300um",
    pad_gap="195um",
    taper_height="300um",
    trace_width="10um",
    trace_gap="5.75um",
    lead_length="20um",
)
D12_CLAW = dict(
    connector_type="0",
    connector_location="90",
    claw_length="150um",
    claw_width="35um",
    ground_spacing="2um",
    claw_gap="6um",
    claw_cpw_width="10um",
    claw_cpw_length="100um",
)
D12_DRIVE_PAD = dict(connector_type="1", ground_spacing="30um", claw_width="10um", claw_gap="6um")
D12_FL_OPTIONS = dict(
    t_top="60um", t_offset="-20um", t_inductive_gap="2um", t_width="2um", t_gap="6um", t_length="100um"
)
D12_CROSS = dict(cross_width="50um", cross_length="220um", cross_gap="20um")
D12_RES_GAP = 36.0  # 20/2 + 12 + 3 µm strip + 10/2 + 6: short-end centre-line from the feedline centre-line

# qubit: (x, y, flux line?, bus_drive connector_location or None); orientation 180 on top, 0 below
D12_QUBITS = {
    "Q0": (-1700, 2000, False, "180"),
    "Q1": (-250, 2000, True, None),
    "Q2": (250, 2000, True, "0"),  # -250 + 20 + 20 + direct_coupler_gap 20 + 2 * 220
    "Q3": (1700, 2000, False, "0"),
    "Q4": (-1700, -2000, False, "0"),
    "Q5": (-500, -2000, True, None),  # -(2 * 220 + 40 + tunable_coupler_gap 20)
    "Q6": (500, -2000, True, None),
    "Q7": (1700, -2000, False, "180"),
    "Q8": (0, -2000, True, None),  # the tunable coupler between Q5 and Q6, with its own readout
}

# resonator → (length, short x, coupler direction from the short (+1 → +x), coupler length, legacy meander axis x,
# first-row y, last-jog y). Coupler length, axis and row ys are the legacy RouteMeander's own polyline (from
# d12_metal_reference(); the coupler is start_straight 400 µm, 300 µm for R8, plus R0's first arm).
D12_RES = {
    "R0": (5493, -2500, +1, 571.9, -2150.0, 186, 1236),
    "R1": (6262, -200, -1, 400.0, -400.0, 186, 1386),
    "R2": (6140, 200, +1, 400.0, 400.0, 186, 1386),
    "R3": (4638, 1600, +1, 400.0, 1811.05, 186, 1386),
    "R4": (4475, -1600, -1, 400.0, -1816.15, 186, 1386),
    "R5": (5200, -1300, +1, 400.0, -1000.0, 186, 1236),
    "R6": (5132, 1300, -1, 400.0, 950.0, 186, 1236),
    "R7": (5690, 2500, -1, 400.0, 2200.0, 186, 1236),
    "R8": (4300, -200, +1, 300.0, -50.0, 186, 1386),
}

# flux / drive lines: launchpad → (qubit, pin, interior points of the legacy RoutePathfinder)
D12_LINES = {
    "LP_TB_00": ("Q5", "flux_line", [(-1300, -2379), (-520, -2379)]),
    "LP_TB_12": ("Q2", "bus_drive", [(1300, 2400), (676, 2400), (676, 2000)]),  # legacy anchor (1.0, 2.4) mm
    "LP_TB_01": ("Q8", "flux_line", []),
    "LP_TB_02": ("Q6", "flux_line", [(1300, -2379), (480, -2379)]),
    "LP_TB_10": ("Q1", "flux_line", [(-1300, 2379), (-230, 2379)]),
    "LP_TB_11": ("Q2", "flux_line", [(-20, 2379), (270, 2379)]),
    "LP_LR_10": ("Q0", "bus_drive", []),
    "LP_LR_00": ("Q4", "bus_drive", []),
    "LP_LR_01": ("Q7", "bus_drive", []),
    "LP_LR_11": ("Q3", "bus_drive", []),
}


def d12_line_pads() -> dict:
    """The ten flux / drive launchpads: name → (x, y, rot) (legacy frame; the origin is the taper tip)."""
    out = {}
    for i, (y, rot) in enumerate(((-2800, 90), (2800, 270))):
        for j, x in enumerate((-1300, -20, 1300)):
            out[f"LP_TB_{i}{j}"] = (x, y, rot)
    for j, (x, rot) in enumerate(((-2800, 0), (2800, 180))):
        for i, y in enumerate((-2000, 2000)):
            out[f"LP_LR_{i}{j}"] = (x, y, rot)
    return out


def d12_meander_x(name: str, r: float = 60.0, clear: float = 5.0) -> float:
    """x of the vertical segment that carries resonator ``name``'s meander: the legacy meander axis when both
    jogs to it (from the claw x and to the coupler's far end) are ≥ 2r + clear long, else whichever of the claw x /
    the coupler far-end x is closer to the axis and leaves a valid jog, else the axis pushed out to the minimum."""
    q = "Q" + name[1:]
    x_q = D12_QUBITS[q][0]
    _, x_short, dirx, cpl, axis, _, _ = D12_RES[name]
    x_far = x_short + dirx * cpl
    need = 2 * r + clear
    if abs(axis - x_q) >= need and abs(axis - x_far) >= need:
        return axis
    if abs(x_q - x_far) >= need:
        return min((x_q, x_far), key=lambda x: abs(x - axis))
    lo, hi = min(x_q, x_far), max(x_q, x_far)
    return lo - need if axis <= (lo + hi) / 2 else hi + need


def d12_metal_reference() -> dict:
    """Rebuild design 12 headless in Quantum Metal with the legacy options (§ Launchpads … flux lines of the legacy
    notebook, transcribed): ``{"pins": {"<comp>.<pin>": (x, y, angle)}, "routes": {name: {"length", "pts"}}}`` in µm,
    legacy frame. Takes ≈ 5 s."""
    import os  # pylint: disable=import-outside-toplevel
    from collections import OrderedDict  # pylint: disable=import-outside-toplevel

    os.environ.setdefault("QISKIT_METAL_HEADLESS", "1")
    import numpy as np  # pylint: disable=import-outside-toplevel
    from qiskit_metal import Dict, designs  # pylint: disable=import-outside-toplevel
    from qiskit_metal.qlibrary.qubits.transmon_cross_fl import TransmonCrossFL  # pylint: disable=C0415
    from qiskit_metal.qlibrary.terminations.launchpad_wb_driven import LaunchpadWirebondDriven  # pylint: disable=C0415
    from qiskit_metal.qlibrary.terminations.short_to_ground import ShortToGround  # pylint: disable=C0415
    from qiskit_metal.qlibrary.tlines.meandered import RouteMeander  # pylint: disable=import-outside-toplevel
    from qiskit_metal.qlibrary.tlines.pathfinder import RoutePathfinder  # pylint: disable=import-outside-toplevel
    from qiskit_metal.qlibrary.tlines.straight_path import RouteStraight  # pylint: disable=import-outside-toplevel

    design = designs.DesignPlanar()
    design.overwrite_enabled = True
    design.variables["cpw_width"], design.variables["cpw_gap"] = "10 um", "6 um"
    for name, x in (("P1_C", 2700), ("P2_C", -2700)):
        LaunchpadWirebondDriven(
            design,
            name,
            options=dict(pos_x=f"{x}um", pos_y="0um", orientation="180" if x > 0 else "0", lead_length="500um")
            | D12_FEED_LAUNCHPAD,
        )
    for name, (x, y, rot) in d12_line_pads().items():
        LaunchpadWirebondDriven(
            design, name, options=dict(pos_x=f"{x}um", pos_y=f"{y}um", orientation=str(rot)) | D12_LINE_LAUNCHPAD
        )
    RouteStraight(
        design,
        "cpw_main",
        Dict(
            pin_inputs=Dict(start_pin=Dict(component="P1_C", pin="tie"), end_pin=Dict(component="P2_C", pin="tie")),
            trace_width="20um",
            trace_gap="12um",
        ),
    )
    for name, (_length, x_short, dirx, *_) in D12_RES.items():
        y = D12_RES_GAP if int(name[1:]) < 4 else -D12_RES_GAP
        ShortToGround(
            design,
            f"short_{name[1:]}",
            options=dict(pos_x=f"{x_short}um", pos_y=f"{y}um", orientation="180" if dirx > 0 else "0"),
        )
    for name, (x, y, flux, drive) in D12_QUBITS.items():
        pads = {"a": dict(D12_CLAW)}
        if drive:
            pads["bus_drive"] = dict(D12_DRIVE_PAD, connector_location=drive)
        TransmonCrossFL(
            design,
            name,
            options=dict(
                pos_x=f"{x}um",
                pos_y=f"{y}um",
                orientation="180" if y > 0 else "0",
                make_fl=flux,
                fl_options=dict(D12_FL_OPTIONS),
                connection_pads=pads,
                **D12_CROSS,
            ),
        )
    asym = {"R0": "50um", "R1": "-200um", "R2": "200um", "R3": "200um", "R4": "200um", "R5": "-100um", "R6": "50um"}
    asym |= {"R7": "100um", "R8": "-150um"}
    for name, (length, *_) in D12_RES.items():
        RouteMeander(
            design,
            name,
            options=Dict(
                pin_inputs=Dict(
                    start_pin=Dict(component=f"short_{name[1:]}", pin="short"),
                    end_pin=Dict(component="Q" + name[1:], pin="a"),
                ),
                total_length=f"{length}um",
                hfss_wire_bonds=True,
                fillet="60um",
                lead=Dict(start_straight="0.3mm" if name == "R8" else "0.4mm", end_straight="0.1mm"),
                meander=Dict(segment_length="0.6mm", spacing="0.15mm", asymmetry=asym[name]),
            ),
        )
    anchors = {"LP_TB_12": (1.0, 2.4)}
    for pad, (q, pin, _) in D12_LINES.items():
        a = OrderedDict()
        if pad in anchors:
            a[0] = np.array(anchors[pad])
        RoutePathfinder(
            design,
            f"line_{pad}",
            options=dict(
                pin_inputs=Dict(start_pin=Dict(component=pad, pin="tie"), end_pin=Dict(component=q, pin=pin)),
                lead={"start_straight": "10um", "end_straight": "100um"},
                step_size="0.25mm",
                fillet="60um",
                hfss_wire_bonds=True,
                prevent_short_edges=True,
                anchors=a,
            ),
        )
    out: dict = {"pins": {}, "routes": {}}
    for name, comp in design.components.items():
        for pin_name, pin in comp.pins.items():
            ang = float(np.degrees(np.arctan2(pin.normal[1], pin.normal[0])))
            out["pins"][f"{name}.{pin_name}"] = (*(round(1000 * v, 2) for v in pin.middle), round(ang, 1))
        if name.startswith(("R", "line_", "cpw")):
            pts = comp.get_points() * 1000
            out["routes"][name] = {"length": round(comp.length * 1000, 1), "pts": [tuple(map(float, p)) for p in pts]}
    return out


# ---- chip_07_resonators ------------------------------------------------------------------------------------------
C07_FEED = dict(length=7500 - 2000 - 40 - 210, lc_thickness=2, rc_thickness=2)  # "Coplanar Waveguide" (c_gap 0)
C07_PAD = dict(trace_width=10, pad_gap=225, pad_height=450, pad_width=400, conn_height=450, round=False, sim=False)
C07_PAD_X = 3750 - 1000 - 125  # "Connector Pad 2" at (∓2625, 0), rot 3 / 1: the feedline ends
C07_RES_COMMON = dict(
    cpw_len=4660, gap=6, clength=300, cgap=4, width=300, flip=False, neck_length=400, ground=True
)  # "Coupled Resonator" resParams_common
# resonator: (x, y, mirror, overrides, target GHz (legacy comment and etched label), legacy second metal?)
C07_RES = {
    "R2": (-2000, -26, False, dict(cpw_len=6200, flip=False, clength=200, cgap=4, neck_length=500), 5.0, False),
    "R3": (-1350, 26, True, dict(cpw_len=5840, flip=True, neck_length=500), 5.25, False),
    "R6": (1350, -26, False, dict(cpw_len=5590, flip=True, neck_length=500, clength=400, cgap=4), 5.5, False),
    "R8": (450 - 800, -26 - 2, False, dict(cpw_len=5200, neck_length=500, clength=300, cgap=6), 6.0, True),
    "R9": (1350 - 900, 26, True, dict(cpw_len=4920, clength=300, cgap=4), 6.25, True),
    "R12": (2100, 26 + 2, True, dict(cpw_len=4740, flip=True, clength=600, cgap=6), 6.5, True),
}
# flux holes: (first hole centre x, y, row length); 2 rows, pitch 20 µm (x) × 15 µm (y), 5 µm squares, n = int(l / 20)
C07_HOLES = [(-2560, 33, 890), (-1850, -45, 1150), (-950, 33, 1090), (50, -45, 950), (750, 33, 900), (1720, -45, 900)]
# text: (name, text, mag, inverted, x, y, rot) — the chip label and the six f × 10 labels (alternating sides, rot 0/2)
C07_TEXT = [("LBL_CHIP", "WSK_TLW07", 300, False, 800, -3000, 0)] + [
    (f"LBL_{v}", str(v), 200, True, x, 276 * (1 if k % 2 == 0 else -1), 0 if k % 2 == 0 else 2)
    for k, (x, v) in enumerate(zip([-2050, -1250, -400, 500, 1300, 2250], [50, 52, 60, 62, 55, 65]))
]


def legacy_chip(name: str):
    """legacy-a's ``_legacy.LegacyChip`` plus the cells legacy-b's chips need: any PCell of the harness's base QWri
    library (``Connector Pad 2``, ``Xmon Cross``, …), flux-hole arrays and ``TextGenerator`` labels, all drawn the
    way the legacy scripts draw them (legacy frame, shifted into the Designer frame)."""
    import contextlib  # pylint: disable=import-outside-toplevel
    import io  # pylint: disable=import-outside-toplevel

    import _legacy as L  # pylint: disable=import-outside-toplevel

    class LegacyChipB(L.LegacyChip):
        def pcell(self, name, display, params, x=0.0, y=0.0, rot=0, mirror=False):
            if display in L.LEGACY_PCELLS:
                return super().pcell(name, display, params, x, y, rot, mirror)
            legacy, _ = L._harness()  # pylint: disable=protected-access
            with contextlib.redirect_stdout(io.StringIO()):
                regions = {li: legacy.legacy_region(display, li, **params) for li in L.LAYERS[:1]}
            self._insert(name, regions, self._trans(x, y, rot, mirror))
            return None

        def holes(self, name, x, y, nx, ny, dx, dy, size=5.0):
            """``CellInstArray(hole, Trans(x, y), Vector(0, dy), Vector(dx, 0), ny, nx)`` of ``size`` squares."""
            pya, dbu = self.pya, self.layout.dbu
            region = pya.Region()
            for i in range(nx):
                for j in range(ny):
                    cx, cy = (x + i * dx) / dbu, (y + j * dy) / dbu
                    h = size / 2 / dbu
                    region.insert(pya.Box(int(cx - h), int(cy - h), int(cx + h), int(cy + h)))
            self._insert(name, {(1, 0): region}, self._trans(0, 0, 0, False))

        def path(self, name, points, width, gap, radius, npoints=300):
            """A legacy raw CPW path: ``Path(points, width + 2 gap) − Path(points, width)``, both
            ``round_corners(radius, npoints)`` (chip_09's feedline), on 1/0."""
            pya, dbu = self.pya, self.layout.dbu
            pts = [pya.Point(pya.DPoint(x / dbu, y / dbu)) for x, y in points]
            inner = pya.Path(pts, width / dbu).round_corners(radius / dbu, npoints)
            outer = pya.Path(pts, (width + 2 * gap) / dbu).round_corners(radius / dbu, npoints)
            self._insert(name, {(1, 0): pya.Region(outer) - pya.Region(inner)}, self._trans(0, 0, 0, False))

        def box(self, name, x, y, w, h):
            """An etched ``w × h`` box centred at (x, y) on 1/0 (resonator_chip_01's "grounder")."""
            pya, dbu = self.pya, self.layout.dbu
            region = pya.Region(pya.Box(int(-w / 2 / dbu), int(-h / 2 / dbu), int(w / 2 / dbu), int(h / 2 / dbu)))
            region = region.transformed(pya.Trans(int(x / dbu), int(y / dbu)))
            self._insert(name, {(1, 0): region}, self._trans(0, 0, 0, False))

        def cell_from(self, name, layout, cell_name, x=0.0, y=0.0, rot=0, mirror=False):
            """legacy-a's ``cell_from`` plus the legacy HSQ layer (500/0), for :func:`junction_xor`."""
            super().cell_from(name, layout, cell_name, x, y, rot, mirror)
            pya = self.pya
            idx = layout.find_layer(pya.LayerInfo(500, 0))
            if idx is not None:
                scale = layout.dbu / self.layout.dbu
                region = pya.Region(layout.cell(cell_name).begin_shapes_rec(idx)).merged()
                region = region.transformed(pya.ICplxTrans(scale)).transformed(
                    self._trans(x, y, rot, mirror).to_itrans(self.layout.dbu)
                )
                self.top.shapes(self.layout.layer(500, 0)).insert(region)

        def text(self, name, text, mag, inverted, x, y, rot=0):
            """``TextGenerator.default_generator().text(text, dbu, mag, inv)`` at ``Trans(rot, False, x, y)``."""
            pya, dbu = self.pya, self.layout.dbu
            region = pya.TextGenerator.default_generator().text(text, dbu, mag, inverted)
            region = region.transformed(pya.Trans(rot, False, int(x / dbu), int(y / dbu)))
            self._insert(name, {(1, 0): region}, self._trans(0, 0, 0, False))

    return LegacyChipB(name)


def chip07_reference(second_metal: bool = True):
    """chip_07_resonators drawn by the legacy PCells (layer 1/0, fab). ``second_metal=True`` keeps the legacy layer
    swap of R8 / R9 / R12 (``l`` = 3/0, ``fab_l`` = 1/0: their CPW etch on 3/0, their gap + cgap envelope on 1/0);
    ``False`` draws them like the others, to compare the CPW geometry itself."""
    import klayout.db as pya  # pylint: disable=import-outside-toplevel

    ref = legacy_chip("chip_07_resonators")
    ref.pcell("FL", "Coplanar Waveguide", {"fab": True, "c_gap": 0, **C07_FEED})
    ref.pcell("PL", "Connector Pad 2", {"fab": True, **C07_PAD}, -C07_PAD_X, 0, 3)
    ref.pcell("PR", "Connector Pad 2", {"fab": True, **C07_PAD}, C07_PAD_X, 0, 1)
    for n, (x, y, mirror, over, _f, m2) in C07_RES.items():
        params = {"fab": True, **C07_RES_COMMON, **over}
        if m2 and second_metal:
            params |= {"l": pya.LayerInfo(3, 0), "fab_l": pya.LayerInfo(1, 0)}
        ref.pcell(n, "Coupled Resonator", params, x, y, 0, mirror)
    for k, (x, y, length) in enumerate(C07_HOLES):
        ref.holes(f"FH{k}", x, y, int(length / 20), 2, 20, 15)
    for name, text, mag, inv, x, y, rot in C07_TEXT:
        ref.text(name, text, mag, inv, x, y, rot)
    return ref


# ---- chip_09_resonatorsExpt ----------------------------------------------------------------------------------------
C09_FEED_PTS = [(-2625, 0), (-2250, 0), (-2250, 2700), (0, 2700), (0, -2700), (2250, -2700), (2250, 0), (2625, 0)]
C09_FEED_R = 150.0  # Path.round_corners(150 µm, 300 points); 10/6 µm CPW
C09_RES_COMMON = dict(
    cpw_len=4660, gap=6, clength=299.5, cgap=4, width=300, flip=False, neck_length=150, ground=True
)  # resParams_common
C09_YGAP = (2700 + 2700) / 4  # 1350
# resonator: (x, y, rot (×90°), mirror, overrides, target GHz (comment and label), legacy second metal?)
C09_RES = {
    "R2": (-1100, 2672, 0, False, dict(cpw_len=4410, flip=False, cgap=6), 7.0, False),
    "R3": (26, 3200 - C09_YGAP, 1, False, dict(cpw_len=5200, flip=True), 6.0, False),
    "R6": (28, 3200 - 2 * C09_YGAP, 1, False, dict(cpw_len=4920, flip=True), 6.25, True),
    "R8": (-24, -3200 + 2 * C09_YGAP, 1, True, dict(cpw_len=6200), 5.0, False),
    "R9": (-26, -3200 + C09_YGAP, 1, True, dict(cpw_len=5840), 5.25, True),
    "R12": (1100, -2670, 2, False, dict(cpw_len=4250, flip=True), 7.2, True),
}
# flux holes: CellInstArray at (x − 150, y), int(lx / 15) = 3 columns at 15 µm, int(ly / 20) rows at 20 µm, 5 µm
C09_HOLES = [
    (x - 150, y, 3, int(ly / 20))
    for x, y, ly in zip(
        [-2165, -2000 - 65.5, -450 + 530, 75, 190, 450 - 255, 2320, 2450],
        [300, 300, 300, -1600, 800, -2200, -2400, -2400],
        [1500 + 660, 2160, 2160, 800, 800, 2160, 2160, 2160],
    )
]
C09_TEXT = [("LBL_CHIP", "WSK_TLW09", 300, False, -3000, -3350, 0)] + [
    (f"LBL_{v}", str(v), 200, True, x + dx, y + dy, 0)
    for v, x, y, dx, dy in zip(
        [70, 60, 62, 50, 52, 72],
        [-1100, 0, 0, 0, 0, 1100],
        [2670, 3200 - C09_YGAP, 3200 - 2 * C09_YGAP, -3200 + 2 * C09_YGAP, -3200 + C09_YGAP, -2670],
        [0, -350, -350, 200, 200, 0],
        [200, 0, 0, 0, 0, -350],
    )
]


def chip09_reference(second_metal: bool = True):
    """chip_09_resonatorsExpt drawn by the legacy PCells and its raw feedline path (1/0, fab); ``second_metal`` as in
    :func:`chip07_reference` (R6 / R9 / R12 carry the layer swap here)."""
    import klayout.db as pya  # pylint: disable=import-outside-toplevel

    ref = legacy_chip("chip_09_resonators_expt")
    ref.path("FL", C09_FEED_PTS, 10, 6, C09_FEED_R)
    ref.pcell("PL", "Connector Pad 2", {"fab": True, **C07_PAD}, -C07_PAD_X, 0, 3)
    ref.pcell("PR", "Connector Pad 2", {"fab": True, **C07_PAD}, C07_PAD_X, 0, 1)
    for n, (x, y, rot, mirror, over, _f, m2) in C09_RES.items():
        params = {"fab": True, **C09_RES_COMMON, **over}
        if m2 and second_metal:
            params |= {"l": pya.LayerInfo(3, 0), "fab_l": pya.LayerInfo(1, 0)}
        ref.pcell(n, "Coupled Resonator", params, x, y, rot, mirror)
    for k, (x, y, nx, ny) in enumerate(C09_HOLES):
        ref.holes(f"FH{k}", x, y, nx, ny, 15, 20)
    for name, text, mag, inv, x, y, rot in C09_TEXT:
        ref.text(name, text, mag, inv, x, y, rot)
    return ref


# ---- chip_09_resonatorsExpt_sim (the earlier frequency plan; legacy-fix, design decision #14) --------------------------
# Same feedline, pads and common resonator parameters as chip_09; differences (chip_09_resonatorsExpt_sim.py):
# R2 y 2674 and no cgap override (4 µm), R6 x 26 / 6200 µm (5.0 GHz), R8 x −26 / 5590 µm (5.5), R9 5340 µm (5.75),
# R12 y −2674; no second-metal layer swap; flux holes at other x with lx = 30 (2 columns); no labels, no markers.
C09S_RES = {
    "R2": (-1100, 2674, 0, False, dict(cpw_len=4410, flip=False), 7.0),
    "R3": (26, 3200 - C09_YGAP, 1, False, dict(cpw_len=5200, flip=True), 6.0),
    "R6": (26, 3200 - 2 * C09_YGAP, 1, False, dict(cpw_len=6200, flip=True), 5.0),
    "R8": (-26, -3200 + 2 * C09_YGAP, 1, True, dict(cpw_len=5590), 5.5),
    "R9": (-26, -3200 + C09_YGAP, 1, True, dict(cpw_len=5340), 5.75),
    "R12": (1100, -2674, 2, False, dict(cpw_len=4250, flip=True), 7.2),
}
C09S_HOLES = [
    (x - 150, y, int(30 / 15), int(ly / 20))
    for x, y, ly in zip(
        [-2150 + 11.5, -2000 - 76.5, -450 + 560, 110, 173.5, 450 - 276.5, 2361.5, 2423.5],
        [300, 300, 300, -1600, 800, -2200, -2400, -2400],
        [1500 + 660, 2160, 2160, 800, 800, 2160, 2160, 2160],
    )
]


def chip09_sim_reference():
    """chip_09_resonatorsExpt_sim drawn by the legacy PCells and its raw feedline path, as the fab negative (1/0) —
    i.e. before the script's final inversion into a positive simulation mask in an 8.5 mm box."""
    ref = legacy_chip("chip_09_resonators_expt_sim")
    ref.path("FL", C09_FEED_PTS, 10, 6, C09_FEED_R)
    ref.pcell("PL", "Connector Pad 2", {"fab": True, **C07_PAD}, -C07_PAD_X, 0, 3)
    ref.pcell("PR", "Connector Pad 2", {"fab": True, **C07_PAD}, C07_PAD_X, 0, 1)
    for n, (x, y, rot, mirror, over, _f) in C09S_RES.items():
        ref.pcell(n, "Coupled Resonator", {"fab": True, **C09_RES_COMMON, **over}, x, y, rot, mirror)
    for k, (x, y, nx, ny) in enumerate(C09S_HOLES):
        ref.holes(f"FH{k}", x, y, nx, ny, 15, 20)
    return ref


# ---- resonator_chip_01 -------------------------------------------------------------------------------------------
RC1_FEED = dict(length=5950, lc_thickness=2, rc_thickness=2)  # "Coplanar Waveguide"
RC1_PAD = dict(trace_width=10, pad_height=300, pad_width=275, conn_height=300)  # "Connector Pad" (round default)
RC1_RES_COMMON = dict(cpw_len=5000, clength=300, cgap=2, width=300, flip=False, neck_length=500)
# resonator (label number): (x, y, mirror, neck_length, legacy variable)
RC1_RES = {
    "R1": (-2000, 26, True, 600, "res1"),
    "R2": (-1000, -26, False, 550, "res2"),
    "R3": (0, 26, True, 500, "res_fixed"),
    "R4": (1000, -26, False, 400, "res3"),
    "R5": (2000, 26, True, 300, "res4"),
}
# "grounder": a 22 × 10 µm etched box (the full CPW width) centred at (x, y), one per resonator tail
RC1_GROUNDERS = {"G1": (-2000, 2000 - 150), "G2": (-1000, -2000 + 70), "G3": (0, 2000), "G4": (1000, -2000 + 260)}
RC1_GROUNDERS |= {"G5": (2000, 2000 - 105)}
RC1_TEXT = [("LBL_RES", "RES", 200, False, -200, 3300, 0)] + [
    (f"LBL_{k}", str(k), 300, True, x, y, 0)
    for k, (x, y) in enumerate([(-2020, -600), (-1020, 600), (-20, -600), (980, 600), (1980, -600)], 1)
]


def resonator_chip01_reference(pad_sim: bool = False, pad_shift: float = 0.0, grounders: bool = True):
    """resonator_chip_01 drawn by the legacy PCells (1/0, fab). The legacy script leaves the pads' ``sim`` at its
    default True (pad metal + ground ring on 1/0 instead of the gap); ``pad_sim=False`` draws the fab pads.
    ``pad_shift`` moves both pads inwards (and shortens the feedline) as the rebuild does; ``grounders=False``
    leaves out the 22 × 10 µm grounder boxes (not intended, design decision #13)."""
    ref = legacy_chip("resonator_chip_01")
    length = RC1_FEED["length"] - 2 * pad_shift
    ref.pcell("FL", "Coplanar Waveguide", {"fab": True, **RC1_FEED, "length": length})
    for name, x, rot in (("PL", -length / 2, 3), ("PR", length / 2, 1)):
        ref.pcell(name, "Connector Pad", {"fab": True, "sim": pad_sim, **RC1_PAD}, x, 0, rot)
    for n, (x, y, mirror, neck, _v) in RC1_RES.items():
        ref.pcell(n, "Coupled Resonator", {"fab": True, **RC1_RES_COMMON, "neck_length": neck}, x, y, 0, mirror)
    for n, (x, y) in RC1_GROUNDERS.items() if grounders else ():
        ref.box(n, x, y, 22, 10)
    for name, text, mag, inv, x, y, rot in RC1_TEXT:
        ref.text(name, text, mag, inv, x, y, rot)
    return ref


# ---- junction layers ---------------------------------------------------------------------------------------------
# legacy layer → (rebuilt KQC/PDK layer name, label): the golden tests' mapping (tests/test_golden_legacy_junctions.py)
JUNCTION_LAYERS = (
    ((2, 0), "1t1_SIS_junction", "straight finger 2/0"),
    ((4, 0), "1t1_SIS_junction_2", "bent finger 4/0"),
    ((500, 0), "qcc_spacer", "HSQ spacer (legacy 500/0 → 50/0)"),
)


def junction_xor(d, ref, names=None, tol_um: float = 0.002) -> tuple[str, dict]:
    """Per legacy instance and junction layer: legacy area, rebuilt area and XOR area (µm², slivers up to ``tol_um``
    ignored), inside the instance's bbox grown by 2 µm. ``ref`` is a :func:`legacy_chip` (its ``cell_from`` keeps
    2/0, 4/0 and 500/0). Returns ``(markdown, {(name, layer label): xor µm²})``."""
    import klayout.db as pya  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.pdk import QCC_LAYERS  # pylint: disable=import-outside-toplevel

    if d.result is None:
        d.show()
    ly, cell = d.result.layout, d.result.cell
    scale = pya.ICplxTrans(ly.dbu / 0.001)
    s = max(1, round(tol_um / 0.001))
    rows = ["| instance | layer | legacy (µm²) | rebuilt (µm²) | XOR (µm²) |", "|---|---|---|---|---|"]
    out = {}
    for legacy_layer, ours, label in JUNCTION_LAYERS:
        info = QCC_LAYERS["hsq"] if ours == "qcc_spacer" else None
        if info is None:
            from kqcircuits.defaults import default_layers  # pylint: disable=import-outside-toplevel

            info = default_layers[ours]
        new = pya.Region(cell.begin_shapes_rec(ly.layer(info))).merged().transformed(scale)
        old = ref.region(legacy_layer)
        for name in names or ref.boxes:
            box = pya.Region(ref.boxes[name].enlarged(2, 2).to_itype(0.001))
            a, b = old & box, new & box
            if a.is_empty() and b.is_empty():
                continue
            x = (a ^ b).sized(-s).sized(s)
            out[(name, label)] = x.area() * 1e-6
            ua, ub = a.area() * 1e-6, b.area() * 1e-6
            rows.append(f"| {name} | {label} | {ua:.3f} | {ub:.3f} | {out[(name, label)]:.4f} |")
    return "\n".join(rows), out


def legacy_path_cell(script: str, func: str, cell: str, *args, tmp):
    """Run a legacy script function that takes ``path=`` (``chip_10a_3X_SQUID.create_squid``) read-only through
    ``tests/legacy_ref/legacy.py::legacy_script_layout``, with ``path`` pointing into ``tmp`` so nothing is written
    anywhere else (the scripts' default paths are Windows paths, which would land in the working directory), and
    return ``(layout, cell name)``."""
    import contextlib  # pylint: disable=import-outside-toplevel
    import io  # pylint: disable=import-outside-toplevel
    from pathlib import Path  # pylint: disable=import-outside-toplevel

    import _legacy as L  # pylint: disable=import-outside-toplevel

    legacy, _ = L._harness()  # pylint: disable=protected-access
    tmp = Path(tmp).resolve()
    tmp.mkdir(parents=True, exist_ok=True)
    for old in tmp.glob("*.gds"):
        old.unlink()
    prefix = str(tmp / f"{Path(script).stem}_")
    with contextlib.redirect_stdout(io.StringIO()):
        out = legacy.legacy_script_layout(f"python/{script}", lambda ns: ns[func](*args, path=prefix), tmp)
    (layout,) = out.values()
    return layout, cell
