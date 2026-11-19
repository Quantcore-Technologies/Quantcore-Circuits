# Tutorials: the Quantcore design loop on real chips

Five notebooks that walk through the whole loop — PDK → layout (live in KLayout via KLive) → DRC → LOM netlist →
LOM simulation → FEM jobs (AEDT) → results back into the LOM → feedback → iterate → fab export — one small step at
a time. Tutorial 0 builds a one-qubit chip from nothing; tutorials 1–3 rebuild existing chips with our library and the
Quantcore PDK (sapphire 650 µm, εr 10.25; Nb trilayer junctions; QCT frame), the way the design notebooks under
`examples/designs/` do, but step by step and explained.

| # | notebook | chip | what it shows | runtime |
|---|---|---|---|---|
| 0 | `00_quickstart_klive_and_pdk.ipynb` | a one-qubit chip built from nothing | `get_pdk()` (stack, fab layer map, die frame, pad rule, junction rule, 3/0 keep-out, cheese, rounding); `Designer(..., live=LIVE)` sending every change to KLayout (KLive), headless fallback; pad (`edge="auto"`) → feedline → Xmon with a trilayer junction sized from a target → λ/4 hanger (`near=`); DRC, netlist and LOM after each step; the resonator length iterated onto its target; **one sim group, three FEM jobs** (Q3D C-matrix, eigenmode/EPR, driven S21 with the fem_loop recipe), solved with `RUN_FEM`, brought back (fill → LOM on FEM values; pyEPR f, α, χ, κ; notch fit κ_ext), one consensus (`loop.analyse`) and a **feedback** step (`loop.feedback` → revision 1, DRC clean); fab export with the cheese band | ≈ 1 min; with `RUN_FEM = True` + ≈ 3 min Q3D, ≈ 10–15 min eigenmode, ≈ 20–40 min driven |
| 1 | `01_chip12_coupled_chip.ipynb` | legacy chip 12 (nine Xmons: a direct pair Q1–Q2 and a tunable-coupler triple Q5–Q8–Q6) | 12 launchpads moved to the 100 µm rule; trilayer junctions / SQUIDs at the PDK nominal; readouts pinned with `near=`; DRC errors / warnings / PDK design warnings; LOM vs the legacy bare-λ/4 targets; direct-pair J and ZZ; **AEDT 2024 R1 round trip** with workstation-sized groups: `Q1_R1` Q3D, `Q1_q` eigenmode (the qubit, its readout cut by the box into a 50 Ω line), `Q1_R1e` eigenmode (qubit + readout, 100 µm margin), `Q1_Q2` Q3D → J on FEM values; estimate vs extracted and a combined consensus; claw 150 → 180 µm before/after; fab export with / without cheese and rounding; CLI equivalents | ≈ 1 min (FEM results loaded); with `RUN_FEM = True` + ≈ 3 + 5 min Q3D and ≈ 5 + 20 min eigenmode |
| 2 | `02_ibm_bowtie_5q.ipynb` | IBM 5-qubit bowtie (ibmqx2 / ibmqx4) | pocket transmons with per-qubit trilayer junctions; λ/2 buses split by a tee; readouts through finger capacitors; LOM vs IBM's f_q / f_r / J; J by avoided crossing; one bus pad widened → J changes; FEM stage 1: the Q2 subset check (Q3D + qubit-only eigenmode, FEM values only); stage 2: its values in the whole netlist (the rest estimates) → LOM vs FEM on all five qubits, readouts and buses → feedback → revision (DRC, fab); `FEM_WHOLE` (opt-in) fills from the whole-chip Q3D; `Q2_read` rendered into AEDT (`render(..., solve=False)` + `check_project`) | ≈ 2–3 min; with `RUN_FEM` + ≈ 1 + 4 min subset (+ ≈ 3 min whole-chip Q3D with `FEM_WHOLE`) |
| 3 | `03_surface17.ipynb` | DeviceLayout.jl DemoQPU17 and the ETH Zurich 17-qubit device (Krinner et al. 2022) | the shared generator `examples/designs/devicelayout/_surface17.py` used stage by stage: lattice, data / auxiliary roles, readout + Purcell modules, feedlines, control lines, crossings → airbridges; 42–50 pads moved to 100 µm; per-qubit LOM with the whole feedline; ETH values against the paper's Table I; FEM export with airbridges on / off; stage 1: the Q23 subset check (Q3D); stage 2: its values in the whole netlist (the LOM stays on estimates: StarQubit pin guard); `FEM_WHOLE` renders the whole chip (no solve); one readout gap changed | ≈ 3–5 min |
| 4 | `04_two_qubit_feedback_loop.ipynb` | two Xmons side by side, coupled through their facing arms, each with a λ/4 hanger on one feedline (an extension of tutorial 0) | targets f_q1, f_q2, f_r1, f_r2, g = J₁₂; `design(knobs)`; LOM-first synthesis (λ/4 lengths, L_J in the PDK R_n window, the ground strip from J); DRC; a **LOM loop** (λ/4 ∝ 1/f, L·C ∝ 1/f², J ∝ C_c); FEM: `PAIR` Q3D (capacitances, C_Q1Q2 → J) and `ALL` eigenmode/EPR (f, α, χ, κ, ZZ) + driven; **feedback** = FEM − LOM correction → revision 1 → re-simulated; **"I want f_q1 = X"** → redesign → DRC → FEM → residuals; fab export (cheese, rounding, layer report, `pdk_report`) and snapshots | ≈ 2–4 min; with `RUN_FEM` + ≈ 25 min per FEM iteration (Q3D + eigenmode) |

Run them in order the first time; each is self-contained.

## How to run

```bat
conda activate qcd
jupyter lab examples/tutorials/00_quickstart_klive_and_pdk.ipynb
```

- **Live (default).** `T.live_mode(gui=KLAYOUT_GUI)` returns True when KLayout is running with the klive Salt package
  (KLive on `localhost:8082`) or a KLayout executable is found (`QCC_KLAYOUT` or the usual install folders), and every
  `add` / `route` / `set` is rebuilt and reloaded there. **`KLAYOUT_GUI = True`** (next to `LIVE`, default): the first
  build opens the KLayout window if it is not running (≈ 3–20 s, with the layout and the Quantcore plugin), reopens it
  if you closed it, and brings it to the front; `False`: only a KLayout you already have open is redrawn
  (`QCC_KLAYOUT_GUI=0` does the same from outside). Without KLayout the notebooks fall back to headless on their own.
- **Headless.** `set QCC_LIVE=0` before starting Jupyter (or run the code as a script): every build writes
  `build/<name>.oas` + its `.qcc.json` sidecar, and the pictures are headless KLayout renders with the GUI's colours.
- **FEM.** Each tutorial exports its jobs to `build/jobs/<design>_<group>_<analysis>/` ("send"). `RUN_FEM = False` by default. With `RUN_FEM = True` (or a set of analyses, e.g. `{"q3d_cmatrix"}`) and AEDT 2024 R1 or later installed **and licensed**, `sim_tools.hfss.solve_job` solves each job, one at a time, the **`AEDT_MODE`** way (next to `RUN_FEM`): `"batch"` (default) in a new non-graphical AEDT process; `"gui"` in a new AEDT window that stays open, so you watch the mesh, the convergence and the fields; `"attach"` inside the AEDT window you already have open (or a new one if none is), released afterwards with the project left open. Every mode prints a progress line every 30 s (`[aedt 1:30 gui pid 25296] solve · pass 13/18 · 26 993 triangles · ΔC 0.732 % (target 0.5 %)`), so a stuck run is visible. qcc never closes an AEDT window it attached to; on a timeout only what it started is stopped. The tutorial copies `results/results.json` + `job.json` to `examples/tutorials/fem/<job>/`; the "bring it back" cells read from there, so they work later without AEDT (`build/` is not in git). Kept results of the same job (same design hash and settings) are not solved again. Tutorials 2 and 3 *render* (no solve) one or two jobs and keep the `check_project` read-back as `fem/<job>/check.json`.
- **Fast FEM (`FEM_FAST`).** `FEM_FAST = T.fem_fast(True)` (first line of each tutorial's sim-group cell, default `True`) exports every job with the library's fast test settings, `sim_tools.export.FAST_SETTINGS` (one place, documented there): Q3D 2 % / ≤ 8 passes; eigenmode ΔF 1 % / ≤ 3 passes (memory-bound here); driven ΔS 0.05 / ≤ 6 passes; mesh seeds × 3 (none given: a 40 / 30 µm gap seed for eigenmode / driven); sweeps ≤ 10 001 points. Criteria are only ever loosened and pass counts only capped, so a notebook's own looser values stay. This lets 00, 01 (+ the whole chip as one Q3D, the built-in group `chip`), 02 (+ the whole chip) and 04 run the full loop in minutes; the values are not converged but move with the design — fine-tune later with `FEM_FAST = False`. A kept result of a full (tighter) solve of the same design stands in for a fast re-run. Outside the tutorials: `sim_tools.export.set_fem_fast(True)`, `export_job(..., fast=True)` or `QCC_FEM_FAST=1`.
- **Two FEM stages (2026-11-14).** Every notebook runs its FEM part the same way, and the LOM is always the
  whole netlist:
  1. **Stage 1, the subset FEM.** `SIM_SUBSET` (a cell near the top, next to `FEM_WHOLE`, `RUN_FEM`, `RESOLVE`,
     `FEM_FAST`, `AEDT_MODE`) chooses `(qubit, readout)` pairs such as `[("Q1", "R1")]` or
     `[("Q1", None), ("Q3", None)]` (`None` = the qubit's own readout chain). `Designer.sim_subset`
     (`sim_tools/subset.py`) turns them into small sim groups — the qubit with its readout chain; the feedline always in
     the box and cut into 50 Ω ports; a bus to a qubit outside the subset cut at the qubit; one box per disjoint pair,
     solved one after the other — which are rendered and solved, and `T.subset_check` shows FEM values only:
     convergence (passes, Δ, mesh, wall time), the raw C-matrix, eigenmodes (f, Q, p_J) and S21 notches, and the
     FEM-filled capacitances next to the estimates. If they are sane and converged, go on.
  2. **Stage 2, the whole LOM.** The subset values are filled into the **whole** netlist; every other branch keeps its
     component estimate (`fill(..., scope="auto")`, the branch's `source` says "outside subset"). The LOM runs on that
     whole netlist (large chips circuit by circuit: QuCat on five qubits and seven resonators at once takes > 10 min),
     LOM and FEM are compared, every component gets its feedback, then the revision, its DRC and its fab file.
  **`FEM_WHOLE = False`** by default: `True` (opt-in, slow) also renders and solves the whole chip (the built-in
  group `chip`: nothing cut, a 50 Ω port on each pad) and fills the netlist from it instead — Q3D ≈ 2–3 min at
  `FEM_FAST`; whole-chip eigenmode / driven (`WHOLE_ANALYSES` in 01 / 02) take hours and > 30 GB here (never blocked
  on memory: `T.solve_or_load` only prints a note below `T.MIN_FREE_GB`). In 00, 04 and the q1_r1 notebooks the
  default subset is already the chip minus its pads, so `FEM_WHOLE` there means the chip with its pads; in 03 it
  renders the 17-qubit chip (no solve: a server job). Defaults: 00 `[("Q1", "R1")]`, 01 `[("Q1", "R1")]` (+ Q1's
  eigenmode boxes `Q1_q` / `Q1_R1e` and the pair `Q1_Q2`), 02 `[("Q2", None)]` (Q3D + qubit-only eigenmode),
  03 `[("Q23", None)]` (Q3D; the StarQubit pin guard keeps its estimates, so 03's LOM is on estimates), 04 both pairs.
  `RESOLVE = True` (or a set of analyses) re-solves jobs whose kept results match, e.g. after a library fix.
  `q1_r1_first_run` and `q1_r1_loop` start AEDT only with `RUN_FEM = True`.
- **Dashboard.** Each notebook's setup cell calls `track.start("t0N")`: builds, DRC, LOM runs, FEM jobs (pass / Δ / mesh while AEDT runs, read by `sim_tools.aedt_progress`) and feedback steps go to `build/t0N/state.json`; `scripts\dashboard.cmd` shows them live (http://127.0.0.1:8765/).
- **Licence.** AEDT checks a licence out of the university server (`1055@GALADRIEL.ENG-AD.GLA.AC.UK`): off the university network connect the VPN first, or the solve stops at its import step (see `%TEMP%\.ansys\licdebug.*.ANSYSEDT.EXE.241.out`).

## Files

| path | what |
|---|---|
| `_tut.py` | tutorial helpers: `setup`, `live_mode`, `pdk_md` / `fab_layers_md`, `built` / `snap` / `drc` / `drc_md` / `pad_edges_md` / `junction_box`, `send` / `solve_or_load` (bool or a set of analyses; reuses kept results of the same job: `kept_matches`; `force=RESOLVE`) / `sim_subset` / `subset_check` (stage 1, FEM only) / `subset_md` / `render_or_load` / `check_md` / `convergence_md` / `cmatrix_md` / `eigen_md` / `driven_md` / `epr_values` / `exchange_on` / `fem_vs_lom_md`, `lom_params` / `before_after_md`, `fab_report_md` |
| `designs/` | the designs the tutorials save (`t00_quickstart.json`, `t01_chip12.json`, `t02_ibm_bowtie_5q.json`, `t03_demoqpu17.json`, `t03_wallraff_17q.json`, `t04_two_qubit.json` / `_rev1` / `_user`); `qcc build` / `qcc mask` work on them |
| `fem/` | solved FEM results kept for the bring-back cells (`<job>/results/results.json` + `job.json`) and render checks (`<job>/check.json`) |
| `img/` | the snapshots each tutorial writes (`t0N_<view>.png`) |

The notebooks are saved with their outputs, so they read with results before anyone runs them. The tutorials also use the design-notebook helpers
(`examples/designs/_common.py`) and the source tables / generators of the chips they rebuild
(`examples/designs/legacy/_legacy_b.py`, `examples/designs/devicelayout/_surface17.py`).

## Tests

`tests/test_tutorials.py`: fast checks (`RUN_FEM = False`, the template steps present, the helpers incl. `solve_or_load`'s reuse / analysis-set rules (no AEDT started) and `epr_values` on the 2024 R1 fixture, the chip-12 qubit-only group's port polygons, tutorial 4's loop structure, its saved designs (build, DRC clean, the sim-group recipe) and job exports (named nets, a workstation-sized box), and every kept FEM result fills the LOM / parses) and slow runs of tutorials 0, 1 and 4 as scripts. All notebooks under `examples/` are also executed by `tests/test_examples.py -m slow`.
