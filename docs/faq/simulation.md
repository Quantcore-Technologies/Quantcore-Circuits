# Simulation

Questions about sending parts of the chip to AEDT (HFSS and Q3D): which analysis to pick, how AEDT is started, and why a
run is slow or does not converge. The page is [simulation](../library/simulation.md).

## Setup and modes

### Which AEDT do I need, and is it required?

AEDT 2024 R1 (v241) or newer, only for Q3D and HFSS runs. Without it the design, DRC, LOM and notebooks with
`RUN_FEM = False` still work. If AEDT is installed in an unusual place, set `QCC_ANSYS_EXECUTABLE`. See
[Getting started](../getting-started.md).

### What are the AEDT modes `batch`, `gui` and `attach`?

| Mode | What happens |
|---|---|
| `batch` (default) | A new non-graphical AEDT per job; it ends with the job |
| `gui` | A new AEDT window that stays open after the solve, so you can see the mesh and convergence |
| `attach` | Connect to an AEDT that is already running, or open one, and solve in it |

Set it with `--aedt` on `qcc hfss render`, the `AEDT_MODE` cell of a notebook, or `QCC_AEDT_MODE`. While a job runs, its
state (pass, convergence, elapsed time) is printed about every 30 seconds, so you can tell stuck from running.

### Will it touch my open AEDT?

Not unless you ask. `batch` and `gui` start their own AEDT. `attach` is the only mode that uses yours, and it never closes
a session it attached to. The plugin's Simulate starts a new non-graphical AEDT and never attaches; a stop from the panel
ends only the process the run started. See [simulation](../library/simulation.md).

### Can I see the mesh and the results in the AEDT window?

Yes, use `gui` (a new window) or `attach` (your open one). The plugin runs in a new non-graphical AEDT by default; tick the
box for a visible window. That GUI path from KLayout was never run for real, so expect rough edges.

## Choosing an analysis

### Q3D, eigenmode or driven: which one?

| Analysis | Use it for | Gives |
|---|---|---|
| `q3d_cmatrix` | Qubits on their own | The Maxwell capacitance matrix; fills the LOM |
| `hfss_eigenmode` / `eigenmode_epr` | A resonator with its feedline and pads, or a qubit with its readout | f, Q, participation, alpha, chi, kappa |
| `hfss_driven` | A readout line, scripted only | S-parameters; notch fits give f_r and kappa_ext |

In the plugin, Simulate offers Q3D and eigenmode: qubits alone preselect Q3D, lines, resonators or pads preselect
eigenmode. Driven runs are for scripts, not the GUI. The usual path is Q1 alone in Q3D, then Q1 + R1 + feedline + pads in
eigenmode. See [simulation](../library/simulation.md).

### Why does Q3D draw only the qubit, not the resonator?

That is how the analysis works: Q3D needs capacitances only, so the resonator is cut to a short stub and only the
qubit's islands and couplers are solved. Use eigenmode when the resonator matters.

### What is a sim group?

A sim group is a FEM sub-problem: the chosen instances and routes plus a margin. The builder cuts it out of the chip, maps
the ports (50 ohm edge ports, cut stubs, a lumped junction) and writes a job folder with `job.json`. In Python
`Designer.sim_subset(...)`, on the command line `qcc sim subset DESIGN -i Q1,R1 -a q3d_cmatrix`, in the plugin the
Simulate dialog. The panel's Sim groups tab draws a saved group on the layout; groups are never part of the chip or an
export. See [simulation](../library/simulation.md).

### How do I see what AEDT will import without starting AEDT?

Simulate > Open simulation layout opens the exported geometry in a new KLayout tab: cut-out metal, gaps, junction sheets and
port polygons. `qcc sim preview DESIGN` prints the box, components and ports as JSON. Nothing is solved.

### What happens to the junction in a simulation?

Q3D leaves the gap open (C_J is added in the LOM). Eigenmode and driven runs replace it with a lumped L in parallel with C
across the gap, with L from your `Lj_nH` (or the PDK value of a drawn Quantcore junction). Where the metal edges at the gap are long (over 20 µm) the sheet is a 10 µm-wide strip on the junction line; spanning
the whole edges had made it a long lopsided trapezoid and the qubit mode did not show up.
A qubit with no L_J blocks an eigenmode run and the Open simulation layout menu, naming the qubit. See
[components](components.md).

## Speed and memory

### What are the fast settings?

The default (`FAST_SETTINGS`, or `QCC_FEM_FAST=1`): they run in minutes and do not converge. A fast eigenmode run does at
most 3 passes and ends near delta f 3 percent against a 1 percent target; a fast Q3D run is typically a few minutes. Use
`--full` or `--set key=value` for finer runs. The aim of the fast defaults is a working loop, not accurate values. In the
plugin, the Simulate dialog is filled with them and your changes are kept for the next run; after each solve it reports
the convergence and proposes the next settings. See [simulation](../library/simulation.md).

### How much memory does it need?

A converged eigenmode run needs 32 GB or more; fast settings do not converge but run on a smaller PC. Low memory no longer stops a solve: it prints a note and keeps going. Close heavy programs first and set
`OPENBLAS_NUM_THREADS=2`. Do not try whole-chip FEM on a laptop: simulate a subset (the feedline is always included, plus
the pairs you pick).

### Why did my Q3D run give many separate nets?

A polygon with more than 8000 points is cut into separate pieces by KLayout's GDS writer, and Q3D turns each piece into its
own net. Simplifying the polygon does not get below the limit. The fix (join the pieces inside AEDT after the import) is not
built; keep long meanders out of a Q3D box. See [status](../overview/status.md).

### Which solvers besides AEDT work?

Elmer, Palace and Sonnet inputs are written, but none was ever solved, and there is no Elmer or Sonnet reader. The runner
and queue for a Linux server are covered only by unit tests. See [simulation](../library/simulation.md).
