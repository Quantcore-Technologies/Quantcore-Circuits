"""Turn a drawn shape into a Quantcore component: polygons + named pins + a junction location.

A freeform component is described by three things:

* **polygons**: the metal of the component (island, coupler claws, pin tails) as ``pya.DPolygon`` in µm, in the
  component's own frame; drawn in Python, or read from a cell of a saved ``.oas`` / ``.gds`` file
  (:func:`read_polygons`),
* **pins**: where the component connects, each a position, a direction pointing OUT of the component and the CPW it
  continues as (``a`` centre width, ``b`` gap): :class:`Pin`,
* **a junction line** (optional): a segment from the island side to the ground side across the gap where the
  Quantcore trilayer junction is drawn.

:class:`FreeformComponent` turns them into a layout cell. It etches ``clearance`` around all polygons (a negative mask:
the cell draws what is removed, on ``base_metal_gap_wo_grid``), keeps a CPW gap ``b`` along each pin's tail, registers
the ports and places the trilayer junction (``place_trilayer``, the PDK junction rule). Subclass it and override
``polygons()``, ``pins()`` and ``junction_line()`` (they may read the cell parameters through ``self``), or call
:func:`component_from_polygons` for a fixed shape (for example polygons drawn in KLayout).

Not part of the library (example code): copy it next to your component, or into ``src/quantcore_circuits/layouts/``
if you want it to be a library module. Guide: docs/library/custom-components/spiralmon.md.
"""

from __future__ import annotations

import json
import math
import types
from dataclasses import dataclass
from pathlib import Path

from kqcircuits.elements.element import Element
from kqcircuits.pya_resolver import pya
from kqcircuits.util.parameters import Param, pdt


@dataclass(frozen=True)
class Pin:
    """A connection point of a freeform component.

    ``x, y``: where the CPW of the pin starts (µm, component frame), ``angle``: the direction pointing out of the
    component (degrees, 0 = +x), ``a`` / ``b``: centre width / gap of the CPW that continues from the pin (``None``:
    the element's ``a`` / ``b``), ``tail``: the length of the tail polygon that ends at the pin (µm). Along the tail
    the helper keeps a CPW gap ``b`` instead of the wide clearance, so a route continues cleanly.
    """

    name: str
    x: float
    y: float
    angle: float
    a: float | None = None
    b: float | None = None
    tail: float = 0.0

    def direction(self) -> tuple[float, float]:
        return math.cos(math.radians(self.angle)), math.sin(math.radians(self.angle))


def _json_dict(text) -> dict:
    if isinstance(text, dict):
        return dict(text)
    value = json.loads(str(text or "").strip() or "{}")
    if not isinstance(value, dict):
        raise ValueError(f"junction_params must be a dict, got {value!r}")
    return value


def read_polygons(path, layer: tuple[int, int] = (1, 0), cell: str | None = None) -> list[pya.DPolygon]:
    """The polygons of one layer of a saved ``.oas`` / ``.gds`` file, in µm, merged (touching shapes become one
    polygon, holes are kept). ``cell``: the cell name (``None``: the top cell); sub-cells are flattened in. Paths,
    boxes and polygons all count; text and other layers are ignored.
    """
    layout = pya.Layout()
    layout.read(str(path))
    top = layout.cell(cell) if cell else layout.top_cell()
    if top is None:
        raise ValueError(f"{path}: no cell {cell!r}" if cell else f"{path}: no top cell")
    index = layout.find_layer(layer[0], layer[1])
    if index is None:
        have = sorted(f"{li.layer}/{li.datatype}" for li in layout.layer_infos())
        raise ValueError(f"{path}: no layer {layer[0]}/{layer[1]} (the file has {have})")
    region = pya.Region(top.begin_shapes_rec(index)).merged()
    return [p.to_dtype(layout.dbu) for p in region.each()]


def _region(polygons, dbu: float) -> pya.Region:
    return pya.Region([p.to_itype(dbu) for p in polygons]).merged()


class FreeformComponent(Element):
    """A component made of drawn polygons: islands / claws / tails (metal), pins and one junction line.

    Override :meth:`polygons`, :meth:`pins`, :meth:`junction_line`. Add a LOM model with ``qcc_lom`` (see
    ``custom_qubit.ForkTransmon`` for one).
    """

    qcc_category = "qubit"
    qcc_junction = True

    clearance = Param(pdt.TypeDouble, "Etched clearance around the polygons", 25, unit="μm")
    junction_type = Param(
        pdt.TypeString,
        "Junction across the junction line",
        "Quantcore Junction",
        choices=["No Squid", "Quantcore Junction", "Quantcore Squid", "Trilayer Junction", "Trilayer Squid", "Sim"],
    )
    junction_params = Param(pdt.TypeString, "Trilayer junction cell parameters (JSON dict, e.g. lj_nH)", "{}")

    # ---- what a subclass describes ----------------------------------------------------------------------------
    def polygons(self) -> list[pya.DPolygon]:
        """The metal polygons (µm). Required."""
        raise NotImplementedError

    def pins(self) -> list[Pin]:
        """The pins (µm, outward directions). Default: none."""
        return []

    def junction_line(self):
        """``((xa, ya), (xb, yb))``: from the island side to the ground side of the junction gap, or ``None``."""
        return None

    # ---- the helper ------------------------------------------------------------------------------------------------
    @classmethod
    def qcc_params(cls, params: dict) -> dict:
        """design.json params -> PCell params: ``junction_params`` dict -> JSON; unknown names raise."""
        params = dict(params)
        unknown = sorted(set(params) - set(cls.get_schema()))
        if unknown:
            raise ValueError(f"{cls.__name__}: unknown parameter(s) {unknown}")
        if isinstance(params.get("junction_params"), dict):
            params["junction_params"] = json.dumps(params["junction_params"], sort_keys=True)
        elif isinstance(params.get("junction_params"), str):
            _json_dict(params["junction_params"])
        return params

    def build(self):
        dbu = self.layout.dbu
        metal = _region(self.polygons(), dbu)
        if metal.is_empty():
            self.raise_error_on_cell(f"{type(self).__name__}: polygons() is empty")
        clear = metal.sized(round(self.clearance / dbu), 2)
        corridors, keep = pya.Region(), pya.Region()
        pins = self.pins()
        for pin in pins:
            a = pin.a if pin.a is not None else self.a
            b = pin.b if pin.b is not None else self.b
            if pin.tail > 0:
                trans = pya.DCplxTrans(1, pin.angle, False, pin.x, pin.y)  # local x = outward along the pin
                for sign in (1, -1):  # ground strips beside the gap b: they cut the wide clearance down to b
                    y0, y1 = sorted((sign * (a / 2 + b), sign * (a / 2 + self.clearance + 1)))
                    keep += pya.Region((trans * pya.DPolygon(pya.DBox(-pin.tail, y0, 0, y1))).to_itype(dbu))
                # beyond the pin the route draws its own gaps: no wide clearance in front of the tip
                reach = self.clearance + 1
                keep += pya.Region(
                    (trans * pya.DPolygon(pya.DBox(0, -(a / 2 + reach), reach, a / 2 + reach))).to_itype(dbu)
                )
                corridors += pya.Region(
                    (trans * pya.DPolygon(pya.DBox(-pin.tail, -a / 2 - b, 0, a / 2 + b))).to_itype(dbu)
                )
        etch = ((clear - keep) + corridors) - metal
        self.cell.shapes(self.get_layer("base_metal_gap_wo_grid")).insert(etch)
        self.add_protection(pya.Region(etch.bbox()).sized(round(self.margin / dbu)))
        for pin in pins:
            ux, uy = pin.direction()
            self.add_port(pin.name, pya.DPoint(pin.x, pin.y), pya.DVector(ux, uy))

        line = self.junction_line()
        if line is not None:
            (xa, ya), (xb, yb) = line
            a_pt, b_pt = pya.DPoint(xa, ya), pya.DPoint(xb, yb)
            self.refpoints["port_squid_a"], self.refpoints["port_squid_b"] = a_pt, b_pt
            jtype = str(self.junction_type or "No Squid")
            if jtype not in ("No Squid", "Sim"):
                from quantcore_circuits.layouts.junctions.trilayer import place_trilayer

                gaps = pya.Region(self.cell.begin_shapes_rec(self.get_layer("base_metal_gap_wo_grid")))
                try:
                    place_trilayer(self, jtype, gaps, a_pt, b_pt, self.junction_params)
                except ValueError as e:
                    self.raise_error_on_cell(f"{type(self).__name__}: {e}")


def register(*classes) -> None:
    """Register component classes that live outside ``src/quantcore_circuits/layouts/`` into the KQC library, so
    ``Designer.add`` can create them (classes in the package are registered automatically)."""
    import quantcore_circuits.layouts as layouts

    layouts.register_pcell_classes(list(classes))


def component_from_polygons(
    name: str,
    polygons,
    pins=(),
    junction_line=None,
    category: str = "qubit",
    module: str | None = None,
    **defaults,
) -> type[FreeformComponent]:
    """A ready component class for a fixed shape, for example polygons drawn in KLayout.

    ``polygons``: ``pya.DPolygon`` list (:func:`read_polygons`); ``pins``: :class:`Pin` list; ``junction_line``:
    ``((xa, ya), (xb, yb))``; ``defaults``: new defaults for the parameters (``clearance=30``). The class is registered,
    so ``Designer.add("X", "<module>.<name>")`` works when ``module`` is the importable module that holds it (set
    ``MyShape = component_from_polygons("MyShape", ...)`` at module level and pass ``module=__name__``).
    """
    fixed_polygons = [p.dup() for p in polygons]
    fixed_pins = list(pins)
    fixed_line = junction_line
    namespace = {
        "qcc_category": category,
        "polygons": lambda self: [p.dup() for p in fixed_polygons],
        "pins": lambda self: list(fixed_pins),
        "junction_line": lambda self: fixed_line,
        "__doc__": f"Freeform component {name}: {len(fixed_polygons)} polygon(s), {len(fixed_pins)} pin(s).",
        "__module__": module or "__main__",
    }
    for key, value in defaults.items():
        if key not in FreeformComponent.get_schema():
            raise ValueError(f"{name}: unknown parameter {key!r}")
        namespace[key] = Param(
            pdt.TypeString if isinstance(value, str) else pdt.TypeDouble,
            FreeformComponent.get_schema()[key].description,
            value,
        )
    cls = types.new_class(name, (FreeformComponent,), {}, lambda ns: ns.update(namespace))
    register(cls)
    return cls


def polygons_to_oas(polygons_by_layer: dict[tuple[int, int], list[pya.DPolygon]], path, cell: str = "DRAWN") -> Path:
    """Write polygons to an ``.oas`` / ``.gds`` file (one cell, one layer per key): a stand-in for a shape someone
    drew in KLayout, and the way to save a Python-made shape for a colleague."""
    layout = pya.Layout()
    layout.dbu = 0.001
    top = layout.create_cell(cell)
    for (layer, datatype), polys in polygons_by_layer.items():
        index = layout.layer(layer, datatype)
        for poly in polys:
            top.shapes(index).insert(poly)
    layout.write(str(path))
    return Path(path)
