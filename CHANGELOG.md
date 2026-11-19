# Changelog

All notable changes to quantcore-circuits are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses `0.MINOR.PATCH` version numbers.

## [Unreleased]

## [0.3.0] - 2026-11-19

First public release, under GPL-3.0-or-later.

### Added

- **Design file and Python API.** `design.json` (a pydantic schema with canonical hashing) carries a chip through every
  step. The `Designer` class builds it from code, live in KLayout through KLive, and a design can be saved back as a
  Python script.
- **Component library.** Quantcore components built as KQCircuits elements with pins (qubits, bond pads, junctions,
  chips and wafers), next to the KQCircuits and Quantum Metal components, with a generated reference page per
  component. Custom components (a custom qubit, a spiralmon, a spiral capacitor, a tunable resonator) are documented
  as examples.
- **PDK and fab export.** The `quantcore_nb_sapphire_v1` process (Nb on sapphire, 650 µm, εr 10.25; a silicon variant
  is kept as `quantcore_nb_si_v1`) with its negative-mask fab layer map, die frame, 100 µm pad-edge rule, keep-outs,
  cheese and corner rounding. `qcc mask` writes the fab layers; wafer assembly of dies is documented.
- **Routing and checks.** A router with Manhattan auto-routing, fixed-length meanders and hanger couplers, a
  connectivity DRC (dangling ports, overlaps, crossings, opens at ports, die-frame keep-outs) and a netlist check of
  declared against extracted connectivity.
- **Lumped-circuit model (LOM).** Every component carries a lumped model; the layout becomes `circuit.json`. Four
  estimators (Quantum Metal LOM, QuCat, SQcircuit, scqubits), QuTiP Hamiltonians (levels, readout, flux curves,
  Purcell) and a consensus against the targets. LOM-first synthesis (`qcc synth`) for an Xmon with a λ/4 readout on one
  feedline.
- **Simulation export.** Sim groups cut a chip into boxes or use the whole chip. Jobs are exported for Ansys HFSS and
  Q3D (`q3d_cmatrix`, `hfss_eigenmode`, `eigenmode_epr`, driven), driven by AEDT 2024 R1 or newer through KQCircuits'
  scripts and PyAEDT (`qcc hfss`, `qcc sim`). Elmer and Palace input files are written; solving with them is a future
  goal.
- **Results and feedback.** Result parsers (C-matrices in Maxwell form), a SQLite results store, EPR from the lumped
  junctions, power-law surrogates anchored on FEM points, bounded least-squares proposals, design revisions and the
  feedback loop (`qcc analyse --feedback`).
- **Runner.** A filesystem job queue and runner for a lab server (`qcc sim submit`, `qcc runner serve`); covered by unit
  tests only.
- **KLayout plugin.** A Salt package: Connect, Route handles and Move/Snap tools, a panel with the component palette,
  LOM netlist and DRC, a Flow strip (check, LOM, simulate, results, tune, fab), undo and redo, rotation snapping,
  a simulation-group overlay and a command server. Optional Live PCells.
- **Dashboard.** A live dashboard (`qcc review`, `qcc dashboard`) that shows the steps, goal, plots, circuit,
  Hamiltonian, jobs and screenshots of a run.
- **`qcc` command line.** `selftest`, `build`, `watch`, `components`, `synth`, `mask`, `review`, `dashboard`,
  `analyse`, and the groups `sim`, `results`, `runner`, `design`, `hfss` and `circuit`.
- **Examples and docs.** Five tutorial notebooks (quickstart, a 12-qubit chip, an IBM bowtie, the surface-17 chip and a
  two-qubit feedback loop), 68 design notebooks that rebuild published chips (Qiskit Metal, KQCircuits, qpdk,
  SQDMetal, SQuADDS, IBM, Google, amplifiers and community designs), and a documentation site (Sphinx + MyST).
- **Packaging and install.** A PyPI package with the extras `analysis`, `sim`, `notebook`, `all` and `dev`; an
  offline wheelhouse builder (`scripts/build_wheelhouse.py`) with install scripts for a PC without internet
  (`scripts/install_sim_pc.ps1`, `.sh`).

### Known limits

- No converged AEDT run has been done yet; the FEM runs so far used fast settings.
- Palace, Elmer and Sonnet were never solved; only their input files are written.
- The flip-chip two-face FEM export and Q3D nets above 8000 points are not built.
- The full status, with evidence, is in the documentation (Overview, Status).

[Unreleased]: https://github.com/Quantcore-Technologies/Quantcore-Circuits/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/Quantcore-Technologies/Quantcore-Circuits/releases/tag/v0.3.0
