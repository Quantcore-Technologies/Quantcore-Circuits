"""Quantum Metal components as Quantcore/KQC cells: ``cell: "metal:<Class>"``.

>>> d.add("Q1", "metal:TransmonPocket", at=(2000, 2000), pad_width=455,
...       connection_pads={"a": {"loc_W": 1, "loc_H": 1}, "b": {"loc_W": -1, "loc_H": -1}})
>>> d.add("L1", "metal:LaunchpadWirebond", at=(500, 2000), rot=180)       # port "tie"

* ``params`` are the Metal options (flat, nested dicts allowed); bare numbers on length options are µm, strings
  with units (``"0.455mm"``) and Metal design variables (``"cpw_width"``) pass through. ``pos_x``/``pos_y``/
  ``orientation`` are rejected: components are built at the origin, the placement rotates them.
* Ports are the Metal pins (name, middle, outward normal, width/gap); junction lines give ``port_squid_a/b``.
* :func:`metal_cell` returns the per-class subclass (``MetalTransmonPocket``, an attribute of this module, so the
  plan's ``cell_ref`` re-imports); all of them build the one registered ``Metal Component`` PCell
  (``metal_class`` + ``options`` JSON), which is also usable directly in the KLayout GUI.
* Metal routes (``RouteStraight``, ``RouteMeander``, ...) are not cells; :data:`ROUTE_MAPPING` gives the qcc route
  to use instead.
"""

from __future__ import annotations

import sys

from kqcircuits.util.parameters import Param, pdt

from quantcore_circuits.layouts.metal.component import JUNCTION_CLASSES, MetalComponent
from quantcore_circuits.layouts.metal.geometry import (
    ROUTE_MAPPING,
    canonical_class_name,
    find_class_info,
    flat_options,
    metal_geometry,
    normalise_options,
    parse_um,
    qlibrary_index,
    template_options,
    user_options,
)

PREFIX = "metal:"
_CLASSES: dict[str, type] = {}


def class_attr_name(metal_class: str) -> str:
    """Name of the generated subclass for a Metal class (``TransmonPocket`` → ``MetalTransmonPocket``)."""
    base = metal_class.rsplit(".", 1)[-1]
    return f"Metal{base[:1].upper()}{base[1:]}"


def metal_cell(metal_class: str) -> type[MetalComponent]:
    """The (cached) MetalComponent subclass for a Metal class name (``"TransmonPocket"``) or dotted path."""
    name = canonical_class_name(metal_class)
    if name in _CLASSES:
        return _CLASSES[name]
    info = find_class_info(name)
    if info is not None and info.is_route:
        raise ValueError(f"metal:{name} is a Metal route, not a cell: use a qcc {ROUTE_MAPPING.get(name, 'route')}")
    attr = class_attr_name(name)
    namespace = {
        "__module__": __name__,
        "__qualname__": attr,
        "__doc__": f"Quantum Metal ``{name}`` as a KQC element. {info.description if info else ''}".strip(),
        "qcc_metal_class": name,
        "qcc_category": info.category if info else "other",
        "metal_class": Param(pdt.TypeString, "Quantum Metal component", name, hidden=True),
    }
    cls = type(attr, (MetalComponent,), namespace)
    _CLASSES[name] = cls
    setattr(sys.modules[__name__], attr, cls)
    return cls


def resolve(ref: str) -> type[MetalComponent]:
    """``"metal:<Class>"`` → its MetalComponent subclass."""
    if not ref.startswith(PREFIX):
        raise ValueError(f"not a Metal cell reference: {ref!r}")
    return metal_cell(ref[len(PREFIX) :])


def __getattr__(attr: str):
    """``MetalTransmonPocket`` etc. resolve on first access (the plan stores ``cell_ref`` = this module + name)."""
    if attr.startswith("Metal") and len(attr) > 5:
        base = attr[5:]
        for candidate in (base, base[:1].lower() + base[1:]):
            info = find_class_info(candidate)
            if info is not None and class_attr_name(info.name) == attr:
                return metal_cell(info.name)
    raise AttributeError(f"module {__name__!r} has no attribute {attr!r}")


__all__ = [
    "JUNCTION_CLASSES",
    "PREFIX",
    "ROUTE_MAPPING",
    "MetalComponent",
    "class_attr_name",
    "find_class_info",
    "flat_options",
    "metal_cell",
    "metal_geometry",
    "normalise_options",
    "parse_um",
    "qlibrary_index",
    "resolve",
    "template_options",
    "user_options",
]
