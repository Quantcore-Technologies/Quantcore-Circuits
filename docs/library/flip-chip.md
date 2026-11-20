# Flip-chip and TSV designs

A flip-chip design uses more than one metal face. KQCircuits names them by chip and side: `1t1` is the top of the
bottom chip (the default face of every design), `1b1` its back side, `2b1` the face of the top chip that looks down at
`1t1`, and `2t1` the top chip's back side. Indium bumps join `1t1` and `2b1`; through-silicon vias (TSVs) join the two
sides of one chip. This page lists what the library supports for such designs and points to the details.

## Building one

- **Cells.** `CpwTsvTransition` carries a CPW line through one chip, with port `a` on the front face and port `b` on
  the back face. KQC's `FlipChipConnectorRf` carries a line across the bump gap, with ports `a` (on `1t1`) and `b`
  (on `2b1`). `QcFlipChipConnectorRf` is the same connector with a settable bump, under-bump metal and number of ground
  bumps. See [Flip-chip and TSV cells](components.md#flip-chip-and-tsv-cells).
- **Routes.** A route takes its face from the port it starts on (or from `face_ids`, or a `face_id` waypoint that
  switches face mid-route). A route whose own face disagrees with its port's face stops the build with a
  `RoutingError`.
- **LOM and netlist.** Both transitions are pass-through conductors: the netlist joins the lines on either side, and
  the LOM sees one node. They carry no lumped inductance or capacitance of their own.

## Checking it

- **DRC.** Overlaps and open conductors are checked per face, so pads stacked on two faces are not an overlap, and a
  route on `1b1` is checked against the `1b1` etch. A via or bump is flagged only where it lands on another
  component's etch on a shared face. See [Faces in flip-chip and TSV designs](routing-drc.md#faces-in-flip-chip-and-tsv-designs).
- **Cheese.** The PDK holes stay at least 13 µm from TSVs, bumps, under-bump metal and airbridges. The cheese is drawn
  on face `1t1` only.
- **Pictures.** The whole-chip picture draws every face on one plane, so a bump or via can look as if it sits on a
  line that runs on another face. Only shapes on the same face touch, and the DRC compares them face by face. In the
  [TSV flip-chip test chip](../designs/qpdk/tsv_flip_chip_test_chip.md), 20 ground bumps lie under the top chip's
  backside serpentines in the top-down view, with the whole top chip between them.

## Simulating it

A sim group that crosses a bump or a TSV exports with every face it uses: the faces are found from its routes and
cells, and the job gets KQC's face stack with the PDK chip gap (8 µm, KQC's default; not a measured Quantcore value).
Bumps and TSVs become conductors that join the faces. One-face groups export exactly as before. See
[Flip-chip and TSV sim groups](simulation.md#flip-chip-and-tsv-sim-groups).

## Fab export

The fab layer map writes faces `1t1` and `2b1` (the top chip on 800–804/0), TSVs on 700/0 and bumps on 801/0 and
802/0. The back faces `1b1` and `2t1` have no fab layer yet: `export_fab` leaves them out with a
`FabLayersDropped` warning. See [Fab export](fab.md).

## Not supported yet

- Junction ports on any face other than `1t1`.
- More than two chips.
- A solved multi-face FEM run: the jobs export and pass the geometry check, but none has been run in AEDT.
- Lumped values for the transitions themselves (via height, bump, width steps).

## Worked example

[The TSV flip-chip test chip](../designs/qpdk/tsv_flip_chip_test_chip.md) runs two CPW lines through all four faces with
these cells, and [the two-face Demo chip](../designs/kqc/demo_twoface.md) splits a four-qubit chip over a flip chip.
