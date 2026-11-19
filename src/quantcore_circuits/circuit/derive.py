"""``circuit.json`` for a sim group (or the whole chip), derived from the design's components and connectivity.

Thin wrapper over :func:`quantcore_circuits.lom.builder.lom_from_design`: the sim group's selection decides which
components and routes enter the circuit (``"chip"`` = all). The same model is filled from FEM results
(:func:`~quantcore_circuits.circuit.fill.fill`) or used with its component estimates (layout → LOM only).
"""

from __future__ import annotations

from quantcore_circuits.circuit.schema import CircuitModel
from quantcore_circuits.lom.builder import DEFAULT_TOL, lom_from_design

__all__ = ["DEFAULT_TOL", "circuit_from_design"]


def circuit_from_design(source, group: str, plan=None) -> CircuitModel:
    """``plan``: the design's build plan when the caller has it already (``plan_for_lom``; planned here otherwise)."""
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools.builder import group_spec  # pylint: disable=import-outside-toplevel

    design = load_design(source)
    g = group_spec(design, group)
    from quantcore_circuits.assembly.last_good import plan_for_lom  # pylint: disable=import-outside-toplevel

    if plan is None:
        plan = plan_for_lom(design, source)  # a failed route: its last good one, with a warning
    model = lom_from_design(design, g.select, name=f"{design.name}_{group}", plan=plan).model
    return model.model_copy(update={"group": group})
