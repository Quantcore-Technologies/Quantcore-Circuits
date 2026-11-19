# Quantcore circuits

Quantcore circuits is Quantcore's design loop for superconducting-qubit chips, built on KQCircuits. You draw a chip,
check it, estimate its frequencies and couplings from a lumped circuit model (the LOM), simulate it in HFSS or Q3D,
compare the two, tune the geometry towards your targets and export the fab mask. One file, `design.json`, carries the
chip through every step:

**draw → check (DRC) → LOM → simulate (HFSS / Q3D) → results → tune → fab mask**

## Design philosophy

Start cheap, spend solver time only where it pays, and let every result feed the next geometry:

**LAYOUT → LOM → EIGENMODE (per component) → FEM on the eigenmode's mesh → extract and analyse → feedback**

1. **Layout.** Draw the chip from real components with pins (KLayout plugin or Python). The layout is the source of
   truth; everything below is computed from it.
2. **LOM.** The layout becomes a lumped circuit in seconds: f_q, α, f_r, g, χ, κ from component formulas. Fix the
   gross errors here, before any solver runs.
3. **Eigenmode, component by component.** Cut each qubit–readout group out of the chip and solve its eigenmodes in
   HFSS with the junctions as lumped inductors. Small boxes converge fast and show where the LOM is off.
4. **FEM on the same mesh.** Reuse the converged eigenmode set-up (box, mesh seeds, the mode frequency) for the driven
   and capacitance runs, instead of meshing again from scratch.
5. **Extract and analyse.** Read the results back, fill the LOM with the FEM values, and compute the Hamiltonian
   parameters (energy participations of the lumped junctions, χ, α, κ) next to the LOM's estimates.
6. **Feedback.** Compare with the targets, propose the next geometry (lengths, claw sizes, L_J), rebuild, and go round
   again until every target is within tolerance. Then export the fab mask.

```{figure} images/system/as_built.svg
:width: 100%

The loop as it is built today. Green: built and run for real. Orange: built, partly unverified. Yellow: solver input
is written but was never solved. Grey: not built yet.
```

## Where to start

| You want to | Start with |
|---|---|
| Install it and build your first chip | [Getting started](getting-started.md) |
| Know what is in the repository and how the pieces fit | [The repository](overview/index.md) |
| Design by clicking in KLayout | [KLayout plugin](plugin/index.md), then its [Q1 + R1 tutorial](plugin/TUTORIAL_q1_r1.md) |
| Design in Python | [Python library](library/index.md) and the [tutorials](tutorials/index.md) |
| Rebuild a published chip (IBM, Google, Qiskit Metal, KQC, ...) | [Design notebooks](designs/overview.md) |
| Pick a component and see its pins | [Component reference](components/cells/index.md) |
| Find an answer fast | [FAQ](faq/index.md) |
| See what is built and what is left | [Status](overview/status.md) |

```{toctree}
:caption: Guide
:maxdepth: 2
:hidden:

getting-started
overview/index
plugin/index
library/index
tutorials/index
designs/overview
faq/index
```

```{toctree}
:caption: Developers
:maxdepth: 2
:hidden:

dev/index
```

```{toctree}
:caption: Reference
:maxdepth: 1
:hidden:

reference/cli
reference/python-api
hosting
```
