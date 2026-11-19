# FAQ

These pages answer the questions a newcomer meets while installing, drawing, checking, simulating and tuning a chip
with Quantcore circuits. Each entry is a short answer with the command or setting, and a link to the page that explains
more. If your question is not here, start from the [home page](../index.md) or the [status](../overview/status.md)
page, which lists what is built and what is not.

| Subsection | Questions about |
|---|---|
| [Install and environments](install.md) | the conda envs, the upstream libraries, files git must not delete, finding AEDT and KLayout |
| [KLayout and the plugin](klayout-plugin.md) | installing the plugin, placing parts, rotation, route handles, dialogs, settings, the log |
| [Components and pins](components.md) | the three component libraries, pins, qubit junction values, hangers and merges, your own component |
| [Routing and DRC](routing-drc.md) | meander length, failed routes, crossings, errors against design warnings |
| [PDK and fab](pdk-fab.md) | layers, die frame, the 100 µm pad rule, keep-outs, cheese, corner rounding, device ID |
| [The LOM](lom.md) | what the lumped model is, what it estimates, how far to trust it, why it runs on the whole chip |
| [Simulation](simulation.md) | AEDT versions and modes, Q3D against eigenmode against driven, sim groups, fast settings, memory |
| [Results and feedback](results-feedback.md) | `results.json`, filling the LOM, targets, proposing the next revision |
| [Notebooks](notebooks.md) | tutorials against design notebooks, `.v1` copies, the switch cell, saved outputs |
| [Building these docs](docs.md) | the docs environment, fast builds, hosting |

```{toctree}
:maxdepth: 1
:hidden:

install
klayout-plugin
components
routing-drc
pdk-fab
lom
simulation
results-feedback
notebooks
docs
```
