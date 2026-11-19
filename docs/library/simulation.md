# Simulation

Simulation here means field solvers: you cut a part of the chip out as a sim group, write a job folder for a solver,
solve it (HFSS and Q3D in AEDT run from here; Elmer, Palace and Sonnet only get input files) and read the numbers back
([Results](results.md)). Use it when the lumped model is not enough, or to fill the LOM with real capacitances.
Everything this page writes goes into a job folder under `build/jobs/`.

## Sim groups

A sim group is a FEM sub-problem: chosen instances and routes plus a margin. The builder
(`sim_tools/builder.py`, `export.py`, `subset.py`) cuts the group out of the chip, maps the ports (50 ohm edge ports,
cut stubs, junction lumped RLC with L_J at the bias), names every conductor net, and writes a KQC job directory with a
`job.json` (design hash, group hash, selection, settings).

```python
GROUP = T.sim_subset(d, [("Q1", "R1")], name="Q1R1", margin_um=300, analyses=list(SIM), settings=SIM)[0]
jobs = {a: C.export_sims(DESIGN, [GROUP], a)[GROUP] for a in SIM}   # one job folder per analysis
```

(`T` and `C` are the tutorials' helper modules; the library calls behind them are `Designer.sim_group`,
`Designer.sim_subset` and `sim_tools.export.export_job`.)

| Analysis | Solver | Gives |
|---|---|---|
| `q3d_cmatrix` | Q3D | Maxwell capacitance matrix with net labels; fills the LOM |
| `hfss_eigenmode`, `eigenmode_epr` | HFSS eigenmode (+ energy participation) | f, Q, EPR, alpha, chi, kappa |
| `hfss_driven` | HFSS driven | S-parameters; notch fits give f_r and kappa_ext |
| `elmer_cap`, `palace_cap`, `palace_eig` | Elmer, Palace | input written only, see below |
| `sonnet_s` | Sonnet | input written only (plugin package `qcc-sonnet`) |

Commands:

| Command | What it does |
|---|---|
| `qcc sim preview DESIGN` | Print the box, components and every port as JSON; writes nothing |
| `qcc sim subset DESIGN -i Q1,R1 -a q3d_cmatrix [--fast / --full] [--margin]` | Export the job folder: geometry, AEDT scripts, `job.json`, `README.md`, `results_template.json` |
| `qcc sim build DESIGN -g GROUP` | Job directory for a saved sim group |
| `qcc sim auto ...` | Subset, export, solve in a new AEDT, analyse |
| `qcc hfss render DESIGN -g Q1R1 -a q3d_cmatrix [--solve] [--aedt batch, gui or attach]` | Render into an AEDT project, optionally solve |
| `qcc hfss solve JOB`, `qcc hfss check JOB`, `qcc hfss collect JOB` | Solve an exported job, read the rendered project back, re-export a solved project |

Fast solver settings are the default (`FAST_SETTINGS`, `QCC_FEM_FAST`): they run in minutes and do not converge. Use
`--full` or `--set key=value` for finer runs.

```{figure} ../images/sim/sim_geometry_q3d.png
:width: 60%

The geometry handed to AEDT for the Q3D job of tutorial 4 (`t04_two_qubit_PAIR_q3d_cmatrix/simulation.oas`): the
cut-out around the two qubits and their readouts, shown with the pads of the chip for scale.
```

```{figure} ../images/sim/sim_geometry_eigenmode.png
:width: 60%

The eigenmode job of the same design (`ALL`): the box (hatched) holds both qubits and their readouts; the feedline runs out to the two pads, which become 50 ohm ports.
```

```{figure} ../images/sim/sim_preview_eig.png
:width: 60%

The plugin's Preview for an eigenmode group: box, components, 50 ohm ports and the junction port.
```

The plugin versions of these pictures (Simulate dialog, Open simulation layout, Sim groups tab) are on the
[plugin tour](../plugin/tour.md).

## HFSS and Q3D driver

`sim_tools/hfss.py` runs a job in AEDT 2024 R1 (version 241; 241 or newer is accepted) without KQC's pyEPR
post-process, which quits AEDT. `hfss.render`, `hfss.solve_job`, `hfss.collect_job` and `hfss.check_project` are the
calls. `--aedt batch` (default) starts a new non-graphical AEDT per job, `gui` a new window, `attach` uses an open AEDT.
Progress is read from the project every 30 s (`aedt_progress`). Time-outs stop only the process tree qcc started.

To see the imported model, the ports and the mesh in AEDT, render a small group and open it:
`qcc hfss render examples/q1_r1_feedline.json -g Q1R1 -a hfss_eigenmode --open`.

Real solves on this PC: Q3D of Q1/R1 in 125 s (C within 0.2 % of an earlier result, 2026-11-03); eigenmode and EPR with
18 passes (delta f 0.52 %, not converged); driven S21 with kappa_ext 0.267 MHz; the tutorial subsets (2026-11-13/14);
the plugin end-to-end smoke with Q3D in a new AEDT (2026-11-17).

Ports where a line leaves the box at an angle (an angled crossing, a 45 degree feedline) get a 50 ohm port across the
line's own axis (`line_port` in `sim_tools/builder.py`), so the eigenmode and driven boxes of angled layouts have a
port polygon on every cut line. Design warnings never stop an export.

Limits:

- No converged eigenmode: fast eigenmode runs 3 passes at most and ends with delta f 2.8-3.2 % against a 1 % target. A
  converged run needs 32 GB or more.
- Q3D nets above 8000 points are cut into separate nets; the fix (unite in AEDT) is not built.
- The flip-chip second face is not simulated.
- Every kept tutorial result was solved for an earlier revision of its job; 57 of 153 sampled existing sim groups
  export differently since the 2026-11 export changes, so kept results must be solved again.

## Elmer, Palace, Sonnet

The exporters write input files only: `elmer_cap` (KQC `export_elmer`), `palace_cap` and `palace_eig`
(`sim_tools/palace.py`: gmsh mesh, `palace.json`, lumped port for the junction, `run_palace.sh`), `sonnet_s` (`.son`
files). Readers exist for Palace terminal C and Palace eigenfrequencies and Q (no EPR). **None of these was ever
solved.** There is no Sonnet or Elmer reader and no test for the `qcc-sonnet` plugin.

## Runner and queue

`qcc sim run JOB`, `qcc sim submit JOB --queue Q`, `qcc runner serve Q`, `qcc runner status Q` run a job locally or
through a filesystem queue for the Linux server. Only unit tests cover it; `runner.py` still carries
`TODO(verify on the Linux server)`.
