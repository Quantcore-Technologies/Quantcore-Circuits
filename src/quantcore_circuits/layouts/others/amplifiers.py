"""Parametric-amplifier cells (agent ``amplifiers``, design decision #45): Quantcore re-drawings of the open JPA / TWPA
layouts listed in ``components/Open Superconducting Device Layouts.md`` ("Parametric amplifiers"), on the PDK stack
(negative mask: the etch is drawn on ``base_metal_gap_wo_grid``, PDK 1/0) with Nb trilayer junctions.

* :class:`SquidTermination` — QPDK ``qpdk/cells/parametric_amplifier.py::squid_termination`` (+ the pump line of
  ``cpw_jpa``): a CPW lead that ends in an etched pocket bridged by a trilayer SQUID to ground, and a shorted CPW
  pump / flux line running past the ground side of the SQUID (Yamamoto et al. 2008; Pogorzalek et al. 2017).
* :class:`LumpedJpa` — the lumped JPAs of twpa-sim (``src/twpa/layout/generate.py``, families ``jpa`` and
  ``squid_jpa``, MIT): one junction or SQUID shunted by a capacitor, here a planar interdigital capacitor (IDC)
  between an island and the ground (the PDK has no MIM layer). ``coupling="capacitive"``: the island's CPW lead is
  the port (put a coupling capacitor cell in front); ``coupling="inductive"``: a tapped-inductor coupling (the
  junction's ground side lands on a narrow strip shared with the signal line; twpa-sim draws a pickup loop).
* :class:`JtwpaChain` — the 4WM JTWPA of twpa-sim (``jtwpa4wm``) and the resonantly phase-matched JTWPA of the QPDK
  JosephsonCircuits notebook (O'Brien et al. 2014): a series chain of trilayer junctions between CPW centre-line
  islands, each island shunted to ground by interdigital fingers, a lumped LC resonator on every
  ``resonator_every``-th node (coupling IDC, pad, meander inductor to ground).
* :class:`KiTwpaSerpentine` — the KI-TWPA serpentine of twpa-sim ``src/twpa/layout/kit.py`` (a port of the NY CREATES
  research geometry, NbN): a 0.58 µm spine with 75.5 µm capacitive fingers (27.5 µm on the loaded cells), straight
  rows joined by U-turns whose spine width is matched in sheet squares, tapered launches to the chip CPW.

Sources were read, never imported or run (``build/external/twpa-sim``, ``build/external/quantum-rf-pdk``).

LOM (``qcc_lom`` on each class): the SQUID termination enters the λ/4 line as its inductive equivalent length (as
:class:`~quantcore_circuits.layouts.others.qpdk_cells.NeckTermination`); the lumped JPA is an island with its IDC
capacitance, the junction / SQUID and the coupling; the JTWPA chain is one node per island (junctions in series,
shunt C, resonators); the KI serpentine is one conductor (a wire between its ports) with its electrical ladder from
:meth:`KiTwpaSerpentine.qcc_ladder` (PDK film kinetic inductance via :mod:`quantcore_circuits.circuit.kinetic`).
"""

from __future__ import annotations

import json
import math

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt

PHI0 = 2.067833848e-15  # Wb
_JUNCTIONS = ["Quantcore Junction", "Quantcore Squid", "Trilayer Junction", "Trilayer Squid", "Sim", "No Squid"]


# ---- shared helpers ------------------------------------------------------------------------------------------------
def _box(dbu, x0, y0, x1, y1) -> pya.Box:
    return pya.DBox(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)).to_itype(dbu)


def _region(dbu, *boxes) -> pya.Region:
    out = pya.Region()
    for b in boxes:
        out.insert(_box(dbu, *b))
    return out


def _json_params(params: dict) -> dict:
    """design.json params → PCell params: a ``junction_params`` dict becomes its JSON string (validated)."""
    from quantcore_circuits.layouts.junctions.trilayer import _json_dict  # pylint: disable=import-outside-toplevel

    params = dict(params)
    jp = params.get("junction_params")
    if isinstance(jp, dict):
        params["junction_params"] = json.dumps(jp, sort_keys=True)
    elif isinstance(jp, str):
        _json_dict(jp)
    return params


def _has_junction(jtype: str) -> bool:
    return str(jtype or "") not in ("", "No Squid", "Sim")


def _place_junction(element, jtype, gap: pya.Region, island: pya.DPoint, ground: pya.DPoint, params) -> None:
    from quantcore_circuits.layouts.junctions.trilayer import place_trilayer  # pylint: disable=import-outside-toplevel

    try:
        place_trilayer(element, jtype, gap, island, ground, params)
    except ValueError as e:
        element.raise_error_on_cell(f"{type(element).__name__}: {e}")


def cpw_gaps(dbu, x0, x1, a, b, axis="x", at=0.0) -> pya.Region:
    """The two gap strips of a straight CPW (centre ``a``, gaps ``b``) from ``x0`` to ``x1`` along ``axis`` (dbu)."""
    lo, hi = min(x0, x1), max(x0, x1)
    if axis == "x":
        return _region(dbu, (lo, at + a / 2, hi, at + a / 2 + b), (lo, at - a / 2 - b, hi, at - a / 2))
    return _region(dbu, (at + a / 2, lo, at + a / 2 + b, hi), (at - a / 2 - b, lo, at - a / 2, hi))


def shorted_line(dbu, x_axis, y_short, length, a, b) -> pya.Region:
    """Etch of a vertical CPW that arrives from −y and is shorted at ``y_short`` (its gaps stop there): the pump /
    flux line of QPDK's ``cpw_jpa`` (``straight_shorted``)."""
    return cpw_gaps(dbu, y_short - length, y_short, a, b, axis="y", at=x_axis)


def interdigital(dbu, x0, n, wf, gf, y_root_a, y_root_b) -> tuple[pya.Region, float]:
    """Fingers of an interdigital capacitor between two electrodes along y: electrode A's fingers rise from
    ``y_root_a`` to ``y_root_b − gf``, B's hang from ``y_root_b`` to ``y_root_a + gf`` (either order of the roots),
    alternating along +x from ``x0`` (A first, ``n`` fingers in all, pitch ``wf + gf``). Returns (A ∪ B fingers as
    metal, x of the last finger's far edge)."""
    out = pya.Region()
    s = 1.0 if y_root_b > y_root_a else -1.0
    x = x0
    for i in range(int(n)):
        if i % 2 == 0:
            out.insert(_box(dbu, x, y_root_a, x + wf, y_root_b - s * gf))
        else:
            out.insert(_box(dbu, x, y_root_b, x + wf, y_root_a + s * gf))
        x += wf + gf
    return out, x - gf


def meander_strip(dbu, x0, x1, y0, y1, width, turns) -> tuple[pya.Region, float]:
    """A strip of ``width`` from (centre x, ``y0``) to (centre x, ``y1``) meandering ``turns`` times across
    [x0, x1] (vertical runs, horizontal legs): the lumped inductors. Returns (metal, developed centre-line length)."""
    turns = max(int(turns), 0)
    if turns == 0:
        xm = (x0 + x1) / 2
        path = [pya.DPoint(xm, y0), pya.DPoint(xm, y1)]
    else:
        lo, hi = x0 + width / 2, x1 - width / 2
        step = (y1 - y0) / (turns + 1)
        x = lo
        path = [pya.DPoint(x, y0)]
        for k in range(turns):  # rise one step, cross to the other side
            y = y0 + (k + 1) * step
            path.append(pya.DPoint(x, y))
            x = hi if x == lo else lo
            path.append(pya.DPoint(x, y))
        path.append(pya.DPoint(x, y1))
    length = sum((path[i + 1] - path[i]).length() for i in range(len(path) - 1))
    dpath = pya.DPath(path, width, width / 2, width / 2)
    return pya.Region(dpath.polygon().to_itype(dbu)), length


def drawn_junction_values(jtype: str, junction_params) -> tuple[float | None, float, str]:
    """(L_J nH, C_J fF, source) of the trilayer cell ``jtype`` drawn with ``junction_params`` (PDK junction rule;
    SQUID: the parallel total at zero flux); (None, 0, …) for ``Sim`` / no junction."""
    from quantcore_circuits.layouts.junctions.trilayer import (  # pylint: disable=import-outside-toplevel
        _json_dict,
        trilayer_junction_values,
    )

    if not _has_junction(jtype):
        return None, 0.0, f"no junction drawn ({jtype!r})"
    values = trilayer_junction_values(str(jtype), _json_dict(junction_params))
    if values is None:
        return None, 0.0, f"{jtype!r} is not a trilayer cell"
    return round(values.lj_nH, 5), round(values.cj_fF, 3), f"drawn {jtype} (PDK junction rule)"


def instance_junction(inst, p: dict) -> tuple[float | None, float, str]:
    """(L_J nH, C_J fF, source): the design's ``junction`` (first entry of a list) wins over the drawn values."""
    j = getattr(inst, "junction", None)
    if j is not None and j.Lj_nH is not None:
        lj = j.Lj_nH[0] if isinstance(j.Lj_nH, list) else j.Lj_nH
        cj = (j.Cj_fF[0] if isinstance(j.Cj_fF, list) else j.Cj_fF) or 0.0
        return float(lj), float(cj), "design"
    return drawn_junction_values(p.get("junction_type"), p.get("junction_params") or "{}")


def _pdk_obj(pdk):
    if pdk is None or isinstance(pdk, str):
        from quantcore_circuits.pdk import DEFAULT_PDK, get_pdk  # pylint: disable=import-outside-toplevel

        return get_pdk(pdk or DEFAULT_PDK)
    return pdk


def cpw_inductance_per_m(a_um: float, b_um: float, pdk=None, f_GHz: float = 6.5) -> float:
    """L' (H/m) of a CPW on the PDK stack, geometric + the film's kinetic inductance (``cpw_properties``)."""
    from quantcore_circuits.analysis.synthesis import cpw_properties  # pylint: disable=import-outside-toplevel

    q = cpw_properties(f_GHz, a_um, b_um, _pdk_obj(pdk).name)
    return q["Z0_ohm"] / q["vp_m_s"]


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float(default)


# ---- SQUID termination (QPDK) ---------------------------------------------------------------------------------------
class SquidTermination(Element):
    """CPW lead shorted to ground through a trilayer SQUID, with a shorted pump / flux line (QPDK ``squid_termination``
    and the pump of ``cpw_jpa``).

    Port ``a`` at the origin faces −x (CPW ``a``/``b``); the lead runs to x = ``lead_length`` and ends on a landing
    ``head`` in an etched pocket ``pocket_width`` wide; a head wider than the CPW (``a`` + 2 ``b``) gets ``b`` of pocket
    before it as well (the pocket then starts at ``lead_length`` − ``b`` around the centre conductor), so the lead
    reaches ground only through the junction. The junction gap ``junction_gap`` beyond the head is bridged by the
    junction cell ``junction_type`` (default
    the PDK ``Quantcore Squid``; its island side lands on the lead end, its ground side on the far pocket edge;
    refpoints ``port_squid_a`` / ``port_squid_b``). With ``pump_line`` a CPW (``a``/``b``) runs along +y past the
    ground side of the SQUID, ``pump_gap`` of ground between the pocket and its gap, shorted ``pump_offset`` beyond the
    SQUID axis; its port ``pump`` is ``pump_length`` below the short and faces −y. The pump current and its return
    through that ground strip thread the SQUID loop (mutual M: extract it by EM; QPDK's SAX model has none either).

    LOM: the SQUID is the λ/4 line's shorted end at its inductive equivalent length ℓ_eq = lead + L_s(Φ)/L' (L' of the
    a/b CPW incl. the film's kinetic inductance), so f_r = f_λ/4 / (1 + L_s/L'ℓ) (Yamamoto 2008; QPDK); L_s(Φ) =
    L_s0/|cos πΦ/Φ0| at the static bias ``flux_phi0``. The Kerr / 3WM nonlinearity is not in the lumped circuit:
    :mod:`quantcore_circuits.analysis.amplifiers` takes it from the same values.
    """

    lead_length = Param(pdt.TypeDouble, "CPW lead length", 10, unit="μm")
    head = Param(pdt.TypeList, "Landing head at the lead end in the pocket (length, width), µm", [6, 28])
    junction_gap = Param(pdt.TypeDouble, "Pocket length along the lead (the junction window height)", 20, unit="μm")
    pocket_width = Param(pdt.TypeDouble, "Pocket width across the lead", 34, unit="μm")
    junction_type = Param(
        pdt.TypeString, "Junction across the pocket (trilayer cell)", "Quantcore Squid", choices=_JUNCTIONS
    )
    junction_params = Param(pdt.TypeString, "Trilayer junction cell parameters (JSON dict)", "{}")
    flux_phi0 = Param(pdt.TypeDouble, "Static flux bias of the SQUID (LOM)", 0.0, unit="Φ0")
    pump_line = Param(pdt.TypeBoolean, "Draw the shorted pump / flux line", True)
    pump_length = Param(pdt.TypeDouble, "Pump line length (port to short)", 200, unit="μm")
    pump_gap = Param(pdt.TypeDouble, "Ground strip between the pocket and the pump line gap", 2, unit="μm")
    pump_offset = Param(pdt.TypeDouble, "Pump short beyond the SQUID axis", 20, unit="μm")

    qcc_category = "termination"

    @classmethod
    def qcc_params(cls, params: dict) -> dict:
        return _json_params(params)

    def _pump_axis(self) -> float:
        return self._far() + self.pump_gap + self.b + self.a / 2

    def _far(self) -> float:
        return self.lead_length + _f(list(self.head)[0]) + self.junction_gap

    def build(self):
        dbu = self.layout.dbu
        a, b, lead, g = self.a, self.b, self.lead_length, self.junction_gap
        w = max(self.pocket_width, a + 2 * b)
        if lead < 0 or g <= 0:
            self.raise_error_on_cell("SquidTermination: lead_length must be >= 0 and junction_gap > 0")
        etch = cpw_gaps(dbu, 0, lead, a, b) if lead > 0 else pya.Region()
        h_len, h_w = (_f(v) for v in list(self.head)[:2])
        if h_w > w - 2 or h_len < 0:
            self.raise_error_on_cell("SquidTermination: head must fit the pocket (width <= pocket_width - 2)")
        x_j = lead + h_len  # island side of the junction gap
        # A head wider than the CPW (a + 2b) would touch the ground beside the lead at x = lead and short the lead past
        # the SQUID: the pocket then starts b before the head, around the lead's centre conductor, so the head is
        # surrounded by etch and the lead reaches ground only through the junction.
        x_back = lead - b if h_w > a + 2 * b else lead
        pocket = _region(dbu, (x_back, -w / 2, x_j + g, w / 2))
        etch += pocket - _region(dbu, (lead, -h_w / 2, x_j, h_w / 2), (x_back, -a / 2, lead, a / 2))
        pocket = _region(dbu, (x_j, -w / 2, x_j + g, w / 2))  # the junction gap
        if self.pump_line:
            if self.pump_length <= self.pump_offset + w / 2:
                self.raise_error_on_cell("SquidTermination: pump_length must reach below the pocket")
            x_p = self._pump_axis()
            etch += shorted_line(dbu, x_p, self.pump_offset, self.pump_length, a, b)
            self.add_port("pump", pya.DPoint(x_p, self.pump_offset - self.pump_length), pya.DVector(0, -1))
            self.refpoints["short"] = pya.DPoint(x_p, self.pump_offset)
        etch.merge()
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(etch)
        self.add_protection(pya.Region(etch.bbox()).sized(self.margin / dbu))
        self.add_port("a", pya.DPoint(0, 0), pya.DVector(-1, 0))
        island, ground = pya.DPoint(x_j, 0), pya.DPoint(x_j + g, 0)
        self.refpoints["port_squid_a"], self.refpoints["port_squid_b"] = island, ground
        self.refpoints["squid"] = pya.DPoint(x_j + g / 2, 0)
        if _has_junction(self.junction_type):
            _place_junction(self, self.junction_type, pocket, island, ground, self.junction_params)

    @classmethod
    def qcc_squid(cls, params: dict, inst=None) -> dict:
        """{L_s0 nH (zero flux), L_s nH (at ``flux_phi0``), C_J fF, source}: the termination's SQUID."""
        from quantcore_circuits.layouts.others.keepout import full_params  # pylint: disable=import-outside-toplevel

        p = full_params(cls, params)
        lj, cj, source = (
            instance_junction(inst, p)
            if inst is not None
            else drawn_junction_values(p["junction_type"], p["junction_params"])
        )
        squid = "squid" in str(p["junction_type"]).lower()
        phi = _f(p.get("flux_phi0"))
        ls = None if lj is None else (lj / max(abs(math.cos(math.pi * phi)), 1e-6) if squid else lj)
        return {"Ls0_nH": lj, "Ls_nH": ls, "Cj_fF": cj, "flux_phi0": phi, "squid": squid, "source": source}

    @classmethod
    def qcc_lom(cls, name: str, inst, pdk):
        """The lead is the routed line's last section; the SQUID adds L_s/L' of electrical length (shorted end)."""
        from quantcore_circuits.lom.fragment import Fragment, Line, cell_params  # pylint: disable=C0415

        p = cell_params(inst)
        a, b = _f(p.get("a"), 10), _f(p.get("b"), 6)
        sq = cls.qcc_squid(p, inst)
        l_per_m = cpw_inductance_per_m(a, b, pdk)
        extra = (sq["Ls_nH"] or 0.0) * 1e-9 / l_per_m * 1e6
        frag = Fragment(nodes={"lead": {"island": f"{name}.lead"}}, port_nodes={"a": "lead"})
        if p.get("pump_line", True):
            frag.port_nodes["pump"] = "control:flux"
        length = _f(p.get("lead_length"), 10) + _f(list(p.get("head") or [6])[0]) + extra
        frag.lines.append(Line(name, "lead", ("a", None), length, a, b, ("short", "short"), through=True))
        if sq["squid"]:
            frag.knobs[f"{name}.flux_phi0"] = (0.0, 0.45)
        frag.notes.append(
            f"{name}: SQUID L_s = {sq['Ls_nH'] or 0:.4g} nH at Φ = {sq['flux_phi0']:g} Φ0 ({sq['source']}) → "
            f"{extra:.0f} µm of {a:g}/{b:g} µm CPW at the shorted end (L' {l_per_m * 1e9:.0f} nH/m incl. kinetic); the "
            "SQUID's Kerr / three-wave mixing is not in the lumped circuit (analysis.amplifiers)"
        )
        return frag


# ---- lumped JPA (twpa-sim jpa / squid_jpa) --------------------------------------------------------------------------
class LumpedJpa(Element):
    """Lumped JPA: a trilayer junction or SQUID to ground, shunted by an interdigital capacitor (twpa-sim ``jpa`` /
    ``squid_jpa``, MIM shunt → planar IDC on the PDK).

    Port ``signal`` at the origin faces −x (CPW ``a``/``b``, ``lead_length`` long) into a pocket holding the island: a
    spine (``spine_width``) with ``shunt_fingers`` fingers on each side interleaved with ground fingers hanging from
    the pocket walls (``finger_length`` / ``finger_width`` / ``finger_gap``; one gap everywhere).

    * ``coupling="capacitive"``: the lead joins the island (the port *is* the island conductor; put a coupling
      capacitor, e.g. KQC ``FingerCapacitorSquare``, between the feed and ``signal``). The junction bridges a
      ``junction_gap`` between the island's far end and the pocket wall; with ``flux_line`` a shorted CPW (port
      ``flux``) runs past it (SQUID flux bias / pump), as :class:`SquidTermination`.
    * ``coupling="inductive"``: the lead ends on a tap pad tied to the pocket floor by a strip (``tap_width``) — the
      coupling inductance shared by the signal line and the JPA loop; the junction bridges the tap pad and the island.

    LOM: ``island`` with the IDC shunt C to ground (Igreja–Dias IDC + the spine, analytic), the junction / SQUID
    (drawn values on the PDK rule unless the design gives ``junction``); capacitive: ``signal`` → island;
    inductive: ``tap`` node (small pad C) with the strip inductance to ground (geometric + kinetic,
    :func:`quantcore_circuits.circuit.kinetic.wire_inductance`), ``signal`` → tap.
    """

    coupling = Param(pdt.TypeString, "Coupling to the signal line", "capacitive", choices=["capacitive", "inductive"])
    junction_type = Param(pdt.TypeString, "Junction (trilayer cell)", "Quantcore Junction", choices=_JUNCTIONS)
    junction_params = Param(pdt.TypeString, "Trilayer junction cell parameters (JSON dict)", "{}")
    lead_length = Param(pdt.TypeDouble, "CPW lead from the port to the pocket", 50, unit="μm")
    spine_width = Param(pdt.TypeDouble, "Island spine width", 20, unit="μm")
    shunt_fingers = Param(pdt.TypeInt, "Island fingers per side", 20)
    finger_length = Param(pdt.TypeDouble, "Finger length", 100, unit="μm")
    finger_width = Param(pdt.TypeDouble, "Finger width", 4, unit="μm")
    finger_gap = Param(pdt.TypeDouble, "Gap between fingers (and all island clearances)", 4, unit="μm")
    junction_gap = Param(pdt.TypeDouble, "Junction gap (window height)", 16, unit="μm")
    tap_width = Param(pdt.TypeDouble, "Inductive coupling strip width", 4, unit="μm")
    tap_pad = Param(pdt.TypeList, "Inductive coupling tap pad (length along x, width), µm", [20, 24])
    flux_line = Param(pdt.TypeBoolean, "Draw a shorted flux / pump line past the junction (capacitive)", False)
    flux_length = Param(pdt.TypeDouble, "Flux line length (port to short)", 200, unit="μm")
    flux_gap = Param(pdt.TypeDouble, "Ground strip between the pocket and the flux line gap", 2, unit="μm")
    flux_offset = Param(pdt.TypeDouble, "Flux short beyond the junction axis", 20, unit="μm")
    flux_phi0 = Param(pdt.TypeDouble, "Static flux bias of a SQUID (LOM)", 0.0, unit="Φ0")

    qcc_category = "resonator"

    @classmethod
    def qcc_params(cls, params: dict) -> dict:
        return _json_params(params)

    @classmethod
    def qcc_geometry(cls, params: dict) -> dict:
        """Key coordinates (µm, local frame) of the drawing: pocket, island span, junction gap, tap."""
        from quantcore_circuits.layouts.others.keepout import full_params  # pylint: disable=import-outside-toplevel

        p = full_params(cls, params)
        wf, gf, lf, ws = (_f(p[k]) for k in ("finger_width", "finger_gap", "finger_length", "spine_width"))
        n, hj, lead = int(p["shunt_fingers"]), _f(p["junction_gap"]), _f(p["lead_length"])
        tap_len, tap_w = (_f(v) for v in list(p["tap_pad"])[:2])
        half_h = ws / 2 + lf + gf
        x_p0 = lead
        inductive = p["coupling"] == "inductive"
        x_i0 = x_p0 + tap_len + hj if inductive else x_p0 + gf
        margin = gf + 2.0  # spine beyond the outer ground fingers: they stay clear of the junction window
        x_f0 = x_i0 + margin
        x_i1 = x_f0 + n * 2 * (wf + gf) + wf + margin
        x_r = x_i1 + (gf if inductive else hj)
        return {
            "x_p0": x_p0,
            "x_i0": x_i0,
            "x_f0": x_f0,
            "x_i1": x_i1,
            "x_r": x_r,
            "half_h": half_h,
            "tap_len": tap_len,
            "tap_w": tap_w,
            "tap_strip_um": half_h - tap_w / 2,
            "inductive": inductive,
        }

    def build(self):
        dbu = self.layout.dbu
        geo = self.qcc_geometry({k: getattr(self, k) for k in type(self).get_schema()})
        a, b = self.a, self.b
        wf, gf, lf, ws = self.finger_width, self.finger_gap, self.finger_length, self.spine_width
        n = int(self.shunt_fingers)
        x_p0, x_i0, x_i1, x_r, hh = geo["x_p0"], geo["x_i0"], geo["x_i1"], geo["x_r"], geo["half_h"]
        if min(wf, gf, ws) <= 0 or lf <= gf or n < 1:
            self.raise_error_on_cell("LumpedJpa: finger/spine sizes must be positive, finger_length > finger_gap")
        if hh < 17:
            self.raise_error_on_cell("LumpedJpa: the pocket must be at least 34 µm high (the junction window)")
        etch = cpw_gaps(dbu, 0, x_p0, a, b) if x_p0 > 0 else pya.Region()
        pocket = _region(dbu, (x_p0, -hh, x_r, hh))
        metal = _region(dbu, (x_i0, -ws / 2, x_i1, ws / 2))
        hw = ws / 2 + gf / 2  # landing head at the junction end (a SQUID's fingers sit at ±8 µm)
        x_h = x_i0 if geo["inductive"] else x_i1 - 2.0
        metal += _region(dbu, (x_h, -max(hw, 13.0), x_h + 2.0, max(hw, 13.0)))
        pitch = 2 * (wf + gf)
        x_f0 = geo["x_f0"]
        for k in range(n):  # island fingers, both sides
            xc = x_f0 + wf / 2 + (wf + gf) + k * pitch
            metal += _region(
                dbu, (xc - wf / 2, ws / 2, xc + wf / 2, ws / 2 + lf), (xc - wf / 2, -ws / 2 - lf, xc + wf / 2, -ws / 2)
            )
        for j in range(n + 1):  # ground fingers from the pocket walls
            xc = x_f0 + wf / 2 + j * pitch
            metal += _region(
                dbu, (xc - wf / 2, ws / 2 + gf, xc + wf / 2, hh), (xc - wf / 2, -hh, xc + wf / 2, -ws / 2 - gf)
            )
        if geo["inductive"]:
            tl, tw = geo["tap_len"], geo["tap_w"]
            xt = x_p0 + tl / 2
            metal += _region(
                dbu,
                (x_p0, -tw / 2, x_p0 + tl, tw / 2),
                (xt - self.tap_width / 2, -hh, xt + self.tap_width / 2, -tw / 2),
            )
            jgap = _region(dbu, (x_p0 + tl, -17, x_i0, 17))
            island, ground = pya.DPoint(x_i0, 0), pya.DPoint(x_p0 + tl, 0)
        else:
            metal += _region(dbu, (x_p0, -a / 2, x_i0, a / 2))  # the lead crosses the pocket gap into the island
            jgap = _region(dbu, (x_i1, -17, x_r, 17))
            island, ground = pya.DPoint(x_i1, 0), pya.DPoint(x_r, 0)
            if self.flux_line:
                x_f = x_r + self.flux_gap + b + a / 2
                etch += shorted_line(dbu, x_f, self.flux_offset, self.flux_length, a, b)
                self.add_port("flux", pya.DPoint(x_f, self.flux_offset - self.flux_length), pya.DVector(0, -1))
        etch += pocket - metal
        etch.merge()
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(etch)
        self.add_protection(pya.Region(etch.bbox()).sized(self.margin / dbu))
        self.add_port("signal", pya.DPoint(0, 0), pya.DVector(-1, 0))
        self.refpoints["port_squid_a"], self.refpoints["port_squid_b"] = island, ground
        self.refpoints["island_center"] = pya.DPoint((x_i0 + x_i1) / 2, 0)
        if _has_junction(self.junction_type):
            _place_junction(self, self.junction_type, jgap, island, ground, self.junction_params)

    @classmethod
    def qcc_values(cls, params: dict, pdk=None) -> dict:
        """Analytic circuit values of the drawing: C_shunt (fF), the tap strip inductance (nH), tap pad C (fF)."""
        from quantcore_circuits.circuit.kinetic import wire_inductance  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.layouts.others.keepout import full_params  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.lom import estimates as est  # pylint: disable=import-outside-toplevel

        p = full_params(cls, params)
        pdk = _pdk_obj(pdk)
        eps = est.substrate_eps(pdk)
        geo = cls.qcc_geometry(p)
        wf, gf, lf, ws = (_f(p[k]) for k in ("finger_width", "finger_gap", "finger_length", "spine_width"))
        n = int(p["shunt_fingers"])
        idc = 2 * est.interdigital(2 * n + 1, wf, gf, lf - gf, eps)  # both sides
        span = geo["x_i1"] - geo["x_i0"]
        ends = 2 * est.coplanar_coupling(ws, ws, ws, gf, eps)  # spine end faces (rough)
        out = {
            "C_shunt_fF": idc + ends,
            "C_idc_fF": idc,
            "island_length_um": span,
            "formula": f"2 × IDC ({2 * n + 1} fingers {wf:g}/{gf:g} µm, overlap {lf - gf:g} µm, Igreja–Dias)"
            " + spine ends",
        }
        if geo["inductive"]:
            w = wire_inductance(geo["tap_strip_um"], _f(p["tap_width"]), pdk)
            out |= {
                "L_tap_nH": w["L_nH"],
                "L_tap_geo_nH": w["L_geo_nH"],
                "L_tap_k_nH": w["L_k_nH"],
                "C_tap_fF": est.pad_to_ground(geo["tap_len"], geo["tap_w"], gf, gf, eps),
            }
        return out

    @classmethod
    def qcc_lom(cls, name: str, inst, pdk):
        from quantcore_circuits.lom import estimates as est  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.lom.fragment import Element as Branch  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.lom.fragment import Fragment, cell_params  # pylint: disable=import-outside-toplevel

        p = cell_params(inst)
        v = cls.qcc_values(p, pdk)
        lj, cj, source = instance_junction(inst, p)
        squid = "squid" in str(p.get("junction_type", "")).lower()
        inductive = p.get("coupling") == "inductive"
        frag = Fragment(nodes={"island": {"island": f"{name}.island"}})
        frag.elements.append(
            Branch(
                f"C_{name}",
                "C",
                ("island", "gnd"),
                est.cap(v["C_shunt_fF"], "analytic", v["formula"]),
                {"param": f"{name}.shunt_fingers"},
            )
        )
        other = "gnd"
        if inductive:
            frag.nodes["tap"] = {"island": f"{name}.tap"}
            frag.port_nodes["signal"] = "tap"
            other = "tap"
            frag.elements.append(
                Branch(
                    f"Ltap_{name}",
                    "L",
                    ("tap", "gnd"),
                    {
                        "L_nH": round(v["L_tap_nH"], 5),
                        "L_k_nH": round(v["L_tap_k_nH"], 5),
                        "source": "analytic: strip (Grover) + film kinetic inductance",
                    },
                    {"param": f"{name}.tap_width"},
                )
            )
            frag.elements.append(
                Branch(
                    f"Ctap_{name}", "C", ("tap", "gnd"), est.cap(v["C_tap_fF"], "rough", "tap pad to the pocket walls")
                )
            )
        else:
            frag.port_nodes["signal"] = "island"
            if p.get("flux_line"):
                frag.port_nodes["flux"] = "control:flux"
        value = {"Lj_nH": lj, "Cj_fF": cj, "source": source}
        if squid:
            # the static bias is applied here (L_s(Φ) = L_s0/|cos πΦ|): the LOM simulation takes Lj_nH as given
            phi = _f(p.get("flux_phi0"))
            if lj:
                value["Lj_nH"] = round(lj / max(abs(math.cos(math.pi * phi)), 1e-6), 6)
            value |= {"asym": 0.0, "flux_phi0": 0.0, "Lj0_nH": lj, "bias_phi0": phi}
        frag.elements.append(
            Branch(
                f"J_{name}", "SQUID" if squid else "JJ", ("island", other), value, {"param": f"{name}.junction.Lj_nH"}
            )
        )
        if lj:
            frag.knobs[f"{name}.junction.Lj_nH"] = (round(lj * 0.5, 4), round(lj * 1.5, 4))
        else:
            frag.notes.append(f"{name}: no junction L_J ({source}); give the instance a junction to simulate it")
        frag.notes.append(f"{name}: lumped JPA, C_shunt ≈ {v['C_shunt_fF']:.0f} fF (analytic IDC)")
        return frag


# ---- 4WM JTWPA chain ------------------------------------------------------------------------------------------------
class JtwpaChain(Element):
    """Series chain of ``cells`` trilayer junctions along +x (4WM JTWPA; twpa-sim ``jtwpa4wm``; QPDK resonantly
    phase-matched JTWPA): ports ``a`` (origin, faces −x) and ``b`` (x = 2·lead + cells·cell_pitch, faces +x), CPW
    ``a``/``b`` leads of ``lead_length``.

    Between the leads the centre line is cut into ``cells + 1`` islands (``island_width``; the end islands are half
    islands, so the end shunts are halved, as the finite-chain convention) separated by ``junction_gap``; each cut is
    bridged by the junction cell ``junction_type`` (default ``Quantcore Junction``). Each island is shunted to ground
    by ``shunt_fingers`` fingers per side interleaved with ground fingers hanging from the trench walls (the chain's
    ground capacitance C_g). With ``resonator_every`` = M > 0, every M-th node (``resonator_offset``, M, 2M, …) loses
    its top or bottom fingers (alternating) and gets a lumped LC resonator beyond the trench wall: a lead through a slot
    to an interdigital coupling capacitor (``coupling_fingers``), a pad (``resonator_pad``) and a meander inductor
    (``inductor_turns``, ``inductor_width``) to the pocket wall — O'Brien et al. 2014 resonant phase matching.

    LOM: nodes ``n0`` … ``n<cells>`` (``a`` → n0, ``b`` → n<cells>), a JJ between neighbours (drawn L_J / C_J, or the
    design's ``junction``), C_g to ground per node (analytic IDC), and per resonator ``r<k>``: C_c, C_r, L_r
    (geometric + kinetic meander). Long chains exceed QuCat: :mod:`quantcore_circuits.analysis.amplifiers` solves
    the linear ladder (ABCD) and the coupled-mode gain from the same values.
    """

    cells = Param(pdt.TypeInt, "Junctions in the chain", 16)
    cell_pitch = Param(pdt.TypeDouble, "Junction pitch", 60, unit="μm")
    lead_length = Param(pdt.TypeDouble, "CPW lead at each end", 30, unit="μm")
    island_width = Param(pdt.TypeDouble, "Island (centre line) width", 20, unit="μm")
    junction_gap = Param(pdt.TypeDouble, "Cut between islands (junction window height)", 12, unit="μm")
    junction_type = Param(pdt.TypeString, "Junction (trilayer cell)", "Quantcore Junction", choices=_JUNCTIONS)
    junction_params = Param(pdt.TypeString, "Trilayer junction cell parameters (JSON dict)", "{}")
    shunt_fingers = Param(pdt.TypeInt, "Island fingers per side per full island", 4)
    shunt_finger_length = Param(pdt.TypeDouble, "Shunt finger length", 40, unit="μm")
    shunt_finger_width = Param(pdt.TypeDouble, "Shunt finger width", 2, unit="μm")
    shunt_gap = Param(pdt.TypeDouble, "Gap between shunt fingers / to the walls", 2, unit="μm")
    resonator_every = Param(pdt.TypeInt, "A resonator on every M-th node (0 = none)", 4)
    resonator_offset = Param(pdt.TypeInt, "First resonator node", 2)
    wall = Param(pdt.TypeDouble, "Ground wall between the trench and a resonator pocket", 10, unit="μm")
    coupling_fingers = Param(pdt.TypeInt, "Coupling capacitor fingers", 10)
    coupling_finger_length = Param(pdt.TypeDouble, "Coupling finger length", 40, unit="μm")
    resonator_pad = Param(pdt.TypeList, "Resonator pad (width along x, height), µm", [160, 120])
    resonator_gap = Param(pdt.TypeDouble, "Pad / inductor clearance in the resonator pocket", 10, unit="μm")
    inductor_width = Param(pdt.TypeDouble, "Meander inductor strip width", 2, unit="μm")
    inductor_turns = Param(pdt.TypeInt, "Meander inductor turns", 10)
    inductor_height = Param(pdt.TypeDouble, "Meander inductor height (pad to wall)", 120, unit="μm")

    qcc_category = "waveguide"

    @classmethod
    def qcc_params(cls, params: dict) -> dict:
        return _json_params(params)

    @classmethod
    def qcc_layout(cls, params: dict) -> dict:
        """Chain coordinates (µm): junction x positions, island spans, resonator nodes / sides, trench half-width."""
        from quantcore_circuits.layouts.others.keepout import full_params  # pylint: disable=import-outside-toplevel

        p = full_params(cls, params)
        n, pitch, lead = int(p["cells"]), _f(p["cell_pitch"]), _f(p["lead_length"])
        gj = _f(p["junction_gap"])
        xj = [lead + (j + 0.5) * pitch for j in range(n)]
        x_end = lead + n * pitch
        islands = [(lead if k == 0 else xj[k - 1] + gj / 2, x_end if k == n else xj[k] - gj / 2) for k in range(n + 1)]
        m, off = int(p["resonator_every"]), int(p["resonator_offset"])
        res = [k for k in range(1, n) if m > 0 and k >= off and (k - off) % m == 0]
        sides = {k: (1 if i % 2 == 0 else -1) for i, k in enumerate(res)}
        half = _f(p["island_width"]) / 2 + _f(p["shunt_gap"]) + _f(p["shunt_finger_length"])
        return {"xj": xj, "islands": islands, "x_end": x_end + lead, "resonators": sides, "trench": half}

    @classmethod
    def qcc_probes(cls, params: dict) -> dict:
        """LOM node → a point on its island (µm, cell frame) for naming the FEM nets: ``n<k>`` at the middle of island
        k on the centre line (the simulation export probes them; no port touches the inner islands)."""
        return {f"n{k}": ((xa + xb) / 2, 0.0) for k, (xa, xb) in enumerate(cls.qcc_layout(params)["islands"])}

    def build(self):
        dbu = self.layout.dbu
        lay = self.qcc_layout({k: getattr(self, k) for k in type(self).get_schema()})
        a, b = self.a, self.b
        wi, gs, lsf, wsf = self.island_width, self.shunt_gap, self.shunt_finger_length, self.shunt_finger_width
        n, gj, lead = int(self.cells), self.junction_gap, self.lead_length
        half = lay["trench"]
        x0, x1 = lead, lay["x_end"] - lead
        if n < 1 or self.cell_pitch <= gj or min(wi, gs, wsf) <= 0:
            self.raise_error_on_cell("JtwpaChain: need cells >= 1, cell_pitch > junction_gap, positive widths")
        etch = cpw_gaps(dbu, 0, lead, a, b) + cpw_gaps(dbu, x1, x1 + lead, a, b)
        trench = _region(dbu, (x0, -half, x1, half))
        metal = pya.Region()
        pitch_f = 2 * (wsf + gs)
        res = lay["resonators"]
        pad_w, pad_h = (_f(v) for v in list(self.resonator_pad)[:2])
        for k, (xa, xb) in enumerate(lay["islands"]):
            metal += _region(dbu, (xa, -wi / 2, xb, wi / 2))  # the end islands meet the leads' centre lines
            span = xb - xa
            nf = int(self.shunt_fingers) if 0 < k < n else max(int(self.shunt_fingers) // 2, 1)
            used = nf * pitch_f + wsf
            if used > span:
                nf = max(int((span - wsf) // pitch_f), 0)
                used = nf * pitch_f + wsf
            start = xa + (span - used) / 2
            for side in (1, -1):
                if res.get(k) == side or nf == 0:
                    continue
                y_root, y_wall = side * wi / 2, side * half
                for f in range(nf):  # island fingers
                    xc = start + wsf / 2 + (wsf + gs) + f * pitch_f
                    metal += _region(dbu, (xc - wsf / 2, y_root, xc + wsf / 2, y_root + side * lsf))
                for g in range(nf + 1):  # ground fingers
                    xc = start + wsf / 2 + g * pitch_f
                    metal += _region(dbu, (xc - wsf / 2, y_wall, xc + wsf / 2, y_root + side * gs))
        for k, side in res.items():  # a resonator's lead keeps its metal through the trench (island to the slot)
            xa, xb = lay["islands"][k]
            lead_w = max(wsf * 2, 4.0)
            xc = (xa + xb) / 2
            y0, y1 = sorted((side * wi / 2, side * (half + gs)))
            metal += _region(dbu, (xc - lead_w / 2, y0, xc + lead_w / 2, y1))
        etch += trench - metal
        for xc in lay["xj"]:
            cut = _region(dbu, (xc - gj / 2, -wi / 2, xc + gj / 2, wi / 2))
            if _has_junction(self.junction_type):
                _place_junction(
                    self,
                    self.junction_type,
                    cut,
                    pya.DPoint(xc + gj / 2, 0),
                    pya.DPoint(xc - gj / 2, 0),
                    self.junction_params,
                )
        for i, (k, side) in enumerate(sorted(res.items())):
            xa, xb = lay["islands"][k]
            xc = (xa + xb) / 2
            etch += self._resonator(dbu, xc, side, half, pad_w, pad_h)
            self.refpoints[f"resonator_{i}"] = pya.DPoint(xc, side * (half + self.wall))
        etch.merge()
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(etch)
        self.add_protection(pya.Region(etch.bbox()).sized(self.margin / dbu))
        self.add_port("a", pya.DPoint(0, 0), pya.DVector(-1, 0))
        self.add_port("b", pya.DPoint(lay["x_end"], 0), pya.DVector(1, 0))

    def _resonator(self, dbu, xc, side, half, pad_w, pad_h) -> pya.Region:
        """Etch of one loading resonator above (side +1) / below (−1) the trench at x = xc."""
        wi, gs, gr = self.island_width, self.shunt_gap, self.resonator_gap
        wl, wsf = max(self.inductor_width, 0.5), self.shunt_finger_width
        nc, lc = max(int(self.coupling_fingers), 2), self.coupling_finger_length
        bus_w = max(nc * (wsf + gs) - gs, 2 * gs + wsf)
        lead_w = max(wsf * 2, 4.0)
        y_wall0 = half  # trench wall (|y|), wall up to half + wall
        y_p0 = half + self.wall  # pocket floor
        y_bus0 = y_p0 + gr  # coupling bus
        y_bus1 = y_bus0 + gs * 2
        y_pad0 = y_bus1 + lc + gs
        y_pad1 = y_pad0 + pad_h
        y_ind1 = y_pad1 + self.inductor_height
        y_top = y_ind1  # pocket ceiling (the inductor lands on it)
        w_pocket = max(pad_w, bus_w) + 2 * gr
        pocket = [(xc - w_pocket / 2, y_p0, xc + w_pocket / 2, y_top)]
        slot = [(xc - lead_w / 2 - gs, y_wall0 - gs, xc + lead_w / 2 + gs, y_p0)]  # through the trench wall
        metal = [
            (xc - lead_w / 2, wi / 2, xc + lead_w / 2, y_bus0),  # lead from the island through the slot
            (xc - bus_w / 2, y_bus0, xc + bus_w / 2, y_bus1),  # coupling bus
            (xc - pad_w / 2, y_pad0, xc + pad_w / 2, y_pad1),
        ]  # resonator pad

        def flip(box):
            x0, y0, x1, y1 = box
            return (x0, side * y0, x1, side * y1)

        etch = _region(dbu, *(flip(bx) for bx in pocket + slot))
        met = _region(dbu, *(flip(bx) for bx in metal))
        fingers, _ = interdigital(dbu, xc - bus_w / 2, nc, wsf, gs, y_bus1, y_pad0)
        if side < 0:
            fingers.transform(pya.Trans(pya.Trans.M0))
        met += fingers
        ind, _ = meander_strip(dbu, xc - pad_w / 2, xc + pad_w / 2, y_pad1, y_ind1 + wl, wl, int(self.inductor_turns))
        if side < 0:
            ind.transform(pya.Trans(pya.Trans.M0))
        met += ind
        return etch - met

    @classmethod
    def qcc_values(cls, params: dict, pdk=None) -> dict:
        """Per-cell analytic values: C_g (fF, full / end island), C_c, C_r (fF), L_r (nH, geometric + kinetic),
        the meander length, and the drawn junction."""
        from quantcore_circuits.circuit.kinetic import wire_inductance  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.layouts.others.keepout import full_params  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.lom import estimates as est  # pylint: disable=import-outside-toplevel

        p = full_params(cls, params)
        pdk = _pdk_obj(pdk)
        eps = est.substrate_eps(pdk)
        lay = cls.qcc_layout(p)
        wi, gs, lsf, wsf = (
            _f(p[k]) for k in ("island_width", "shunt_gap", "shunt_finger_length", "shunt_finger_width")
        )
        nf = int(p["shunt_fingers"])

        def shunt(n_fingers: int, sides: int) -> float:
            if n_fingers <= 0:
                return 0.0
            return sides * est.interdigital(2 * n_fingers + 1, wsf, gs, lsf - gs, eps)

        span = lay["islands"][1][1] - lay["islands"][1][0] if len(lay["islands"]) > 2 else _f(p["cell_pitch"])
        c_line = span * est.cpw_c_per_um(wi, gs, eps) * 0.0  # the spine edges face the ground fingers' roots: in IDC
        nc, lc = max(int(p["coupling_fingers"]), 2), _f(p["coupling_finger_length"])
        pad_w, pad_h = (_f(v) for v in list(p["resonator_pad"])[:2])
        gr = _f(p["resonator_gap"])
        c_c = est.interdigital(nc, wsf, gs, lc - gs, eps)
        c_r = est.pad_to_ground(pad_w, pad_h, gr, gr, eps)
        wl = max(_f(p["inductor_width"]), 0.5)
        y0, y1 = 0.0, _f(p["inductor_height"]) + wl
        _, length = meander_strip(0.001, -pad_w / 2, pad_w / 2, y0, y1, wl, int(p["inductor_turns"]))
        ind = wire_inductance(length, wl, pdk)
        lj, cj, source = drawn_junction_values(p["junction_type"], p["junction_params"])
        return {
            "Cg_fF": shunt(nf, 2) + c_line,
            "Cg_loaded_fF": shunt(nf, 1) + c_line,
            "Cg_end_fF": shunt(max(nf // 2, 1), 2),
            "Cc_fF": c_c,
            "Cr_fF": c_r,
            "Lr_nH": ind["L_nH"],
            "Lr_k_nH": ind["L_k_nH"],
            "inductor_length_um": length,
            "Lj_nH": lj,
            "Cj_fF": cj,
            "junction_source": source,
            "resonators": sorted(lay["resonators"]),
        }

    @classmethod
    def qcc_lom(cls, name: str, inst, pdk):
        from quantcore_circuits.lom import estimates as est  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.lom.fragment import Element as Branch  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.lom.fragment import Fragment, cell_params  # pylint: disable=import-outside-toplevel

        p = cell_params(inst)
        v = cls.qcc_values(p, pdk)
        n = int(p["cells"])
        lj, cj, source = instance_junction(inst, p)
        frag = Fragment(
            nodes={f"n{k}": {"island": f"{name}.n{k}"} for k in range(n + 1)}, port_nodes={"a": "n0", "b": f"n{n}"}
        )
        res = set(v["resonators"])
        for k in range(n + 1):
            cg = v["Cg_end_fF"] if k in (0, n) else (v["Cg_loaded_fF"] if k in res else v["Cg_fF"])
            frag.elements.append(
                Branch(
                    f"Cg_{name}_{k}",
                    "C",
                    (f"n{k}", "gnd"),
                    est.cap(max(cg, 0.01), "analytic", "shunt fingers (IDC, Igreja–Dias)"),
                )
            )
        for j in range(n):
            frag.elements.append(
                Branch(
                    f"J_{name}_{j}",
                    "JJ",
                    (f"n{j}", f"n{j + 1}"),
                    {"Lj_nH": lj, "Cj_fF": cj, "source": source},
                    {"param": f"{name}.junction.Lj_nH"},
                )
            )
        for k in sorted(res):
            frag.nodes[f"r{k}"] = {"island": f"{name}.r{k}"}
            frag.elements.append(
                Branch(
                    f"Cc_{name}_{k}",
                    "C",
                    (f"n{k}", f"r{k}"),
                    est.cap(v["Cc_fF"], "analytic", "coupling IDC (Igreja–Dias)"),
                )
            )
            frag.elements.append(
                Branch(
                    f"Cr_{name}_{k}", "C", (f"r{k}", "gnd"), est.cap(v["Cr_fF"], "rough", "resonator pad to its pocket")
                )
            )
            frag.elements.append(
                Branch(
                    f"Lr_{name}_{k}",
                    "L",
                    (f"r{k}", "gnd"),
                    {
                        "L_nH": round(v["Lr_nH"], 5),
                        "L_k_nH": round(v["Lr_k_nH"], 5),
                        "source": "analytic: meander strip (Grover) + film kinetic inductance",
                    },
                )
            )
        if lj:
            frag.knobs[f"{name}.junction.Lj_nH"] = (round(lj * 0.5, 4), round(lj * 1.5, 4))
        frag.notes.append(
            f"{name}: JTWPA chain of {n} junctions (L_J {lj} nH, {source}), {len(res)} loading resonators; "
            "simulate the ladder with analysis.amplifiers (QuCat is limited to a few junctions)"
        )
        return frag


# ---- KI-TWPA serpentine (twpa-sim / NY CREATES) ---------------------------------------------------------------------
def _smooth(alpha):
    return alpha * alpha * (3.0 - 2.0 * alpha)


def _radial_rect(dbu, theta, u0, u1, hw) -> pya.Polygon:
    """A rectangle from radius ``u0`` to ``u1`` along the direction ``theta``, half-width ``hw`` across it (dbu)."""
    ux, uy, tx, ty = math.cos(theta), math.sin(theta), -math.sin(theta), math.cos(theta)
    return pya.DPolygon(
        [
            pya.DPoint(u0 * ux - hw * tx, u0 * uy - hw * ty),
            pya.DPoint(u1 * ux - hw * tx, u1 * uy - hw * ty),
            pya.DPoint(u1 * ux + hw * tx, u1 * uy + hw * ty),
            pya.DPoint(u0 * ux + hw * tx, u0 * uy + hw * ty),
        ]
    ).to_itype(dbu)


class KiTwpaSerpentine(Element):
    """Kinetic-inductance TWPA serpentine (twpa-sim ``KITLayout`` / ``kit.primitives``, the NY CREATES research
    geometry; MIT): ``rows`` straight rows of ``periods_per_row`` supercells (``unloaded_cells`` + ``loaded_cells``
    cells of ``pitch``; the loaded cells, in the middle of each supercell, have ``loaded_finger_length`` fingers) joined
    by U-turns of ``turn_radius`` with ``turn_periods`` supercells of radial fingers each. The turn spine is widened
    with a smooth-step profile (``taper_cells``) so its biased sheet-square count matches the straight rows
    (twpa-sim's approximation, ``bias_ratio``).

    Negative mask: the etch is the spine gap (``spine_gap``) and each finger's slot (``finger_gap`` around it); the
    ground between rows is the chip ground plane (twpa-sim's two separate ground combs need package grounding; here
    they are one plane). Launches: the spine tapers to the chip CPW (``a``/``b``) over ``launch_taper_length`` and runs
    ``launch_length`` straight to the ports ``a`` (row 0, input) and ``b`` (last row), both facing away from the rows.
    Rows run along x centred on the origin; row r is at y = (rows − 1 − 2r)·turn_radius.
    """

    rows = Param(pdt.TypeInt, "Rows", 2)
    periods_per_row = Param(pdt.TypeInt, "Supercells per row", 2)
    unloaded_cells = Param(pdt.TypeInt, "Unloaded cells per supercell (even)", 48)
    loaded_cells = Param(pdt.TypeInt, "Loaded cells per supercell", 6)
    turn_periods = Param(pdt.TypeInt, "Supercells per U-turn", 3)
    pitch = Param(pdt.TypeDouble, "Cell pitch", 1.5, unit="μm")
    spine_width = Param(pdt.TypeDouble, "Spine width", 0.58, unit="μm")
    spine_gap = Param(pdt.TypeDouble, "Spine gap", 0.5, unit="μm")
    finger_width = Param(pdt.TypeDouble, "Finger width", 0.5, unit="μm")
    finger_gap = Param(pdt.TypeDouble, "Finger gap", 0.25, unit="μm")
    finger_length = Param(pdt.TypeDouble, "Finger length", 75.5, unit="μm")
    loaded_finger_length = Param(pdt.TypeDouble, "Loaded finger length", 27.5, unit="μm")
    turn_radius = Param(pdt.TypeDouble, "Turn radius (row spacing / 2)", 154, unit="μm")
    bias_ratio = Param(pdt.TypeDouble, "Turn sheet-square bias ratio", 0.2)
    taper_cells = Param(pdt.TypeInt, "Turn taper cells", 6)
    arc_points = Param(pdt.TypeInt, "Points on a turn arc", 513)
    launch_taper_length = Param(pdt.TypeDouble, "Launch taper (spine → a/b)", 88, unit="μm")
    launch_length = Param(pdt.TypeDouble, "Launch straight (a/b) to the port", 155, unit="μm")
    sheet_inductance_pH_sq = Param(pdt.TypeDouble, "Film sheet kinetic inductance for the ladder (0 = PDK film)", 0.0)

    qcc_category = "waveguide"

    def _check(self) -> str:
        if self.rows < 2 or self.unloaded_cells % 2 or self.arc_points < 33:
            return "need rows >= 2, even unloaded_cells, arc_points >= 33"
        if self.pitch <= self.finger_width + 2 * self.finger_gap:
            return "finger slots leave no ground between cells"
        if self.loaded_finger_length > self.finger_length or self.turn_radius <= self.finger_length + 5:
            return "loaded fingers longer than fingers, or turn radius too small"
        if self.taper_cells * 2 >= (self.unloaded_cells + self.loaded_cells) * self.turn_periods:
            return "the turn tapers occupy the whole turn"
        return ""

    def _nc(self) -> int:
        return int(self.unloaded_cells + self.loaded_cells)

    def _loaded(self, c: int) -> bool:
        u = int(self.unloaded_cells)
        return u // 2 <= c % self._nc() < u // 2 + int(self.loaded_cells)

    def _turn_width(self):
        """(max turn spine width, width profile function) solving twpa-sim's biased sheet-square match."""
        import numpy as np  # pylint: disable=import-outside-toplevel
        from scipy.optimize import brentq  # pylint: disable=import-outside-toplevel

        w0, nturn = self.spine_width, int(self.turn_periods) * self._nc()
        dtheta = math.pi / nturn
        th = math.pi / 2 - (np.arange(nturn) + 0.5) * dtheta
        p_turn = math.pi * self.turn_radius / nturn

        def profile(theta, wmax):
            d_end = np.minimum(math.pi / 2 - theta, theta + math.pi / 2)
            return w0 + (wmax - w0) * _smooth(np.clip(d_end / (self.taper_cells * dtheta), 0.0, 1.0))

        target = nturn * (self.pitch / w0) * (1.0 + self.bias_ratio**2)

        def err(wm):
            w = profile(th, wm)
            return float(np.sum((p_turn / w) * (1.0 + self.bias_ratio**2 * (w0 / w) ** 2)) - target)

        return brentq(err, w0 / 10, 10 * w0), profile, th

    def _supercell_etch(self, dbu) -> pya.Region:
        """Etch of one straight supercell starting at x = 0 on the row axis y = 0."""
        w, s, wf, sf, lf = self.spine_width, self.spine_gap, self.finger_width, self.finger_gap, self.finger_length
        p = self.pitch
        nc = self._nc()
        etch = _region(dbu, (0, w / 2, nc * p, w / 2 + s), (0, -w / 2 - s, nc * p, -w / 2))
        fingers = pya.Region()
        for c in range(nc):
            xm = (c + 0.5) * p
            lc = self.loaded_finger_length if self._loaded(c) else lf
            etch += _region(
                dbu,
                (xm - wf / 2 - sf, w / 2 + s, xm + wf / 2 + sf, w / 2 + s + lf),
                (xm - wf / 2 - sf, -w / 2 - s - lf, xm + wf / 2 + sf, -w / 2 - s),
            )
            fingers += _region(
                dbu, (xm - wf / 2, w / 2, xm + wf / 2, w / 2 + lc), (xm - wf / 2, -w / 2 - lc, xm + wf / 2, -w / 2)
            )
        return (etch - fingers).merged()

    def _turn_etch(self, dbu) -> pya.Region:
        """Etch of a right-hand U-turn centred at the origin (rows at y = ±turn_radius, x ≥ 0)."""
        import numpy as np  # pylint: disable=import-outside-toplevel

        wm, profile, th_k = self._turn_width()
        r_t, s, wf, sf, lf = self.turn_radius, self.spine_gap, self.finger_width, self.finger_gap, self.finger_length
        thetas = np.linspace(-math.pi / 2, math.pi / 2, int(self.arc_points))
        w_th = profile(thetas, wm)
        r_in, r_out = r_t - 0.5 * w_th, r_t + 0.5 * w_th

        def poly(radii_a, radii_b):
            pts = [pya.DPoint(r * math.cos(t), r * math.sin(t)) for r, t in zip(radii_a, thetas)]
            pts += [pya.DPoint(r * math.cos(t), r * math.sin(t)) for r, t in zip(radii_b[::-1], thetas[::-1])]
            return pya.Region(pya.DPolygon(pts).to_itype(dbu))

        ring = poly(r_out + s, r_in - s)
        signal = poly(r_out, r_in)
        slots, fingers = pya.Region(), pya.Region()
        nc = self._nc()
        for k, th in enumerate(th_k):
            lc = self.loaded_finger_length if self._loaded(k % nc) else lf
            w_loc = float(profile(np.array([th]), wm)[0])
            rik, rok = r_t - 0.5 * w_loc, r_t + 0.5 * w_loc
            fingers.insert(_radial_rect(dbu, th, rok - 0.1, rok + lc, wf / 2))
            fingers.insert(_radial_rect(dbu, th, rik - lc, rik + 0.1, wf / 2))
            slots.insert(_radial_rect(dbu, th, r_t, rok + lf + s, wf / 2 + sf))
            slots.insert(_radial_rect(dbu, th, rik - lf - s, r_t, wf / 2 + sf))
        return ((ring + slots).merged() - (signal + fingers).merged()).merged()

    def _launch_etch(self, dbu) -> pya.Region:
        """Etch of a launch at the origin going −x: spine taper to (a, b), then a straight to the port."""
        w, s, a, b = self.spine_width, self.spine_gap, self.a, self.b
        lt, ls = self.launch_taper_length, self.launch_length
        out = pya.Region()
        for sgn in (1, -1):
            pts = [
                pya.DPoint(0, sgn * w / 2),
                pya.DPoint(0, sgn * (w / 2 + s)),
                pya.DPoint(-lt, sgn * (a / 2 + b)),
                pya.DPoint(-lt, sgn * a / 2),
            ]
            out.insert(pya.DPolygon(pts).to_itype(dbu))
        out += cpw_gaps(dbu, -lt - ls, -lt, a, b)
        return out.merged()

    @classmethod
    def qcc_keepout(cls, params: dict) -> list:
        """3/0 keep-out (local µm): filled boxes over each row band, each U-turn and each launch, grown by the PDK
        component margin — cheap to evaluate, unlike growing the 100 k-polygon etch itself."""
        from quantcore_circuits.layouts.others.keepout import as_cell  # pylint: disable=import-outside-toplevel

        s = as_cell(cls, params)
        m = 20.0
        ys, xl, xr = s.qcc_rows()
        half = s.spine_width / 2 + s.spine_gap + s.finger_length + m
        reach = s.turn_radius + s.spine_width * 2 + s.spine_gap + s.finger_length + m
        boxes = [pya.DBox(xl, y - half, xr, y + half) for y in ys]
        for i in range(len(ys) - 1):
            yc = (ys[i] + ys[i + 1]) / 2
            x0 = xr if i % 2 == 0 else xl - reach
            boxes.append(pya.DBox(x0, yc - reach, x0 + reach, yc + reach))
        lr = s.launch_taper_length + s.launch_length
        lw = s.a / 2 + s.b + m
        boxes.append(pya.DBox(xl - lr - m, ys[0] - lw, xl, ys[0] + lw))
        if (len(ys) - 1) % 2 == 1:
            boxes.append(pya.DBox(xl - lr - m, ys[-1] - lw, xl, ys[-1] + lw))
        else:
            boxes.append(pya.DBox(xr, ys[-1] - lw, xr + lr + m, ys[-1] + lw))
        return boxes

    def qcc_rows(self) -> tuple[list[float], float, float]:
        length = int(self.periods_per_row) * self._nc() * self.pitch
        ys = [(int(self.rows) - 1 - 2 * r) * self.turn_radius for r in range(int(self.rows))]
        return ys, -length / 2, length / 2

    def build(self):
        problem = self._check()
        if problem:
            self.raise_error_on_cell(f"KiTwpaSerpentine: {problem}")
        dbu = self.layout.dbu
        ys, xl, xr = self.qcc_rows()
        nc, p = self._nc(), self.pitch
        layer = self.get_layer("base_metal_gap_wo_grid")
        shapes = self.cell.shapes(layer)
        sc = self._supercell_etch(dbu)
        for y in ys:
            for j in range(int(self.periods_per_row)):
                shapes.insert(sc.transformed(pya.Trans(int(round((xl + j * nc * p) / dbu)), int(round(y / dbu)))))
        right = self._turn_etch(dbu)
        left = right.transformed(pya.Trans(pya.Trans.M90))
        for i in range(len(ys) - 1):
            x = xr if i % 2 == 0 else xl
            shapes.insert(
                (right if i % 2 == 0 else left).transformed(
                    pya.Trans(int(round(x / dbu)), int(round((ys[i] + ys[i + 1]) / 2 / dbu)))
                )
            )
        launch = self._launch_etch(dbu)
        reach = self.launch_taper_length + self.launch_length
        last_left = (len(ys) - 1) % 2 == 1
        shapes.insert(launch.transformed(pya.Trans(int(round(xl / dbu)), int(round(ys[0] / dbu)))))
        if last_left:
            shapes.insert(launch.transformed(pya.Trans(int(round(xl / dbu)), int(round(ys[-1] / dbu)))))
            pb, db = pya.DPoint(xl - reach, ys[-1]), pya.DVector(-1, 0)
        else:
            mirrored = launch.transformed(pya.Trans(pya.Trans.M90))
            shapes.insert(mirrored.transformed(pya.Trans(int(round(xr / dbu)), int(round(ys[-1] / dbu)))))
            pb, db = pya.DPoint(xr + reach, ys[-1]), pya.DVector(1, 0)
        box = pya.Region(self.cell.bbox_per_layer(layer))
        self.add_protection(box.sized(self.margin / dbu))
        self.add_port("a", pya.DPoint(xl - reach, ys[0]), pya.DVector(-1, 0))
        self.add_port("b", pb, db)

    @classmethod
    def qcc_ladder(
        cls,
        params: dict,
        pdk=None,
        sheet_pH_sq: float | None = None,
        thickness_um: float | None = None,
        eps_r: float | None = None,
    ) -> dict:
        """Electrical ladder of the drawing (one cell = series L + shunt C to ground; twpa-sim ``Cell``):

        * L_cell = L'_geo·pitch (Metal's CPW formula for the bare spine) + L_s·(pitch/spine_width) (sheet squares of
          the film: the PDK's L_s, or ``sheet_pH_sq``) — the twpa-sim cell has 20 pH/□ × 1.5/0.58 × 1.04;
        * C_cell = two fingers, each a strip in its slot (CPW C' of finger_width / finger_gap × finger length) + the
          spine to ground over the pitch outside the slots; loaded cells with ``loaded_finger_length``;
        * the counts: cells per supercell, supercells per row / turn, total cells.
        """
        from quantcore_circuits.analysis.synthesis import cpw_properties  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.circuit.kinetic import sheet_inductance_pH_sq  # pylint: disable=C0415
        from quantcore_circuits.layouts.others.keepout import full_params  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.lom import estimates as est  # pylint: disable=import-outside-toplevel

        p = full_params(cls, params)
        pdk = _pdk_obj(pdk)
        eps = est.substrate_eps(pdk) if eps_r is None else float(eps_r)
        w, s, wf, sf = (_f(p[k]) for k in ("spine_width", "spine_gap", "finger_width", "finger_gap"))
        pitch, lf, llf = _f(p["pitch"]), _f(p["finger_length"]), _f(p["loaded_finger_length"])
        ls = (
            sheet_pH_sq
            if sheet_pH_sq is not None
            else (_f(p.get("sheet_inductance_pH_sq")) or sheet_inductance_pH_sq(pdk))
        )
        q = cpw_properties(7.0, w, s, pdk.name, kinetic=False)
        l_geo = q["Z0_ohm"] / q["vp_m_s"] * pitch * 1e-6 * 1e12  # pH per cell
        l_k = ls * (pitch / w)
        c_f = est.cpw_c_per_um(wf, sf, eps)
        c_sp = est.cpw_c_per_um(w, s, eps) * max(pitch - wf - 2 * sf, 0.0)
        nc = int(p["unloaded_cells"]) + int(p["loaded_cells"])
        rows, per, turns = int(p["rows"]), int(p["periods_per_row"]), int(p["turn_periods"])
        n_total = rows * per * nc + (rows - 1) * turns * nc
        return {
            "L_cell_pH": l_geo + l_k,
            "L_geo_pH": l_geo,
            "L_k_pH": l_k,
            "alpha_k": l_k / (l_geo + l_k),
            "sheet_pH_sq": ls,
            "C_cell_fF": 2 * c_f * lf + c_sp,
            "C_loaded_fF": 2 * c_f * llf + c_sp,
            "Z_cell_ohm": math.sqrt((l_geo + l_k) * 1e-12 / ((2 * c_f * lf + c_sp) * 1e-15)),
            "cells_per_supercell": nc,
            "unloaded_cells": int(p["unloaded_cells"]),
            "loaded_cells": int(p["loaded_cells"]),
            "supercells": rows * per + (rows - 1) * turns,
            "cells": n_total,
            "length_um": n_total * pitch,
            "eps_r": eps,
        }

    @classmethod
    def qcc_lom(cls, name: str, inst, pdk):
        """One conductor between ``a`` and ``b`` (a wire when both meet pads); the ladder values ride in the notes."""
        from quantcore_circuits.lom.fragment import Fragment, Line, cell_params  # pylint: disable=C0415

        p = cell_params(inst)
        lad = cls.qcc_ladder(p, pdk)
        frag = Fragment(nodes={"line": {"island": f"{name}.line"}}, port_nodes={"a": "line", "b": "line"})
        frag.lines.append(
            Line(name, "line", ("a", "b"), lad["length_um"], _f(p["spine_width"]), _f(p["spine_gap"]), ("open", "open"))
        )
        frag.notes.append(
            f"{name}: KI-TWPA ladder of {lad['cells']} cells, L {lad['L_cell_pH']:.3g} pH/cell (kinetic "
            f"{lad['alpha_k']:.1%} at {lad['sheet_pH_sq']:.3g} pH/□), C {lad['C_cell_fF']:.3g} fF/cell, Z ≈ "
            f"{lad['Z_cell_ohm']:.0f} Ω (analysis.amplifiers for dispersion and gain)"
        )
        return frag
