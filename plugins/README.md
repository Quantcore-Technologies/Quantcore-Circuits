# plugins/ — tool and solver adapters

Each subfolder is a separately installable package that extends quantcore-circuits through Python entry
points, so new tools plug in without changing the core.

| Entry-point group | Loads | Used for |
|---|---|---|
| `quantcore_circuits.analyses` | a `quantcore_circuits.plugins.AnalysisPlugin` | a new `sim_groups.*.analyses` name |
| `quantcore_circuits.cells` | a module with KQC `Element` classes | extra component libraries |

An `AnalysisPlugin` has a `name`, a `kind` (`capacitance` | `eigenmode` | `driven`), a `solver` label, default
settings and `export(setup, job_dir, **settings)`. The `kind` decides how the sim builder prepares the
cut-out:

- `capacitance`: routes attached to selected qubits are cut, and edge ports are added.
- `eigenmode`: routes are kept, and there are no edge ports.

`setup.simulation` is a ready KQC `Simulation`, and qcc writes `job.json` after your exporter returns.

## Included

- `qcc-sonnet/`: Sonnet `.son` export through KQC's `export_sonnet` (analysis `sonnet_s`).

```bash
pip install -e plugins/qcc-sonnet
qcc sim build examples/q1_r1_feedline.json -g Q1R1 -a sonnet_s
```
