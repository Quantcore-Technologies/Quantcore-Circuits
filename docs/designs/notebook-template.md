# How a design notebook works

Every notebook under `examples/designs/` (except `legacy/`) follows one template, the "v2" form: it builds the chip one
segment at a time with a picture after each, then walks the same steps as the plugin's Flow strip (Check, LOM,
Simulate, Results, Fab). This page describes the template, the switch cell at the top, the variants, and what to check
on a first run.

On 2026-11-19 every v2 notebook was run up to the whole-chip render (Setup and Design cells), so each one is saved
with its layout pictures and its "Same design as before" check. The LOM, Simulate, Results and Fab cells were not run,
so run them yourself; the design pages show LOM estimates computed separately. The
[tutorials](../tutorials/index.md) are different notebooks, saved with all their outputs.

## What a v2 notebook is

The notebook builds the chip the way the chip-12 notebook does, one segment at a time (die, bond pads, readout, qubit
placement, coupling, routing, whole chip), so you can see what each step adds. After the layout it follows the plugin's
Flow strip with the same names.

```{figure} ../images/design-notebooks/section_order.svg
:width: 100%

Section order of a v2 design notebook. The headings after Design use the plugin's step names.
```

| Part | Cells |
|---|---|
| Title, setup, **switch cell**, PDK table | the v1 setup is kept; the switches are `RUN_FEM = False`, `RESOLVE = False`, `FEM_FAST = True`, `AEDT_MODE = "batch"`, `MAX_ITER = 3` |
| Design 1-8 | 1 die and frame; 2 bond pads (`edge=`); 3 readout line (feedline, readout pads, tees, input capacitors, anything that needs no qubit); 4 qubit placement (qubits with `trilayer_junction`); 5 readout resonators; 6 coupling (buses, coupler elements, `d.couple`); 7 control lines (flux, drive, charge, airbridges); 8 the whole chip: sim groups, targets, centring, `save_design` |
| Check | 1 DRC (`drc_md`, `pdk_report`); 2 netlist |
| LOM | 1 simulation (`simulate_groups`); 2 plots (`plot_lom`); 3 one geometry change by hand |
| Simulate | 1 export to HFSS (`export_sims`); 2 component simulation (Q3D); 3 eigenmode; 4 full-wave on the eigenmode's mesh settings (`driven_from_eigenmode`) |
| Results | 1 eigenmode plots; 2 the values (`epr_values`, `driven_values`); 3 FEM against LOM; 4 feedback (`loop.feedback`); 5 iterate to the target (`iterate_to_target`) |
| Fab | export, snapshots, summary |

Each Design segment ends with a picture and a line "on the chip so far: n pads, n qubits, ..., this step added ...".
Design 8 calls `save_design(d, path)`, which prints "Same design as before" when the saved `<id>.json` is byte-identical
to the file it replaces. The segmentation only reorganises the same calls with the same arguments, so the JSON does
not change. If it says "differs", compare with the `.v1` notebook and fix the v2.

The same step pictures the v1 notebooks wrote (`<id>_step_die.png`, `_pads.png`, `_parts.png`, `_routes.png`) show the
progression. These are the ones from `metal/a2_two_coupled_transmons` (v1 outputs; the v2 adds a picture per segment):

```{figure} ../images/design-notebooks/a2_die.png
:width: 60%

Step 1: the empty die with the PDK frame and the device ID (v1 output of `a2_two_coupled_transmons`).
```

```{figure} ../images/design-notebooks/a2_pads.png
:width: 40%

Step 2: a bond pad at the 100 µm rule, with the cheese band beside it.
```

```{figure} ../images/design-notebooks/a2_parts.png
:width: 60%

Step 3: the components placed before any route (v1 `_step_parts.png`).
```

```{figure} ../images/design-notebooks/a2_routes.png
:width: 60%

The whole chip with its routes (v1 `_step_routes.png`).
```

## The switch cell: nothing solves as shipped

| Switch | Meaning |
|---|---|
| `RUN_FEM = False` | No AEDT is started. Simulate cells export the jobs and print "no solved results yet" unless kept results exist; Results cells load kept results from `<group>/fem/<job>/` or print one line |
| `RESOLVE = False` | Do not solve again when kept results of the same revision exist |
| `FEM_FAST = True` | Fast solver settings: minutes per solve, not converged |
| `AEDT_MODE = "batch"` | `batch`, `gui` or `attach` (as in the tutorials) |
| `MAX_ITER = 3` | Revisions tried by the iterate cell |

With `RUN_FEM = True` (AEDT 2024 R1 or later, `FEM_FAST = True`) the cells solve and keep results; set it back to `False`
and the Simulate and Results cells load them. Timings seen on the workstation: Q3D 1-5 min per component box,
eigenmode 2-17 min, driven 3-8 min.

## Variants

The template is variant A. The others differ where the chip's geometry fixes the order or the chip is one PCell.

| Variant | Chips | What changes |
|---|---|---|
| A. Qubit chips | metal, community, google, ibm, squadds, sqdmetal, qpdk and KQC qubit chips | The template. No feedline: segment 3 holds the readout pads. No pads: segment 2 says so in one sentence |
| B. Amplifiers | the six `amplifiers/` notebooks | Die, pads, feed or pump lines, the nonlinear element (JJ chain, KI serpentine, SQUID, KI resonator), routing, whole chip. LOM uses the v1's own models. Eigenmode and driven runs only where a sim group fits: none for the two TWPAs or `unsw_kipa` (it would need a new chip-sized group), no driven run for the inductive JPA (its Q of about 71 is below the helper's Q > 100 mode pick). Feedback is a one-knob rule (`rule_iterate`) because `loop.feedback` has no qubit-readout pair: `qpdk_cpw_jpa` aims at its own 6.07 GHz, the others at exercise targets. The v2 saves once (Design 6); the keys the v1s added by re-saving (`flux_phi0`, `inductor_turns`) are now in the layout calls |
| C. Test chips drawn element by element | `airbridge_crossings`, `crossing_twoface`, `quality_factor_twoface`, `sample_holder_test` | Die, launchers, test structures, routing, whole chip. LOM and Simulate only where there is a circuit or a sim group. Results are the XOR against KQC |
| D. One-PCell chips | eight KQC test chips and `daisy_woven` | The chip cannot be split without redoing the PCell, so the segments are views: the empty die, the PCell placed with `pcell_params_md`, then zoomed views of its parts. LOM, Simulate and Results say in one sentence why they do not apply |
| E. Plan-driven chips | `metal/m53_wallraff_17q`, `devicelayout/demoqpu17` | The segments are the calls of the shared `_surface17.py` helper in the target order: pads, qubits, tees and caps, feed lines, resonators, couplers, control lines. Feedback runs on one readout group (`group=`) |
| F. Order fixed by geometry | `sqchip_em`, `tuokkola_near_ms_transmon`, `demo`, `demo_twoface`, `xmonsdirectcoupling`, `shaping`, `gatemon_test_chip` | The v1 call order is kept where a position depends on an earlier one (centring before the pads, parts placed from a qubit port, snap chains). The headings follow the real order and say why |
| G. Derived or gallery | `filled_qubit_test_chip`, `component_examples`, `flipchip_qubit_resonator` | Views of loaded or gallery content; no sim groups are added |

## All rewritten notebooks

| Group | Notebooks (variant) |
|---|---|
| `metal` (19, pilot included) | `m51_four_qubit_chip` (A, pilot), `a1_transmon_readout`, `a2_two_coupled_transmons`, `a3_four_qubit_mux`, `a4_full_chip`, `a5_launch_video`, `a6_hackathon_2q`, `a7_ims2022_3q`, `iswap1_concentric_direct`, `iswap2_pocket_tc`, `iswap3_xmon_tc`, `m52_barends_5q`, `m54_wallraff_cell`, `tut13_four_qubit_ring`, `tut222_100q_grid`, `tut443_10x10_package` (all A); `m53_wallraff_17q` (E); `component_examples`, `flipchip_qubit_resonator` (G) |
| `community` (5) | `qm2litho_12q_flux_processor`, `qm2litho_6xmon`, `seven_qubit_processor` (A); `sqchip_em`, `tuokkola_near_ms_transmon` (F) |
| `devicelayout` (2) | `demoqpu17` (E), `singletransmon` (A) |
| `google` (2) | `google_tc_cell`, `google_tc_2x2` (A) |
| `ibm` (2) | `ibm_bowtie_5q`, `ibm_falcon_27q` (A) |
| `squadds` (1) | `tutorial_5_fab_ready_chip` (A) |
| `sqdmetal` (4) | `2_transmons_wres_comp`, `floating_transmon`, `two_transmon`, `xmon_cap_sim` (A) |
| `qpdk` (6) | `qubit_test_chip`, `flipmon_test_chip`, `resonator_test_chip`, `vortex_neck_test_chip` (A); `gatemon_test_chip` (F); `filled_qubit_test_chip` (G) |
| `kqc` (8) | `munchqubits`, `qualityfactor`, `simple`, `singlexmons` (A); `demo`, `demo_twoface`, `xmonsdirectcoupling` (F); `daisy_woven` (D) |
| `kqc/test_chips` (13) | `shaping` (F); `airbridge_crossings`, `crossing_twoface`, `quality_factor_twoface`, `sample_holder_test` (C); `airbridge_dc_test`, `empty`, `junction_test`, `junction_test2`, `lithography_test`, `lithography_test_twoface`, `stripes`, `tsv_test` (D) |
| `amplifiers` (6) | `jtwpa_4wm`, `ki_twpa_serpentine`, `qpdk_cpw_jpa`, `twpa_sim_jpa`, `twpa_sim_squid_jpa`, `unsw_kipa` (B; from the plan) |

The `legacy/` group was not rewritten.

## The `.v1` notebooks

Beside every rewritten notebook sits `<id>.v1.ipynb`: a byte copy of the old notebook with its saved outputs, left
unedited. Use it to see what the old run printed (the v2 marks such run values "(from the v1 run)") or to get the old
one-step layout. A `.v1` writes the same `<id>.json`, `build/<id>.oas` and step pictures as the v2, so run one or the
other, not both in a row, if you want to compare files. The test suite and `scripts/design_status.py` know about the
pairing (a v2 without outputs reports the v1's state).

## Checklist for the first run

Run top to bottom, live or with `QCC_LIVE=0` and `OPENBLAS_NUM_THREADS=2`, switches as shipped first.

- Each Design segment shows its picture and its "on the chip so far" line; the counts grow segment by segment.
- Design 8 prints "Same design as before", and `git diff examples/designs/<group>/<id>.json` is empty.
- The Check and LOM tables equal the `.v1` notebook's saved outputs; the LOM 2 plots appear.
- Simulate cells print "no solved results yet" and export the jobs; no AEDT starts.
- Results 1-3 print their "no results yet" lines. Results 4 runs `loop.analyse` and `loop.feedback` (minutes on 4+
  qubits) and gives a proposal, a revision and "DRC: clean". If it says "no target reached the consensus", see R3 below.
- Results 5: the history table ends "on target: yes" within `MAX_ITER` (on the LOM) and the residual plot falls below 1.
- Fab and the snapshots as in the v1.
- Then `RUN_FEM = True`. Watch: eigenmode boxes that cut a line on a bend (no port polygon; the builder warns), a missing
  S21 notch on pad-terminated readouts (`m51`, `a5`: kappa from the eigenmode Q instead), and pyEPR p_J near 1 on the
  qubit mode.
- With kept FEM: Results 3 shows LOM, LOM on the Q3D C-matrix and eigenmode side by side; Results 4 anchors on the FEM
  point; Results 5 with `RUN_FEM = True` solves each revision's component jobs (`fem/rev<k>/`).

A static checker, `python scripts/check_notebook_api.py NB.ipynb [--clean]`, reads a notebook without running it: schema,
syntax, names, imports and the signatures of every resolvable call.

## Known gaps

- **No mesh reuse (R1).** The library cannot reuse a solved eigenmode mesh in a driven setup. `driven_from_eigenmode`
  substitutes the same group and box, the eigenmode job's `mesh_size` seeds, the adaptive frequency at the eigenmode's
  resonator mode and a fast sweep around it. The cell says so.
- **Feedback only knows qubit-readout pairs.** `loop.feedback` tunes pairs; buses, couplers, amplifiers, test structures
  and qubits without a readout use a notebook-side first-order rule (lambda proportional to 1/f, L_J proportional to
  1/f squared). The iterate cell without `RUN_FEM` judges revisions on the LOM, so a FEM minus LOM offset is not carried
  on (tutorial 4 does the space mapping by hand).
- **Drawn junction after feedback (R2).** The feedback changes `<Q>.junction.Lj_nH`; designs that draw the PDK nominal
  fingers keep drawing them.
- Several designs carry targets outside the PDK windows, so feedback bounds are the model's defaults (R8, R11).

The ranked library requests are in [status page](../overview/status.md#library-requests-from-the-notebook-rewrite).
