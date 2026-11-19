"""Parameter extraction: LOM (Quantum Metal), EPR (pyEPR), scqubits, QuCat, SQcircuit, QuTiP; results store.

Submodules import their (heavy) backends lazily:

* :mod:`.transmon` — conversions, scqubits spectrum, inverse problem, dressed transmon + resonator
* :mod:`.lom` — Metal LOM 2.0 from a capacitance matrix
* :mod:`.epr` — pyEPR Hamiltonian from eigenmode participation data
* :mod:`.circuits` — QuCat lumped network, SQcircuit transmon, QuTiP model
* :mod:`.synthesis` — targets → Lj, C_Σ, Cg, resonator length ("LOM → layout")
* :mod:`.results` / :mod:`.extract` — solver outputs → parameters comparable to ``design.targets``
* :mod:`.store` — SQLite results store keyed by design hash
"""
