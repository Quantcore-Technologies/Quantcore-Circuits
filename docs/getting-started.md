# Getting started

This page goes from an empty machine to a first chip: install the library and its upstream libraries, check that the
`qcc` command works, build a one-qubit chip in a few lines of Python, and find where the files go. KLayout and AEDT are
only needed for the steps that say so. To see what the repository contains first, read [the repository](overview/index.md).

## What you need

| Need | Version | For |
|---|---|---|
| Python | 3.11 or newer | everything |
| KLayout | 0.30.5 | the plugin and live drawing (the Python package `klayout==0.30.5` is installed with the library) |
| Ansys AEDT | 2024 R1 or later | HFSS and Q3D simulations only; optional |
| Windows 10/11 or Linux | | Palace and Elmer are meant for Linux |

## Install

Install from PyPI (current release 0.0.2). SQcircuit (in the `analysis` extra)
needs PyTorch, so install its CPU build first:

```bat
conda create -n qcd python=3.11
conda activate qcd
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install --pre "quantcore-circuits[all]"
qcc kqc-files
```

`qcc kqc-files` fetches KQCircuits' simulation scripts and label font once (a few seconds, from the KQCircuits release
on GitHub). The `kqcircuits` package on PyPI does not include them, and the HFSS / Q3D / Elmer export and KQC's
chip-frame labels need them. If you have a KQCircuits checkout, you can set `QCC_KQC_SCRIPTS` to its
`klayout_package/python/scripts` folder instead; a checkout installed in editable mode needs neither.

The extras are `analysis` (Quantum Metal, pyEPR, scqubits, QuTiP, SQcircuit, QuCat), `sim` (gmsh, PyAEDT, scikit-rf),
`notebook` (Jupyter kernel, matplotlib), `all` (the three together) and `dev` (pytest, ruff, pre-commit). Without an
extra you get the layout, routing, DRC and `qcc`. `pyproject.toml` gives the dependency ranges and
`requirements/tested.txt` the exact versions the tests run with.

### Without internet: the offline wheelhouse

For a PC that cannot reach PyPI (or to pin the exact tested set), build a wheelhouse on a machine that has the
repository and the upstream libraries, copy it over and install from it:

1. `python scripts/build_wheelhouse.py` writes `dist/wheelhouse/`: this package plus wheels of KQCircuits,
   Quantum Metal, SQcircuit, QuCat and PyAEDT.
2. On the target PC, `scripts/install_sim_pc.ps1` (Windows) or `scripts/install_sim_pc.sh` creates the conda env `qcc`,
   installs torch, the pinned packages of `requirements/sim-pc.txt` and the wheels, then runs `qcc selftest` (and, from
   a checkout, `pytest -m "not slow"`). The packages the wheels pull in (numpy, pandas, ...) still come from PyPI, so
   pip needs a package index (a mirror is fine). Details are on [the simulation PC page](overview/simulation-pc.md).

### From a checkout

To work on the library or the notebooks, clone the repository and install it editable. The steps (and the tests and
the docs build) are in the [developer guide](dev/index.md).

## Check the install

```bat
conda activate qcd
qcc --version
qcc components
qcc components Xmon
```

`qcc --version` prints `quantcore-circuits 0.0.2`. `qcc components` lists the Quantcore, KQC and Metal components by
category; `qcc components Xmon` lists the ports of one of them. If `qcc` is not found, the env is not active or the
install did not finish. `qcc selftest` goes further: it checks the imports of every extra and builds, checks and
exports a small chip. Read any `[FAIL]` line.

## Your first chip in Python

This builds a feedline with two bond pads, one Xmon qubit and a readout resonator. Save it as `first_chip.py` and run
`python first_chip.py` in an empty folder.

```python
from quantcore_circuits.designer import Designer

d = Designer("my_chip", box=(0, 0, 7500, 7500), live=False)   # live=True redraws KLayout after every change
pw = d.add("PAD_W", "BondPad", at=(1125, 3750), rot=270, edge="auto")
pe = d.add("PAD_E", "BondPad", at=(6375, 3750), rot=90, edge="auto")
fl = d.route("FL", pw.a, pe.a)                                # the feedline
q1 = d.add("Q1", "Xmon", at=(2975, 2200), cross_length=300, junction={"Lj_nH": 12, "Cj_fF": 2})
d.route("R1", q1.claw_n, fl.hanger(s=2000, length=300, side="right"), meander=4200)   # the readout resonator
d.show()                       # build the layout: build/my_chip.oas
d.save("my_chip.json")         # the design file
print(d.drc())                 # connectivity checks
print(d.lom().model)           # the lumped circuit
```

What the code does:

- `edge="auto"` puts each pad where the PDK wants it, 100 µm from the die edge.
- `route` joins two pins with a Manhattan line; `fl.hanger(...)` makes a lambda/4 coupler beside the feedline, and
  `meander=4200` tunes the resonator to 4200 µm.
- `d.drc()` prints `DRC clean` when every pin is connected and nothing overlaps. The line `pdk_rn` is a design
  warning, not an error: it says the junction's normal-state resistance for 12 nH is outside the PDK window.
- `d.lom()` turns the layout into a lumped circuit from the components' estimates, with no solver.

With `live=True` the same code opens KLayout (if it is installed) and redraws it after each call; see
[KLive scripts](plugin/klive.md). More on the API: [the Designer](library/designer.md). The longer, explained version is
[tutorial 0](tutorials/00-quickstart.md), the notebook `examples/tutorials/00_quickstart_klive_and_pdk.ipynb`.

## Your first chip in KLayout

The [Q1 + R1 tutorial](plugin/TUTORIAL_q1_r1.md) draws one Xmon, its readout resonator and a feedline, then runs
check, LOM, simulation and the fab export from the panel's Flow strip. If you have never used KLayout, read
[KLayout basics](plugin/klayout-basics.md) first.

## The same chip on the command line

The example designs are in the repository's `examples/` folder (not in the pip package), so run these from a clone.

```bat
qcc build examples/q1_r1_feedline.json --show     REM build an example and open it in KLayout
qcc design drc examples/q1_r1_feedline.json
qcc circuit export examples/q1_r1_feedline.json
```

All commands are in the [`qcc` reference](reference/cli.md).

## Where outputs go

| What | Where |
|---|---|
| Layouts (`.oas`) and their sidecar (`.qcc.json`) | `build/<name>.oas`, `build/<name>.qcc.json` in the folder you run from |
| Design files | where you save them, for example `my_chip.json` or `examples/` |
| LOM circuit | `build/<name>.circuit.json` |
| FEM jobs and their results | `build/jobs/<design>_<group>_<analysis>/` |
| Dashboard state | `build/<run>/state.json` |
| Fab mask | `build/<name>_fab.oas` |

The `build/` folder is git-ignored. The full list of files per step is on [the flow page](overview/flow.md).

## Where to go next

- A map of the repository and its modules: [the repository](overview/index.md).
- What you can do with it: [use cases](overview/use-cases.md).
- Pick a component: the [component reference](components/cells/index.md) lists every component with a picture of its pins,
  a table of its pins, its parameters and its LOM model.
- Learn by notebooks: [tutorials](tutorials/index.md), then the [design notebooks](designs/overview.md).
- Something not working: the [FAQ](faq/index.md).
