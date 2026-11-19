# Design notebooks

The notebooks in `examples/designs/` rebuild published chips (from Qiskit Metal, KQCircuits, IBM, Google, QPDK and
other open projects) on the Quantcore PDK. Each one builds its chip one segment at a time, with a picture after each
segment: die, bond pads, readout, qubits, resonators, coupling, control lines, whole chip. Then it walks the same
steps as the plugin: Check, LOM, Simulate, Results, Fab.

Use them as worked examples: pick a chip close to the one you want and read how it is built.

## The groups

| Group | Where the designs come from | Notebooks | Build today |
|---|---|---|---|
| [Qiskit Metal](metal/index.md) | Qiskit Metal tutorials and circuit examples (Apache-2.0) | 19 | all 19 |
| [KQCircuits](kqc/index.md) | KQC's own chips and test chips (GPL-3.0) | 21 | all 21 |
| [QPDK](qpdk/index.md) | gdsfactory's quantum-rf-pdk test chips (MIT) | 6 (+2 spec only) | all 6 |
| [IBM](ibm/index.md) | IBM's 5-qubit bowtie and 27-qubit Falcon, laid out from published device data | 2 | both |
| [Google](google/index.md) | Google's tunable-coupler cell and a 2 × 2 plaquette, laid out from the papers | 2 | both |
| [DeviceLayout](devicelayout/index.md) | AWS DeviceLayout.jl examples (MIT), incl. a 17-qubit surface code | 2 | both |
| [Community](community/index.md) | public repositories and data sets (licences on each page) | 5 (+3 spec only) | all 5 |
| [SQDMetal](sqdmetal/index.md) | SQDMetal example notebooks (Apache-2.0) | 4 | all 4 |
| [SQuADDS](squadds/index.md) | SQuADDS tutorial 5, a fab-ready four-qubit chip (MIT) | 1 | yes |
| [Amplifiers](amplifiers/index.md) | JPAs and TWPAs from QPDK, twpa-sim and UNSW | 6 | all 6 |
| [Legacy](legacy/index.md) | Quantcore's own earlier chips (notebooks not rewritten; rebuilt from their saved designs for the pictures) | 20 | all 20 designs |

"Build today" means the notebook's Setup and Design cells were run on 2026-11-19 with no error, and the design they
saved is byte-identical to the one saved before the notebooks were rewritten: 68 of 68. The 20 legacy designs were
rebuilt from their saved `design.json` (their notebooks were not run): 20 of 20.

## Reading a design page

Every page has the same order, so you can stop reading when you have what you need:

1. **What it is**: two short paragraphs and a picture of the whole chip.
2. **At a glance**: the notebook, the source and licence, the chip size, what is on it, whether it builds today.
3. **How the notebook builds it**: one picture per segment and one line on what each segment adds.
4. **LOM estimates**: qubit and resonator frequencies, anharmonicity, κ and χ from the lumped model (not FEM).
5. **Build spec**: the detailed spec the notebook was written from (every component, port, route and length).

## Run one yourself

1. Open the notebook in Jupyter from the `qcd` environment (see [getting started](../getting-started.md)).
2. Run it top to bottom. KLayout opens live by default; set `QCC_LIVE=0` before starting Jupyter for no window.
3. The switch cell at the top keeps every FEM solve off (`RUN_FEM = False`): the Simulate cells export the jobs and
   the Results cells load kept results if there are any. Turn it on only with AEDT 2024 R1 or later installed.
4. Design 8 (Design 6 in the amplifiers) should print "Same design as before".

[How a design notebook works](notebook-template.md) explains the template, the switches, the variants and a checklist
for the first full run. The old one-cell version of each notebook is kept beside it as `<id>.v1.ipynb`, with its
outputs.

## Maintainer tables

- [Design specs index](INDEX.md): every spec, its conventions and its build status, as the builders use it.
- [Design status](STATUS.md): the build status table of every design.

```{toctree}
:maxdepth: 1
:hidden:

notebook-template
metal/index
kqc/index
qpdk/index
ibm/index
google/index
devicelayout/index
community/index
sqdmetal/index
squadds/index
amplifiers/index
legacy/index
INDEX
STATUS
```
