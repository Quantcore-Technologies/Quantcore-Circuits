# The simulation PC

Some work needs a PC with 32 GB of RAM or more and AEDT 2024 R1 (v241) or newer: converged FEM solves, whole-chip
eigenmodes and the big chips. The notebooks mark every such spot with a note that starts "Simulation PC (32 GB+ RAM)".
This page is the checklist to follow there, in order. Everything runs through the same notebooks; only the switches
change.

## Set up the PC

1. Install the package from PyPI as in [getting started](../getting-started.md):
   `pip install torch --index-url https://download.pytorch.org/whl/cpu`, then `pip install "quantcore-circuits[all]"`,
   then `qcc kqc-files` (KQCircuits' simulation scripts and label font, which its PyPI package lacks). Clone the repository too:
   the notebooks and the tests are in it.
   **No internet on this PC?** Use the offline wheelhouse instead: on a machine with the repository and the upstream
   libraries run `python scripts/build_wheelhouse.py`, copy `dist/wheelhouse/` into the clone on the PC, and run
   `scripts/install_sim_pc.ps1` (Windows) or `scripts/install_sim_pc.sh`. The script creates the conda env `qcc`,
   installs torch, the pinned packages of `requirements/sim-pc.txt`, the wheels and `quantcore-circuits[all]`, runs
   `qcc selftest` and, from a checkout, `pytest -m "not slow"`. It stops at the first failure. Options: env name
   (`-EnvName` / `QCC_ENV`), wheelhouse folder (`-Wheelhouse` / `WHEELHOUSE`), `-SkipTorch` / `SKIP_TORCH=1`,
   `-SkipTests` / `SKIP_TESTS=1`. Other packages the wheels pull in still come from PyPI.
2. Run `qcc selftest` and fix what it reports before any solve. `ansysedt` is only reported: if it says "not found",
   install AEDT or set `QCC_ANSYS_EXECUTABLE` to the `ansysedt` executable.
3. Check that AEDT starts (`AEDT_MODE = "batch"` opens its own non-graphical process; it never touches a window you have open).
4. Close other heavy programs. Run one AEDT job at a time.

## The switches

Each tutorial has them in its first code cell ("The FEM part in two stages, and its switches").

| Switch | Set to | Meaning |
|---|---|---|
| `RUN_FEM` | `True`, or a set such as `{"q3d_cmatrix"}` | solve the exported jobs in AEDT, one after the other |
| `FEM_FAST` | `False` | converged settings instead of the fast test settings |
| `RESOLVE` | `True` | solve again although a kept result of the same job exists (needed once on the current library: the kept results are stale) |
| `AEDT_MODE` | `"batch"` (default), `"gui"` to watch the mesh | `"attach"` uses an open AEDT |

On a smaller PC leave `RUN_FEM = False`: the cells export the jobs and load kept results only.

## Order of work

### 1. The tutorials

Each solved job's `results.json` and `job.json` are copied to `examples/tutorials/fem/<job>/`. Keep that folder
after each notebook. Times are the ones measured on a 31 GB workstation at fast settings; converged runs take longer.

| Notebook | Marked before | What to run | Expected AEDT time |
|---|---|---|---|
| `00_quickstart_klive_and_pdk` | section 9 (stage 1) | the three jobs of Q1 + R1: Q3D, eigenmode + EPR, driven; set `RESOLVE = True` once | Q3D 3 min, eigenmode 20-30 min, driven about 40 min |
| | section 10 (stage 2) | LOM vs FEM on the filled netlist: the calibration check | no AEDT |
| | section 11 (feedback) | FEM point, surrogate, revision | no AEDT |
| `01_chip12_coupled_chip` | section 10 | Q3D groups, `Q1_q` and `Q1_R1e` eigenmodes; the whole chip with `WHOLE_ANALYSES` is optional | Q3D about 3 min each; eigenmodes not yet timed (a whole-readout box timed out at 20 min on 31 GB); whole-chip eigenmode hours, over 30 GB |
| | section 11 | fill the 9-qubit LOM, J on FEM values | no AEDT |
| | the feedback cell | feedback on every component | no AEDT |
| `02_ibm_bowtie_5q` | section 9 | whole-chip Q3D, qubit-only eigenmodes, the readout boxes | Q3D about 3 min; eigenmodes not yet timed (one 9.5 mm box needs over 11 GB at fast settings) |
| | section 10 | the filled 12-branch netlist, circuit by circuit | LOM over 10 min |
| | section 10 (b) | feedback and revision | no AEDT |
| `03_surface17` | section A11 | `Q23_Q33` Q3D, `Q12_readout` and `Q33_readout` eigenmodes, with and without airbridges | Q3D about 1 min; eigenmodes not yet timed |
| | section A11 (stage 2) | fill the 17-qubit LOM one qubit group at a time; the `FEM_WHOLE` job | no AEDT; whole chip needs the big PC |
| | Part B | `D5_readout` and `D5_Z3` | like A11 |
| `04_two_qubit_feedback_loop` | section 6 | revision 0: `PAIR` Q3D, `ALL` eigenmode + EPR, driven | 3-5 min, 20-30 min, about 40 min |
| | section 7 | LOM vs FEM table (the calibration) | no AEDT |
| | section 8 | FEM - LOM into the next knobs | no AEDT |
| | section 9 | revision 1 solved again: does the FEM land on target? | as section 6 |
| | section 10 | redesign for a wanted f_q1, solve, compare | as section 6 |

Two jobs of tutorial 3 need a fix before they give real values: the StarQubit pin ports on the 45 degree lattice
(the coupler and readout pads come out as ground, so the LOM keeps the component estimates).

### 2. Converged runs for tutorials 0 and 4

Set `FEM_FAST = False` in tutorials 0 and 4. This is the first converged eigenmode + EPR and driven run; so far every
eigenmode stopped after at most 3 passes. Check the convergence table (ΔF below 1 %) before you keep the result.

### 3. The design notebooks

Each of the 68 v2 design notebooks under `examples/designs/` has one marker before its `# Simulate` section. Work
through them group by group, one notebook at a time, with `RUN_FEM = True` and `FEM_FAST = False`.

| Group | Notebooks | Big chips (do last, or give a subset) |
|---|---|---|
| `metal` | 19 | `m53_wallraff_17q`, `tut222_100q_grid`, `tut443_10x10_package` |
| `kqc` | 21 | test chips; most have no qubit |
| `qpdk` | 6 | |
| `sqdmetal` | 4 | |
| `squadds` | 1 | |
| `community` | 5 | `qm2litho_12q_flux_processor` |
| `amplifiers` | 6 | |
| `devicelayout` | 2 | `demoqpu17` |
| `google` | 2 | |
| `ibm` | 2 | `ibm_falcon_27q` |

For a big chip solve the sim-group subsets, not the whole chip, unless the machine has the memory. Keep each notebook's
`fem/` folder.

### 4. Library work that follows the FEM results

These need the kept results above. They are code work, done after the solves.

1. **Calibrate the LOM against FEM:** hanger κ per kind, TransmonCross claws, claw-to-ground C, χ.
2. **Close the FEM feedback loop on target** (tutorial 4) and document how many FEM iterations it takes.
3. **Surrogates from FEM sweeps** (levels M11 and M12).
4. **Flip-chip two-face FEM export,** Q3D nets above 8000 points (unite pieces in AEDT after import), and the whole-chip LOM of the big chips.

## Future development goals

Solving with Palace, Elmer and Sonnet is not part of this checklist. Only their input files are written today; see
[the status page](status.md).
