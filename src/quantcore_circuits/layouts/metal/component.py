"""``MetalComponent``: any Quantum Metal ``qlibrary`` QComponent as a KQC element with ports.

The PCell has two parameters of its own: ``metal_class`` (qlibrary class name, e.g. ``TransmonPocket``, or a dotted
path to a user QComponent) and ``options`` (the Metal options as JSON). Building it instantiates the component in a
shared headless Metal design (see :mod:`.geometry`, cached per class + options) and renders, in µm:

* ``base_metal_gap_wo_grid`` = union(subtract shapes) − union(metal shapes); paths are buffered by width / 2 with
  flat ends, path and polygon fillets are honoured; plus ``ground_grid_avoidance`` (the drawn shapes grown by
  ``margin``), as other KQC elements do;
* metal outside the component's own pockets → ``base_metal_addition`` (metal wins over other gaps, as in Metal);
  for junction components (``jj_manhattan``, ``jj_dolan``, ``SQUID_LOOP``, ``SNAIL``, ``BridgeFreeJunction``) the
  metal goes to ``SIS_junction`` instead;
* every junction-table line → its footprint (line × width) on ``SIS_junction``, and refpoints ``port_squid_a`` (line
  start; the island side of Metal's grounded qubits) / ``port_squid_b`` (line end) for the first junction
  (``junction_<k>_a/b`` for all of them), which the simulation builder uses for the junction port;
* **trilayer junctions** (design decisions #6 / #21): ``junction_type`` = ``"Quantcore Junction"`` /
  ``"Quantcore Squid"`` (or any trilayer cell of the Junction Library, e.g. ``"Trilayer Junction"``) replaces each
  junction line's footprint by that cell (CLEARER on), its window spanning the gap the line crosses (the etched span
  along the line through its middle; window width ≤ 32 µm, 1 µm inside the gap's lateral extent on each side),
  ``origin_squid`` on the ``port_squid_b`` side and ``port_common`` on the ``port_squid_a`` side;
  ``junction_params`` (JSON dict, e.g. ``{"lj_nH": 6.7}``) is passed to the cell (sizing by the PDK junction rule).
  ``"Metal"`` (default) and ``"Sim"`` (what simulation builds set) keep Metal's footprint; ``"No Squid"`` draws no
  junction (refpoints stay);
* every Metal pin → a port named like the pin at the pin middle, facing the pin normal (outward), with the pin
  width/gap as the port's CPW ``a``/``b`` (``qcc_port_widths``);
* **pin ends**: some components' own etch continues past a pin (TransmonCross claws: the claw etcher is the claw
  buffered by ``claw_gap``, so it runs ``claw_gap`` beyond the pin over the full claw width). Metal's GDS renderer
  draws every non-subtract shape on top of the etch, so there the route's trace (which starts at the pin) fills it.
  A qcc route only etches its gaps, so the wrapper does what the renderer does: the etch beyond each pin within the
  pin width (the part touching the pin line, up to where it ends) is removed at every pin that ends one of the
  component's conductors (not at LaunchpadWirebondDriven's inward ``in`` pin). The pin then ends on metal, as every
  KQC port does: connect a route, or terminate it (``metal:OpenToGround``). ``open_pins`` (comma-separated pin
  names) keeps Metal's etch at those pins, as Metal draws a pin with no route (an open end);
* launch pads (``LaunchpadWirebond``, ``...Driven``, ``...Coupled``) → refpoints ``lumped_signal`` / ``lumped_ground``
  across the pad's side gap at the pad centre (the simulation builder's 50 Ω port, as for ``BondPad``).

The element's ``a``/``b`` set Metal's ``cpw_width``/``cpw_gap`` design variables.

In ``design.json`` and ``Designer.add`` use ``cell: "metal:<Class>"`` with the Metal options as flat ``params``
(nested dicts allowed). :func:`metal_cell` makes the per-class subclass whose ``qcc_params`` turns those options into
the two PCell parameters; :mod:`quantcore_circuits.assembly.plan` calls it before creating the cell.
"""

from __future__ import annotations

import json

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt

from quantcore_circuits.layouts.junctions.trilayer import (  # noqa: F401  (re-exported)
    MAX_WINDOW_WIDTH,
    _json_dict,
    place_trilayer,
    trilayer_on_line,
)
from quantcore_circuits.layouts.metal.geometry import (
    canonical_class_name,
    find_class_info,
    metal_geometry,
    normalise_options,
    parse_um,
    template_options,
)

JUNCTION_CLASSES = ("jj_manhattan", "jj_dolan", "SQUID_LOOP", "SNAIL", "BridgeFreeJunction")
# junction_type values: Metal's own footprint ("Metal"; "Sim" = the same, set by simulation builds), none, or a
# trilayer cell of the Junction Library placed on each junction line
JUNCTION_TYPES = (
    "Metal",
    "Quantcore Junction",
    "Quantcore Squid",
    "Trilayer Junction",
    "Trilayer Squid",
    "Sim",
    "No Squid",
)
FOOTPRINT_TYPES = ("Metal", "Sim", "")


def _launchpad_lumped(o, um):
    """LaunchpadWirebond(Driven): pad from x = -taper_height to -(taper_height + pad_height), half-width
    pad_width / 2, pocket side pad_gap beyond it (qlibrary/terminations/launchpad_wb.py)."""
    x = -(um(o["taper_height"]) + um(o["pad_height"]) / 2)
    y = um(o["pad_width"]) / 2
    return (x, y), (x, y + um(o["pad_gap"]))


def _launchpad_coupled_lumped(o, um):
    """LaunchpadWirebondCoupled: fixed pad from x = -202 to -122 µm, half-width trace_width / 2 + 35 µm, pocket
    side at trace_width / 2 + trace_gap + 87 µm (qlibrary/terminations/launchpad_wb_coupled.py)."""
    tw, tg = um(o["trace_width"]), um(o["trace_gap"])
    return (-162.0, tw / 2 + 35.0), (-162.0, tw / 2 + tg + 87.0)


# Metal launch pads → lumped-port terminals across the pad's side gap at the pad centre (refpoints ``lumped_signal``
# / ``lumped_ground``, as BondPad): the simulation builder's 50 Ω port for a pad that terminates a sim group
LUMPED_PORTS = {
    "LaunchpadWirebond": _launchpad_lumped,
    "LaunchpadWirebondDriven": _launchpad_lumped,
    "LaunchpadWirebondCoupled": _launchpad_coupled_lumped,
}


def _region(polys, dbu: float) -> pya.Region:
    region = pya.Region()
    for p in polys:
        region.insert(p.to_itype(dbu))
    region.merge()
    return region


def _pin_names(text) -> set[str]:
    return {t.strip() for t in str(text or "").replace(";", ",").split(",") if t.strip()}


def pin_end_strip(pin, length: float) -> pya.DPolygon:
    """The pin-width strip from the pin line ``length`` µm outward (along the pin normal)."""
    (mx, my), (nx, ny) = pin.middle, pin.normal
    tx, ty, h = -ny, nx, pin.width / 2
    pts = [(mx - tx * h, my - ty * h), (mx + tx * h, my + ty * h)]
    pts += [(x + nx * length, y + ny * length) for x, y in reversed(pts)]
    return pya.DPolygon([pya.DPoint(x, y) for x, y in pts])


def _trim_pin_ends(gap: pya.Region, metal: pya.Region, pins: dict, keep_open: set[str], dbu: float) -> pya.Region:
    """Remove the etch beyond each pin within the pin width (Metal: the route's trace is drawn over it).

    Only pins that end one of the component's own conductors are trimmed (its metal touches the pin line from
    behind), and only etch that does not reach the component's metal again further out: a pin facing into the
    component, such as LaunchpadWirebondDriven's ``in`` (a lumped-port terminal across the pad gap), is left as is.
    """
    if gap.is_empty() or metal.is_empty():
        return gap
    box = gap.bbox()
    corners = [(box.left, box.bottom), (box.left, box.top), (box.right, box.bottom), (box.right, box.top)]
    for name, pin in pins.items():
        if name in keep_open or pin.width <= 0:
            continue
        (mx, my), (nx, ny) = pin.middle, pin.normal
        length = max((x * dbu - mx) * nx + (y * dbu - my) * ny for x, y in corners) + 1.0
        if length <= 0:
            continue
        band = pya.Region(pin_end_strip(pin, 4 * dbu).moved(-2 * nx * dbu, -2 * ny * dbu).to_itype(dbu))
        behind = pya.Region(pin_end_strip(pin, 0.5).moved(-0.5 * nx, -0.5 * ny).to_itype(dbu))
        if (metal & behind).is_empty():
            continue  # no conductor of the component ends at this pin
        strip = pya.Region(pin_end_strip(pin, length).to_itype(dbu))
        cut = (gap & strip).interacting(band)
        far = metal & pya.Region(pin_end_strip(pin, length).moved(0.05 * nx, 0.05 * ny).to_itype(dbu))
        if cut.is_empty() or not cut.interacting(far).is_empty():
            continue
        gap = (gap - cut).merged()
    return gap


class MetalComponent(Element):
    """Any Quantum Metal ``qlibrary`` QComponent rendered as a KQC element (Metal pins → ports)."""

    metal_class = Param(
        pdt.TypeString, "Quantum Metal component (qlibrary class name or dotted path)", "TransmonPocket"
    )
    options = Param(pdt.TypeString, "Metal options as JSON (bare numbers on length options are µm)", "{}")
    open_pins = Param(
        pdt.TypeString,
        "Pins left open (comma-separated): keep Metal's etch beyond them, as drawn with no route attached",
        "",
    )
    junction_type = Param(
        pdt.TypeString,
        "Junction as fabricated: Metal footprint, or a trilayer cell placed on each junction line",
        "Metal",
        choices=list(JUNCTION_TYPES),
    )
    junction_params = Param(pdt.TypeString, "Trilayer junction cell parameters (JSON dict, e.g. lj_nH)", "{}")

    qcc_category = "other"
    qcc_metal_class: str | None = None  # set on the per-class subclasses made by metal_cell()

    # ---- design.json params → PCell params ---------------------------------------------------------------------
    @classmethod
    def qcc_params(cls, params: dict) -> dict:
        """Metal options as typed in ``design.json`` → the PCell parameters (``metal_class``, ``options`` JSON, plus
        any KQC element parameters such as ``margin``). Raises ``ValueError`` for unknown or placement options.

        Names shared by a Metal option and a KQC element parameter (``n``, ``r``, ``a``, ``b``, ``margin``, ...):

        * design.json form (no ``options``, or ``options`` as a dict): the Metal option wins (``n`` of
          ``ResonatorCoilRect`` = turns);
        * PCell form (``options`` already a JSON string, as in a plan, merged with the chip's inherited element
          parameters such as ``n`` = 64 circle points): every schema parameter stays an element parameter and the
          Metal options come from ``options`` only, so an inherited ``n`` never overrides the Metal ``n``.
        """
        params = dict(params)
        schema = cls.get_schema()
        name = params.pop("metal_class", None) or cls.qcc_metal_class
        if not name:
            raise ValueError("MetalComponent needs metal_class (or use cell 'metal:<Class>')")
        name = canonical_class_name(str(name))
        options = params.pop("options", None) or {}
        pcell_form = isinstance(options, str)
        if pcell_form:
            options = json.loads(options or "{}")
        options = dict(options)
        defaults = template_options(name)
        element = {}
        for key, value in params.items():
            if key in schema and (pcell_form or key not in defaults):
                element[key] = value
            else:
                options[key] = value
        options = normalise_options(name, options)
        jp = element.get("junction_params")
        if isinstance(jp, dict):
            element["junction_params"] = json.dumps(jp, sort_keys=True)
        elif isinstance(jp, str):
            _json_dict(jp)  # validate
        jt = element.get("junction_type")
        if jt is not None and jt not in FOOTPRINT_TYPES + ("No Squid",):
            from quantcore_circuits.layouts.junctions.trilayer import trilayer_classes  # pylint: disable=C0415

            if jt not in trilayer_classes():
                raise ValueError(
                    f"metal:{name}: junction_type {jt!r} is not a trilayer junction cell; use one of {JUNCTION_TYPES}"
                )
        return {**element, "metal_class": name, "options": json.dumps(options, sort_keys=True)}

    @classmethod
    def create(cls, layout, library=None, **parameters) -> pya.Cell:
        """Create the cell; accepts raw Metal options too (converted with :meth:`qcc_params`)."""
        schema = cls.get_schema()
        if (
            cls.qcc_metal_class
            or isinstance(parameters.get("options"), dict)
            or any(k not in schema for k in parameters)
        ):
            parameters = cls.qcc_params(parameters)
        # every subclass builds the one registered "Metal Component" PCell
        return Element.create.__func__(MetalComponent, layout, library, **parameters)

    # ---- geometry ----------------------------------------------------------------------------------------------
    @classmethod
    def qcc_geometry(cls, params: dict):
        """The cached :class:`~.geometry.MetalGeometry` for PCell parameters (or raw Metal options)."""
        schema = cls.get_schema()
        if any(k not in schema for k in params) or not isinstance(params.get("options", ""), str):
            params = {**params, **cls.qcc_params(params)}
        name = canonical_class_name(str(params.get("metal_class") or cls.qcc_metal_class or cls.metal_class))
        options = normalise_options(name, json.loads(params.get("options") or "{}"))
        a, b = float(params.get("a", 10.0)), float(params.get("b", 6.0))
        return metal_geometry(name, json.dumps(options, sort_keys=True), a, b)

    @classmethod
    def qcc_port_widths(cls, params: dict) -> dict:
        """Per-port CPW widths (a, b) = the Metal pin width/gap."""
        geom = cls.qcc_geometry(params)
        return {name: (pin.width, pin.gap) for name, pin in geom.pins.items()}

    def display_text_impl(self):
        return self.display_name or f"Metal {self.metal_class}"

    def _trilayer_junction(self, jtype: str, gap: pya.Region, a: pya.DPoint, b: pya.DPoint) -> pya.Region:
        """Place the trilayer cell ``jtype`` across the gap of the junction line a → b; returns its footprint."""
        try:
            return place_trilayer(self, jtype, gap, a, b, self.junction_params)
        except ValueError as e:
            self.raise_error_on_cell(str(e))
            return pya.Region()

    def build(self):
        try:
            params = {"metal_class": self.metal_class, "options": self.options, "a": self.a, "b": self.b}
            geom = self.qcc_geometry(params)
        except Exception as e:  # noqa: BLE001  (KLayout swallows exceptions; show it on the cell)
            self.raise_error_on_cell(f"metal:{self.metal_class}: {type(e).__name__}: {e}")
            return
        dbu = self.layout.dbu
        subtract = _region(geom.subtract, dbu)
        metal = _region(geom.metal, dbu)
        drawn = pya.Region()
        gap = _trim_pin_ends(subtract - metal, metal, geom.pins, _pin_names(self.open_pins), dbu)
        if not gap.is_empty():
            self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(gap)
            drawn += gap
        outside = metal - subtract
        info = find_class_info(geom.metal_class)
        if geom.metal_class.rsplit(".", 1)[-1] in JUNCTION_CLASSES or (info and info.category == "junction"):
            jt = str(self.junction_type or "Metal")
            if not metal.is_empty() and jt not in FOOTPRINT_TYPES and jt != "No Squid":
                # trilayer stand-in for a Metal junction tile (jj_manhattan, jj_dolan, ...): the trilayer cell spans
                # the tile's bounding box bottom (lower pad, origin_squid) → top (port_common)
                box = metal.bbox().to_dtype(dbu)
                a, b = pya.DPoint(box.center().x, box.top), pya.DPoint(box.center().x, box.bottom)
                jp = {"window_width": min(MAX_WINDOW_WIDTH, box.width()), **_json_dict(self.junction_params)}
                try:
                    drawn += place_trilayer(self, jt, pya.Region(), a, b, jp)
                except ValueError as e:
                    self.raise_error_on_cell(str(e))
                self.refpoints["port_squid_a"], self.refpoints["port_squid_b"] = a, b
            elif not metal.is_empty() and jt != "No Squid":
                self.cell.shapes(self.get_layer("SIS_junction")).insert(metal)
                drawn += metal
        elif not outside.is_empty():
            self.cell.shapes(self.get_layer("base_metal_addition")).insert(outside)
            drawn += outside
        for layer, polys in geom.layers.items():
            region = _region(polys, dbu)
            self.cell.shapes(self.get_layer(layer)).insert(region)
        jtype = str(self.junction_type or "Metal")
        for k, j in enumerate(geom.junctions):
            pts = [pya.DPoint(x, y) for x, y in j.points]
            if jtype not in FOOTPRINT_TYPES and jtype != "No Squid" and len(pts) >= 2:
                drawn += self._trilayer_junction(jtype, gap, pts[0], pts[-1])
            elif j.width > 0 and jtype != "No Squid":
                marker = pya.Region(pya.DPath(pts, j.width, 0, 0).polygon().to_itype(dbu))
                self.cell.shapes(self.get_layer("SIS_junction")).insert(marker)
                drawn += marker
            self.refpoints[f"junction_{k + 1}_a"] = pts[0]
            self.refpoints[f"junction_{k + 1}_b"] = pts[-1]
            if k == 0:
                self.refpoints["port_squid_a"] = pts[0]
                self.refpoints["port_squid_b"] = pts[-1]
        if not drawn.is_empty():
            self.add_protection(drawn.sized(self.margin / dbu).merged())
        for name, pin in geom.pins.items():
            self.add_port(name, pya.DPoint(*pin.middle), pya.DVector(*pin.normal))
        lumped = LUMPED_PORTS.get(geom.metal_class)
        if lumped:
            signal, ground = lumped(geom.options, lambda v: parse_um(v, self.a, self.b))
            self.refpoints["lumped_signal"] = pya.DPoint(*signal)
            self.refpoints["lumped_ground"] = pya.DPoint(*ground)
