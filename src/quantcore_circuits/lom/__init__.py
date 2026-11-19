"""Layout ↔ LOM: component lumped models, the layout → circuit builder, LOM simulation and LOM → layout synthesis.

* :mod:`.fragment` — a component's LOM model (nodes, elements, port → node map) and the registry
* :mod:`.kqc_models` — LOM models for stock KQC cells (Swissmon), registered from outside their classes
* :mod:`.calibration` — knob → element value per component and PDK (no FEM needed for a first LOM)
* :mod:`.builder` — compose fragments along routes/snaps into a ``circuit.json`` (:func:`lom_from_design`)
* :mod:`.simulate` — any circuit → QuCat network → normal modes, κ, QuTiP Hamiltonian
* :mod:`.synthesize` — targets / circuit → component knobs → a laid-out design (LOM → layout)
"""

from quantcore_circuits.lom import kqc_models  # noqa: F401  (registers LOM models for stock KQC cells)
from quantcore_circuits.lom.builder import LomBuild, lom_from_design
from quantcore_circuits.lom.fragment import Element, Fragment, register_lom

__all__ = ["Element", "Fragment", "LomBuild", "lom_from_design", "register_lom"]
