"""Circuit IR (``circuit.json``), extraction bridges, estimator adapters, consensus and Hamiltonian models (M8–M10).

* :mod:`.schema` — pydantic ``circuit.json`` with topology validation, ``to_networkx``
* :mod:`.derive` — default circuit for a sim group from the design
* :mod:`.bridges` — C-matrix → branches, λ/4 → LC, Rn ↔ Ic ↔ Lj, SQUID EJ(Φ)
* :mod:`.fill` — fill a circuit from job results (design and extracted values side by side)
* :mod:`.adapters` — Metal LOM, QuCat, SQcircuit, scqubits: ``solve(filled) -> ParamSet``
* :mod:`.consensus` — per-parameter estimator table, spread, choice, residual to target
* :mod:`.hamiltonian` — QuTiP Hamiltonian, dressed levels, simulated readout (χ), flux curve, Purcell T1
"""

from quantcore_circuits.circuit.schema import CircuitModel, load_circuit, save_circuit

__all__ = ["CircuitModel", "load_circuit", "save_circuit"]
