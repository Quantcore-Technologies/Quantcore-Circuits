"""quantcore-circuits: KQCircuits-native superconducting-qubit design loop.

LOM → layout (design.json → KQC chip, router-based CPWs and meanders) → live view (klive) → simulation job export
(HFSS/Q3D via KQC scripts, Elmer, Palace) → parameter extraction (LOM, EPR, scqubits, QuCat, SQcircuit, QuTiP) →
feedback into design.json.

Typical use (``import quantcore_circuits as qcc``)::

    design = qcc.load_design("examples/q1_r1_feedline.json")
    result = qcc.build(design)          # KQC chip cell + resolved plan (ports, route lengths)
    qcc.show(design)                    # write OAS and open/reload it in KLayout via klive

Heavy sub-packages (layouts/KQC, analysis stacks) are imported lazily.
"""

from importlib import import_module

__version__ = "0.3.0"

_LAZY = {
    "load_design": "quantcore_circuits.design",
    "save_design": "quantcore_circuits.design",
    "design_hash": "quantcore_circuits.design",
    "Design": "quantcore_circuits.design",
    "build": "quantcore_circuits.assembly",
    "show": "quantcore_circuits.assembly",
    "write_layout": "quantcore_circuits.assembly",
    "plan_design": "quantcore_circuits.assembly",
    "get_pdk": "quantcore_circuits.pdk",
    "Designer": "quantcore_circuits.designer",
    "lom_from_design": "quantcore_circuits.lom",
}
# submodules reachable as attributes without importing them up front (qcc.review.connect(...), qcc.lom, ...)
_SUBMODULES = {
    "review",
    "lom",
    "loop",
    "plots",
    "designer",
    "codesign",
    "circuit",
    "track",
    "cards",
    "live",
    "sim_tools",
}


def __getattr__(name):
    if name in _LAZY:
        return getattr(import_module(_LAZY[name]), name)
    if name in _SUBMODULES:
        return import_module(f"quantcore_circuits.{name}")
    raise AttributeError(f"module 'quantcore_circuits' has no attribute {name!r}")


__all__ = sorted(_LAZY) + ["__version__"]
