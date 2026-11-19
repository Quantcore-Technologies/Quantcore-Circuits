# Results and feedback

Questions about reading solver output back into the design, comparing it with the LOM and your targets, and tuning the
next revision. The pages are [results](../library/results.md) and [feedback](../library/feedback.md).

## Reading results

### What does a solved job leave, and where do I find the numbers?

`qcc results collect JOB` turns solver output into one `results/results.json`: the capacitance matrix with net labels,
eigenmodes, participation, convergence and S-parameters with notch fits. The tutorials print each result as a table
(`T.cmatrix_md`, `T.eigen_md`, `T.driven_md`, `T.convergence_md`). See [results](../library/results.md).

### I solved in AEDT myself. How do I bring it back?

Change the setup in AEDT and solve there, run the job's `scripts/qcc_collect.py` in that AEDT (it exports what was
solved without solving again; or `qcc hfss collect JOB` in a new non-graphical AEDT), then import:
`qcc results import DESIGN JOB`, or the plugin's Simulate > Import results... on the job folder. Import is read again when
the AEDT outputs are newer than the stored results.

### Import results changed a file in my job folder.

When it collects from raw files, `qcc results import` can write `results/results.json` inside the folder you give it. Import
from a copy of a fixture, not from `tests/data`. See [results](../library/results.md).

### Do I have to type in the FEM values?

No. `circuit.fill.fill(model, design, jobs)` puts the FEM values into the LOM, only for the components each job owns.
Estimate, FEM and design values stay side by side, so you can compare them.

### My results do not match the design any more.

Every job stores the design hash and the group hash. If the design changed after the solve, the results belong to an older
revision and the plugin marks them stale; solve again. A kept result in a tutorial may be from an earlier revision of its
job for the same reason. In the notebooks `RESOLVE = False` keeps kept results of the same revision.

### Did the simulation converge?

Check the convergence table: passes, last delta against the target, and the converged flag. The fast settings usually stop
short (a fast eigenmode ends near 3 percent against a 1 percent target), which is fine for a working loop and not for
numbers you quote. For a converged run use finer settings or more memory. See [simulation](simulation.md).

## Targets and feedback

### How do I set a target?

On the component or route: in the plugin the dialog's targets section (f_q, alpha for a qubit; f_r, kappa for a
readout), in Python `d.targets(...)` (stored under `targets` in `design.json`). Results are compared with the targets and each value gets
pass or fail, with a tolerance (0.02 GHz for qubits and 0.01 GHz for readouts in the tutorials).

### How does the tool propose the next revision?

FEM and LOM values go into one consensus against the targets; a surrogate calibrated on the LOM proposes new values of the
knobs (junction L_J, resonator length, claw length); the revision is written, rebuilt and checked by the DRC. Use
`loop.feedback(...)` in Python; `qcc results propose DESIGN -o proposal.json` then `qcc results apply DESIGN proposal.json
-o new.json` on the command line; in the plugin Results > Propose next revision, then Apply (one undo step). See
[feedback](../library/feedback.md).

### Is the "after" value a new simulation?

No. It is the surrogate's prediction. You simulate the new revision to see the real value. In tutorial 4 the predicted
and the solved values after one revision agreed to about 0.2 percent, but the notebook still ends with "on target: False"
because its tolerances are tighter than that.

### Why are some qubits "not tuned"?

The proposal lists qubits that have no readout pair as "not tuned". Give the qubit a readout and a target and propose again.

### Can I tune a subset only?

You can render and solve a subset first (a check of convergence, the C-matrix and the eigenmodes against the estimates), and
then solve the whole chip at fast settings. The LOM and the feedback always use the whole chip. See
[the LOM](lom.md) and [simulation](simulation.md).

### Is the feedback loop proven?

Once, for real: tutorial 4 (two qubits, fast FEM settings). Other loops are emulated on the LOM for a few iterations. See
[status](../overview/status.md).

## Dashboard

### How do I watch a run live?

`qcc dashboard` (or `qcc dashboard t04` to pin a run) and open `http://127.0.0.1:8765/`. A notebook or script feeds it with
`track.start("t04", dashboard=True)` or `QCC_TRACK=1`. See [the dashboard](../overview/dashboard.md).
