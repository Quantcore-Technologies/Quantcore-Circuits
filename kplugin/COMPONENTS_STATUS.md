# Component placement status (quantcore cells, through the KLayout plugin)

Generated from `kplugin/gui_smoke_components.py` (real KLayout, scratch design per cell, 2026-11-15).

Steps per cell: **places** = panel select (parameter table fills), arm (double-click path), ghost redraw with rotate / mirror, click to drop, size check;
**edit** = edit dialog (one numeric parameter +10 %), applied to design.json, plus the double-click path; **connect** = Connect a directed port to a BondPad port, then rebuild;
**build** = the rebuild after the drop, the edit and a native (KLayout) move that syncs to design.json. `n/a` = the step does not apply.

| cell | places | edit | connect | build | notes |
|---|---|---|---|---|---|
| Flipmon | ok | ok | ok | ok | ports without direction: squid_a, squid_b (ghost draws boxes) |
| Gatemon | ok | ok | ok | ok | ports without direction: squid_a, squid_b (ghost draws boxes) |
| TransmonTaperedInsets | ok | ok | ok | ok | ports without direction: squid_a, squid_b (ghost draws boxes) |
| TwoPadTransmon | ok | ok | ok | ok | SQUID ports have no direction (null): ghost draws them as boxes (was the crash) |
| Xmon | ok | ok | ok | ok |  |
| QuantcoreJunction | ok | ok | n/a (no directed port) | ok | ports without direction: common (ghost draws boxes) |
| QuantcoreSquid | ok | ok | n/a (no directed port) | ok | ports without direction: common (ghost draws boxes) |
| SquidV0 | ok | ok | n/a (no directed port) | ok | ports without direction: common (ghost draws boxes) |
| TrilayerJunction | ok | ok | n/a (no directed port) | ok | ports without direction: common (ghost draws boxes) |
| TrilayerJunctionCompact | ok | ok | n/a (no directed port) | ok | ports without direction: common (ghost draws boxes) |
| TrilayerJunctionHSQ | ok | ok | n/a (no directed port) | ok | ports without direction: common (ghost draws boxes) |
| TrilayerSquid | ok | ok | n/a (no directed port) | ok | ports without direction: common (ghost draws boxes) |
| TrilayerSquidHSQ | ok | ok | n/a (no directed port) | ok | ports without direction: common (ghost draws boxes) |
| GatemonCoupler | ok | ok | ok | ok |  |
| HyperbolicVertexCoupler | ok | ok | ok | ok |  |
| PadCoupler | ok | ok | ok | ok |  |
| CpweFingerCapacitor | ok | ok | ok | ok |  |
| CpweFingerLine | ok | ok | ok | ok |  |
| CpweGapCapacitor | ok | ok | ok | ok |  |
| SmoothCapacitorSemicircle | ok | ok | ok | ok |  |
| CoupledResonator | ok | ok | ok | ok | end port is a capacitive tail, not galvanic: use the hanger for a readout (see README) |
| CpweQuarterWaveResonator | ok | ok | n/a (no directed port) | ok | no ports (a coupler arm only); lambda/4 for CPWE chips, place it next to the line by hand |
| CpwResonator | ok | ok | ok | ok |  |
| LumpedJpa | ok | ok | ok | ok | ports without direction: squid_a, squid_b (ghost draws boxes) |
| QubitResonator | ok | ok | ok | ok | end port is a capacitive tail, not galvanic: use the hanger for a readout (see README) |
| SpiralLine | ok | ok | made, build refused (routing error shown; Undo) | ok | ports are 2 um CPW and 1.8 deg off-axis: a Connect to a 10/6 BondPad cannot route (error shown, Undo) |
| BondPad | ok | ok | ok | ok |  |
| ConnectorPad | ok | ok | ok | ok |  |
| CpweBondPad | ok | ok | ok | ok |  |
| CpweOpenEnd | ok | ok | ok | ok |  |
| NeckTermination | ok | ok | ok | ok |  |
| SquidTermination | ok | ok | ok | ok | ports without direction: squid_a, squid_b (ghost draws boxes) |
| CoupledConnector | ok | ok | ok | ok |  |
| CpweMeanderLine | ok | ok | ok | ok |  |
| CpweTaper | ok | ok | ok | ok |  |
| CpwSegment | ok | ok | ok | ok |  |
| JtwpaChain | ok | ok | ok | ok |  |
| KiTwpaSerpentine | ok | ok | ok | ok | no etched outline (bbox only ghost) |
| AlignmentMarkers | ok | ok | n/a (no directed port) | ok | chip-sized marker set (7350 um); fits a 7500 um chip |
| BoundaryBox | ok | ok | n/a (no directed port) | ok | chip-frame box (5010 um) |
| CornerMarker | ok | ok | n/a (no directed port) | ok | no ports |
| CrossMarker | ok | ok | n/a (no directed port) | ok | no ports |
| DicingMarker | ok | ok | n/a (no directed port) | ok | no ports |
| EbeamMarker | ok | ok | n/a (no directed port) | ok | no ports |
| GlobalMarker | ok | ok | n/a (no directed port) | ok | no ports |
| WaferMap75 | ok | ok | n/a (no directed port) | ok | wafer-scale (100 mm); builds, but the plugin warns in the status bar that it is larger than the chip |
| JunctionGroundPad | ok | ok | n/a (no directed port) | ok | no ports |
| JunctionTestPads | ok | ok | n/a (no directed port) | ok | no ports |
| ProbePadPair | ok | ok | n/a (no directed port) | ok | no ports |
| TaperedPad | ok | ok | ok | ok |  |
| ArcPath | ok | ok | n/a (no directed port) | ok | no ports |
| JJFingerBent | ok | ok | n/a (no directed port) | ok | no ports |
| JJFingerStraight | ok | ok | n/a (no directed port) | ok | no ports |
| SpiralPath | ok | ok | n/a (no directed port) | ok | no ports |
| TextLabel | ok | ok | n/a (no directed port) | ok | no ports |
| FluxHoleArray | ok | ok | n/a (no directed port) | ok | no ports |
| FluxHoles | ok | ok | n/a (no directed port) | ok | no ports |

Totals: 57 cells; places ok 57; edit ok 57; build ok 57; connect ok 29, connect n/a 27, connect FAIL 0.

Not standalone on a chip: **WaferMap75** (wafer-level: it builds but is 100 mm wide; the status bar says so). Junction / SQUID cells, markers and other children place and build alone (a junction without a qubit is just a drawn shape). Whole-chip checks (Check, Run LOM on a design with no qubit, readout hanger) are in the same smoke, section `[no-qubit design]` / `[readout resonator]` of its output.
