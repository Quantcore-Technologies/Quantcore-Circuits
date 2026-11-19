"""A custom component: a two-terminal capacitor made of two interleaved spirals (a "spiral / twisted capacitor").

Two metal arms wind outward together (a double spiral). Every turn of one arm has the other arm on both sides, so the
facing edges add up to a long, thin gap: a lot of capacitance in a small cut-out. The arms start close to the centre,
never touch, and leave the spiral on opposite sides, where two short leads reach the pins. The component sits in a
ground cut-out, so it can be placed in a CPW line:

    feedline ──── pin a ─[ spiral ]─ pin b ──── resonator

Copy this file into ``src/quantcore_circuits/layouts/others/`` (any folder of ``layouts/`` works) and it joins the
Quantcore library; or keep it where it is and use the dotted reference ``custom_component.spiral_capacitor.
TwistedSpiralCapacitor`` with ``examples/`` on ``sys.path``. Guide: docs/library/custom-components/spiral-capacitor.md.
"""

from __future__ import annotations

import math

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt

from quantcore_circuits.lom import estimates as est
from quantcore_circuits.lom.fragment import Element as LomElement
from quantcore_circuits.lom.fragment import Fragment, cell_params, register_lom

_STEP_DEG = 4.0  # polyline step of the spiral arms


def arm_points(r_in: float, pitch: float, turns: float, phase_deg: float = 0.0) -> list[tuple[float, float]]:
    """Centre line of one arm: an Archimedean spiral r = r_in + pitch · t / 2π, t = 0 … 2π · turns, rotated by
    ``phase_deg``. ``pitch`` is the radial distance between two turns of the same arm."""
    n = max(int(round(360.0 * turns / _STEP_DEG)), 2)
    phase = math.radians(phase_deg)
    pts = []
    for i in range(n + 1):
        t = 2 * math.pi * turns * i / n
        r = r_in + pitch * t / (2 * math.pi)
        pts.append((r * math.cos(t + phase), r * math.sin(t + phase)))
    return pts


def arm_length(pts: list[tuple[float, float]]) -> float:
    """Length of a polyline (µm)."""
    return sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))


class TwistedSpiralCapacitor(Element):
    """Interleaved double spiral in a ground cut-out; pins ``a`` (−x) and ``b`` (+x), both pointing outwards."""

    # the class the panel, the DRC, the fab export and the LOM read (quantcore_circuits.layouts.catalog.CATEGORIES)
    qcc_category = "capacitor"

    turns = Param(pdt.TypeDouble, "Turns of each arm (in steps of 0.5)", 2.0)
    arm_width = Param(pdt.TypeDouble, "Width of each arm", 6.0, unit="μm")
    arm_gap = Param(pdt.TypeDouble, "Gap between neighbouring arms", 4.0, unit="μm")
    inner_radius = Param(pdt.TypeDouble, "Radius where the arms start", 14.0, unit="μm")
    clearance = Param(pdt.TypeDouble, "Clearance from the outer arm to ground", 20.0, unit="μm")
    lead_length = Param(pdt.TypeDouble, "Length of the leads from the spiral to the pins", 30.0, unit="μm")

    # ---- geometry helpers (also used by the LOM model, so the numbers cannot drift apart) -----------------------
    @classmethod
    def geometry(cls, params: dict) -> dict:
        """Everything the build and the LOM need: the two arms, their length, the outer radius and the lead."""
        w, g = float(params["arm_width"]), float(params["arm_gap"])
        pitch = 2 * (w + g)  # each turn of one arm leaves room for a turn of the other arm between
        turns, r_in = round(2 * float(params["turns"])) / 2, float(params["inner_radius"])  # half turns: ends on x
        a_pts = arm_points(r_in, pitch, turns, 0.0)  # ends on the x axis
        b_pts = arm_points(r_in, pitch, turns, 180.0)  # ends on the x axis, opposite
        r_out = r_in + pitch * turns + w / 2
        return {
            "pitch": pitch,
            "arm_a": a_pts,
            "arm_b": b_pts,
            "arm_length": arm_length(a_pts),
            "r_out": r_out,
            "window_r": r_out + float(params["clearance"]),
        }

    def build(self):
        dbu = self.layout.dbu
        geo = self.geometry({name: getattr(self, name) for name in self.get_schema() if not name.startswith("_")})
        w = self.arm_width
        ca, cb = self.a, self.b  # CPW centre width and gap of the pins (Element parameters)
        win_r = geo["window_r"]
        x_pin = win_r + self.lead_length

        def dpoly(points, width):
            return pya.DPath([pya.DPoint(x, y) for x, y in points], width, w / 2, w / 2, True).polygon()

        # metal that stays: the two arms and the two leads (centre conductor of the pins, width ``a``)
        metal = pya.Region()
        for pts in (geo["arm_a"], geo["arm_b"]):
            metal.insert(dpoly(pts, w).to_itype(dbu))
        for end in (geo["arm_a"][-1], geo["arm_b"][-1]):  # each arm ends on the x axis: a lead runs out to its pin
            x_end = round(end[0] / dbu)
            x_far = round(math.copysign(x_pin, end[0]) / dbu)
            metal.insert(pya.Box(min(x_end, x_far), round(-ca / 2 / dbu), max(x_end, x_far), round(ca / 2 / dbu)))
        metal.merge()

        # the window that is etched: a disc around the spiral and a CPW channel (centre + two gaps) to each pin
        window = pya.Region(pya.DPolygon(
            [pya.DPoint(win_r * math.cos(2 * math.pi * i / 128), win_r * math.sin(2 * math.pi * i / 128))
             for i in range(128)]).to_itype(dbu))
        for sign in (-1, 1):
            x0, x1 = (0, x_pin) if sign > 0 else (-x_pin, 0)
            window.insert(pya.DBox(x0, -(ca / 2 + cb), x1, ca / 2 + cb).to_itype(dbu))
        window.merge()

        # negative mask: draw what is etched, on the layer every Quantcore / KQC cell uses
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(window - metal)
        self.add_protection(pya.Region(window.bbox()).sized(round(self.margin / dbu)))  # no cheese holes here
        self.add_port("a", pya.DPoint(-x_pin, 0), pya.DVector(-1, 0))
        self.add_port("b", pya.DPoint(x_pin, 0), pya.DVector(1, 0))


# ---- the LOM model --------------------------------------------------------------------------------------------------
# LOM models are found by class name, so the class must not be called SpiralCapacitor: that is KQCircuits'
# own spiral capacitor, which has its own model in the library.
@register_lom("TwistedSpiralCapacitor")  # by class name: subclasses inherit the model
def spiral_capacitor_lom(name: str, inst, pdk) -> Fragment:
    """Series C between pin ``a`` and pin ``b``.

    Estimate: the arms form a long coplanar-strip gap. Walking along the spiral, every turn of one arm faces the other
    arm on both sides, so the gap tracks add up to the length of both arms. The coplanar-strip capacitance per length
    (``estimates.cps_c_per_um``, two strips of width ``arm_width`` spaced ``arm_gap``, on the PDK substrate) times that
    length is the capacitance. It ignores the spiral's curvature and the coupling to ground, so treat it as +-30 %
    until a FEM C-matrix fills the value (net names ``<name>.a`` / ``<name>.b``).
    """
    p = cell_params(inst)
    eps = est.substrate_eps(pdk)
    geo = TwistedSpiralCapacitor.geometry(p)
    w, g = float(p["arm_width"]), float(p["arm_gap"])
    gap_length = 2 * geo["arm_length"]  # both arms: one gap track per turn of either arm
    c_ff = gap_length * est.cps_c_per_um(w, w, g, eps)
    return Fragment(
        nodes={"a": {"island": f"{name}.a"}, "b": {"island": f"{name}.b"}},  # one conductor per arm
        port_nodes={"a": "a", "b": "b"},  # which conductor each pin touches
        elements=[
            LomElement(
                f"C_{name}",
                "C",
                ("a", "b"),
                est.cap(c_ff, "rough", f"coplanar-strip gap over {gap_length:.0f} um of spiral gap"),
                {"param": f"{name}.turns"},
            )
        ],
        knobs={f"{name}.turns": (max(1.0, float(p["turns"]) * 0.5), float(p["turns"]) * 1.6)},
    )
