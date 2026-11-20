"""Flip-chip and TSV cells with ports on both faces.

* :class:`CpwTsvTransition`: a CPW that goes through one chip, from a pad on one face to a pad on the other face of
  the same chip (``1t1`` ↔ ``1b1`` or ``2b1`` ↔ ``2t1``), through signal TSVs, with a row of ground TSVs on each side.
  The layout follows QPDK's ``tsv_transition_double_sided`` (gdsfactory/quantum-rf-pdk, ``qpdk/cells/tsv.py``, MIT;
  read, not imported) and is drawn from KQC parts: ``WaveguideCoplanar`` pads, ``WaveguideCoplanarTaper`` tapers and
  KQC ``Tsv`` vias (``TsvEllipse`` by default).
* :class:`QcFlipChipConnectorRf`: KQC's ``FlipChipConnectorRf`` (the bump transition between the two chips) with a
  bump size, an under-bump metal size, a choice of ground bumps and named ports ``a`` / ``b``. It subclasses KQC's
  cell and only changes which bump it inserts.

Both record the face of each port (``Port.face``): a route that starts or ends on one of them is drawn on that face
(``assembly.plan``), and the LOM treats each cell as one conductor between its two ports.
"""

from __future__ import annotations

import re

from kqcircuits.defaults import default_faces
from kqcircuits.elements.element import Element
from kqcircuits.elements.finger_capacitor_square import FingerCapacitorSquare, eval_a2, eval_b2
from kqcircuits.elements.flip_chip_connectors.flip_chip_connector import FlipChipConnector
from kqcircuits.elements.flip_chip_connectors.flip_chip_connector_rf import FlipChipConnectorRf
from kqcircuits.elements.tsvs.tsv import Tsv
from kqcircuits.elements.tsvs.tsv_ellipse import TsvEllipse
from kqcircuits.elements.waveguide_coplanar import WaveguideCoplanar
from kqcircuits.elements.waveguide_coplanar_taper import WaveguideCoplanarTaper
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, add_parameters_from, pdt


def other_side(face: str) -> str:
    """The face on the other side of the same chip: ``1t1`` ↔ ``1b1``, ``2b1`` ↔ ``2t1`` (KQC face ids are
    ``<chip><t|b><n>``)."""
    m = re.fullmatch(r"(\d+)([tb])(\d+)", str(face))
    back = f"{m[1]}{'b' if m[2] == 't' else 't'}{m[3]}" if m else None
    if back is None or back not in default_faces or face not in default_faces:
        raise ValueError(f"face {face!r} has no other side in KQC's faces {sorted(default_faces)}")
    return back


def _lom_through(name: str, length: float, a: float, b: float):
    """One conductor between ports ``a`` and ``b``: a pass-through CPW section (``Line.through``) of ``length`` µm,
    so a line or resonator that passes the cell stays one line."""
    from quantcore_circuits.lom.fragment import Fragment, Line  # pylint: disable=import-outside-toplevel

    frag = Fragment(nodes={"line": {"island": f"{name}.line"}}, port_nodes={"a": "line", "b": "line"})
    frag.lines.append(Line(name, "line", ("a", "b"), length, a, b, ("short", "short"), through=True))
    return frag


@add_parameters_from(FingerCapacitorSquare, "a2", "b2")
@add_parameters_from(Tsv, "tsv_margin", tsv_type="Tsv Ellipse", tsv_diameter=10)
@add_parameters_from(TsvEllipse, tsv_elliptical_width=20)
class CpwTsvTransition(Element):
    """CPW transition through one chip: a pad on each face, joined by signal TSVs, with ground TSVs around them.

    QPDK ``tsv_transition_double_sided`` drawn from KQC parts. The front face is ``face_ids[0]`` (the chip's front
    face unless the instance sets ``face_ids``); the back face is the other side of the same chip (``1t1`` →
    ``1b1``, ``2b1`` → ``2t1``). Both pads (``pad_width`` × ``pad_length``, gap ``pad_gap``) are centred on the
    origin along x; the front pad opens towards −x and is closed by a ``pad_gap``
    etch at +x, the back pad the other way round. A linear taper of ``taper_length`` leads from the front CPW
    (``a``/``b``) into the front pad, one of ``taper_length_back`` from the back pad to the back CPW (``a2``/``b2``,
    -1 = ``a``/``b``). Port ``a`` (front face) is at the start of the front taper and faces −x, port ``b`` (back face)
    at the end of the back taper and faces +x; with a taper length of 0 the port is the pad edge and has the pad's
    width and gap. ``n_signal_vias`` TSVs at ``signal_via_pitch`` (across the line) sit in the pads at the origin,
    ``n_ground_vias_per_side`` TSVs at ``ground_via_pitch`` (along the line) on each side, ``ground_via_distance``
    from the pad gap's outer edge. The vias are KQC ``Tsv`` cells of ``tsv_type`` on both faces (``tsv_diameter``
    across the line, ``tsv_elliptical_width`` along it for ``Tsv Ellipse``; ``tsv_margin`` is KQC's ground-grid
    avoidance around each via).

    LOM: one conductor between ``a`` and ``b`` (a pass-through section of the tapers + pad length; the via height
    and the width steps are not modelled).
    """

    taper_length = Param(pdt.TypeDouble, "Front taper length (0: port at the pad)", 100, unit="μm")
    taper_length_back = Param(pdt.TypeDouble, "Back taper length (0: port at the pad)", 100, unit="μm")
    pad_width = Param(pdt.TypeDouble, "Pad centre-conductor width", 40, unit="μm")
    pad_gap = Param(pdt.TypeDouble, "Pad gap to ground (also closes the pad)", 24, unit="μm")
    pad_length = Param(pdt.TypeDouble, "Pad length along the line", 30, unit="μm")
    n_signal_vias = Param(pdt.TypeInt, "Signal TSVs in the pad", 2)
    signal_via_pitch = Param(pdt.TypeDouble, "Signal TSV pitch across the line", 20, unit="μm")
    n_ground_vias_per_side = Param(pdt.TypeInt, "Ground TSVs on each side of the pad", 4)
    ground_via_pitch = Param(pdt.TypeDouble, "Ground TSV pitch along the line", 30, unit="μm")
    ground_via_distance = Param(pdt.TypeDouble, "Ground TSV centres from the pad gap's outer edge", 15, unit="μm")

    qcc_category = "flip_chip"

    @classmethod
    def faces(cls, params: dict) -> tuple[str, str]:
        """(front, back) faces of an instance with ``params``."""
        face_ids = list(params.get("face_ids") or cls.face_ids)
        return str(face_ids[0]), other_side(face_ids[0])

    @classmethod
    def qcc_port_faces(cls, params: dict) -> dict:
        front, back = cls.faces(params)
        return {"a": front, "b": back}

    @classmethod
    def qcc_port_widths(cls, params: dict) -> dict:
        """``a``: the front CPW (``a``/``b``), ``b``: the back CPW (``a2``/``b2``); the pad's width and gap where a
        taper length is 0."""
        a, b = float(params["a"]), float(params["b"])
        a2, b2 = float(params.get("a2", -1)), float(params.get("b2", -1))
        pad = (float(params["pad_width"]), float(params["pad_gap"]))
        return {
            "a": (a, b) if float(params["taper_length"]) > 0 else pad,
            "b": (a if a2 < 0 else a2, b if b2 < 0 else b2) if float(params["taper_length_back"]) > 0 else pad,
        }

    @classmethod
    def qcc_keepout(cls, params: dict) -> list:
        """3/0 keep-out (local µm): the box around both pads, both tapers and every via, grown by the PDK component
        margin (as the bounding-box rule of other components; the ground vias lie outside the pads' etch)."""
        from quantcore_circuits.layouts.others.keepout import full_params  # pylint: disable=C0415
        from quantcore_circuits.pdk import KeepoutRule  # pylint: disable=import-outside-toplevel

        p = full_params(cls, params)
        length, w, g = float(p["pad_length"]), float(p["pad_width"]), float(p["pad_gap"])
        r = float(p["tsv_diameter"]) / 2
        along = float(p["tsv_elliptical_width"]) / 2 if p["tsv_type"] == "Tsv Ellipse" else r
        x_via = (int(p["n_ground_vias_per_side"]) - 1) / 2 * float(p["ground_via_pitch"]) + along
        y_via = w / 2 + g + float(p["ground_via_distance"]) + r if int(p["n_ground_vias_per_side"]) else 0.0
        x0 = max(length / 2 + max(float(p["taper_length"]), 0.0), length / 2 + g, x_via)
        x1 = max(length / 2 + max(float(p["taper_length_back"]), 0.0), length / 2 + g, x_via)
        widths = cls.qcc_port_widths(p).values()
        y = max(w / 2 + g, y_via, *(a / 2 + b for a, b in widths))
        rule = KeepoutRule()
        grow = rule.component_margin - rule.own_grow  # keepout_region adds own_grow to every hook shape
        return [pya.DBox(-x0 - grow, -y - grow, x1 + grow, y + grow)]

    @classmethod
    def qcc_lom(cls, name: str, inst, pdk):  # noqa: ARG003
        """One conductor between ``a`` and ``b``: a pass-through section of the in-plane length (tapers + pad)."""
        from quantcore_circuits.lom.fragment import cell_params  # pylint: disable=import-outside-toplevel

        p = cell_params(inst)
        length = float(p["taper_length"]) + float(p["pad_length"]) + float(p["taper_length_back"])
        return _lom_through(name, length, float(p["a"]), float(p["b"]))

    def build(self):
        try:
            front, back = self.faces({"face_ids": self.face_ids})
        except ValueError as e:
            self.raise_error_on_cell(str(e))
        length, w, g = self.pad_length, self.pad_width, self.pad_gap
        tl, tb = max(self.taper_length, 0.0), max(self.taper_length_back, 0.0)
        span = (self.n_signal_vias - 1) * self.signal_via_pitch + self.tsv_diameter
        along = self.tsv_elliptical_width if self.tsv_type == "Tsv Ellipse" else self.tsv_diameter
        if span > w or along > length:
            self.raise_error_on_cell(
                f"{self.n_signal_vias} signal TSV(s) of {self.tsv_diameter} × {along} µm at pitch "
                f"{self.signal_via_pitch} µm do not fit in a {length} × {w} µm pad"
            )
        if self.n_ground_vias_per_side and self.ground_via_distance < self.tsv_diameter / 2:
            self.raise_error_on_cell(f"ground_via_distance {self.ground_via_distance} µm puts the ground TSVs into "
                                     "the pad gap")

        pad = pya.DPath([pya.DPoint(-length / 2, 0), pya.DPoint(length / 2, 0)], 0)
        self.insert_cell(WaveguideCoplanar, path=pad, a=w, b=g, term1=0, term2=g, face_ids=[front, back])
        self.insert_cell(WaveguideCoplanar, path=pad, a=w, b=g, term1=g, term2=0, face_ids=[back, front])
        if tl > 0:
            self.insert_cell(WaveguideCoplanarTaper, pya.DTrans(-length / 2 - tl, 0), taper_length=tl, a=self.a,
                             b=self.b, a2=w, b2=g, m2=self.margin, face_ids=[front, back])
        if tb > 0:
            self.insert_cell(WaveguideCoplanarTaper, pya.DTrans(length / 2, 0), taper_length=tb, a=w, b=g,
                             a2=eval_a2(self), b2=eval_b2(self), m2=self.margin, face_ids=[back, front])

        via = self.add_element(Tsv, face_ids=[front, back])
        for k in range(self.n_signal_vias):
            self.insert_cell(via, pya.DTrans(0, (k - (self.n_signal_vias - 1) / 2) * self.signal_via_pitch))
        y = w / 2 + g + self.ground_via_distance
        for k in range(self.n_ground_vias_per_side):
            x = (k - (self.n_ground_vias_per_side - 1) / 2) * self.ground_via_pitch
            for sy in (1, -1):
                self.insert_cell(via, pya.DTrans(x, sy * y))

        self.refpoints["signal_via"] = pya.DPoint(0, 0)
        self.add_port("a", pya.DPoint(-length / 2 - tl, 0), pya.DVector(-1, 0), front)
        self.add_port("b", pya.DPoint(length / 2 + tb, 0), pya.DVector(1, 0), back)


@add_parameters_from(FlipChipConnector, "bump_diameter", "ubm_diameter")
class QcFlipChipConnectorRf(FlipChipConnectorRf):
    """KQC's flip-chip bump transition (FlipChipConnectorRf) with a bump size and named ports a and b.

    The CPW transition between the two chips through an indium bump, drawn by KQC's cell. ``bump_diameter`` and
    ``ubm_diameter`` size the signal bump and its under-bump metal (KQC's cell always draws its default 25 µm bump
    on a 40 µm UBM), ``n_ground_bumps`` is 4 (KQC's ground bumps around the transition) or 0 (none, as QPDK's
    ``bump_transition``). Port ``a`` is the CPW end on ``face_ids[0]`` (CPW
    ``a``/``b``), port ``b`` the end on ``face_ids[1]`` (``a2``/``b2``, rotated by ``output_rotation``); both are
    drawn as port texts, so the netlist check sees them.

    LOM: one conductor between ``a`` and ``b`` (a pass-through section; the bump is not modelled).
    """

    n_ground_bumps = Param(pdt.TypeInt, "Ground bumps around the transition (4: KQC's, 0: none)", 4,
                           choices=[["4", 4], ["0", 0]])

    qcc_category = "flip_chip"

    @classmethod
    def qcc_port_faces(cls, params: dict) -> dict:
        face_ids = list(params.get("face_ids") or cls.face_ids)
        return {"a": str(face_ids[0]), "b": str(face_ids[1])}

    @classmethod
    def qcc_port_widths(cls, params: dict) -> dict:
        a, b = float(params["a"]), float(params["b"])
        a2, b2 = float(params.get("a2", -1)), float(params.get("b2", -1))
        return {"a": (a, b), "b": (a if a2 < 0 else a2, b if b2 < 0 else b2)}

    def build(self):
        if self.n_ground_bumps not in (0, 4):
            self.raise_error_on_cell(f"n_ground_bumps must be 4 or 0, not {self.n_ground_bumps}")
        super().build()
        for name, face in (("a", 0), ("b", 1)):
            pos = self.refpoints[f"{self.face_ids[face]}_port"]
            corner = self.refpoints[f"{self.face_ids[face]}_port_corner"]
            self.add_port(name, pos, corner - pos, face)

    def _get_bump(self):
        return self.add_element(
            FlipChipConnector,
            face_ids=self.face_ids,
            bump_type=self.bump_type,
            bump_diameter=self.bump_diameter,
            ubm_diameter=self.ubm_diameter,
        )

    def _insert_ground_bumps(self, bump):
        if self.n_ground_bumps:
            super()._insert_ground_bumps(bump)
