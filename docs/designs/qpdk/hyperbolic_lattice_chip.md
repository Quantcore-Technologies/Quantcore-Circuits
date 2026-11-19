# Hyperbolic lattice chip (QPDK)

A finite flake of the {7,3} hyperbolic tiling from gdsfactory's quantum-rf-pdk (MIT), drawn as a lattice of CPW resonators: every tiling edge is one 7500 µm resonator and every vertex a three-pin capacitive disk coupler (after Kollár et al., Nature 2019). The chip lies on a disk of 6000 µm radius.

There is no notebook for this chip yet (spec only). The spec below is what a Quantcore rebuild would follow.

## At a glance

| | |
|---|---|
| Notebook | none yet (spec only) |
| Builds today | not applicable |

## Build spec

The rest of this page is the spec the design would be built from.

> **Update 2026-11-03:** frame = **source**: build with `chip={"die_frame": False, ...}` so the replica keeps its own size and frame (the Quantcore PDK die frame is for Quantcore chips only). `metal:<Class>` wrappers are READY (ports = Metal pin names, params = Metal options), so the `metal:` refs in this spec build as written; the Quantcore/KQC substitutions stay optional.

Source: [qpdk/samples/hyperbolic_lattice_chip.py](https://github.com/gdsfactory/quantum-rf-pdk/blob/main/qpdk/samples/hyperbolic_lattice_chip.py)
· generator `qpdk/cells/hyperbolic.py` (`hyperbolic_lattice`, `hyperbolic_edge_resonator`, `hyperbolic_vertex_coupler`)
and tiling maths `qpdk/hyperbolic.py` · licence MIT (verified) · read 2026-11-02. No image in the repo.
Reference: Kollár et al., *Hyperbolic lattices in circuit QED*, Nature 2019 (`kollarHyperbolicLatticesCircuit2019`).
What it is: a finite flake of the {p, q} = {7, 3} hyperbolic tiling (central heptagon + `shells = 1` ring) mapped from
the Poincaré disk onto a 6000 µm-radius disk on chip. **Every tiling edge is one CPW resonator** of exactly 7500 µm
(pin rim to pin rim), meandered inside the quadrilateral formed by its two vertices and the centroids of the two
adjacent faces. **Every vertex is a 3-pin capacitive disk coupler.** Free boundary pins get a 400 µm shorted λ/4 stub
(far above the band). Two free pins (`probe_pins = (11, 0)`) are fed out to launchers. The model is line-graph tight
binding with t < 0 and a flat band at ω₀ − 2|t|.
Size: not stated. The disk is ⌀ 12 mm, plus feed lines (1000 µm + bends) and launchers, plus a 500 µm `edge_margin`.
Estimate **≈ 14 × 14 mm**, box (0, 0, 14000, 14000), disk centre at (7000, 7000) (source is centred on the disk).
Status: **no (missing: hyperbolic_vertex_coupler, exact-length region meander)**. Reference/P3.

### Generator (use this instead of a per-instance table)
| item | count (derived for {7,3}, 1 shell) | parameters |
|---|---|---|
| faces (heptagons) | 8 (1 central + 7) | `central_polygon_radius(p, q)` sets the hyperbolic scale |
| vertices = couplers `V_i` | 35 (14 interior/degree-3, 21 boundary/degree-2) | pin_radius 40, pin_gap 4 (radial), ground_gap 6, lead_length 20; one pin per incident edge, oriented along the geodesic tangent |
| edges = resonators `R_ij` | 42 | length 7500 µm rim-to-rim (leads included), bend_radius 30 (legs 60 µm apart), margin 25 µm from region edge, end_straight 70 |
| boundary stubs | 21 free pins − 2 probes = 19 | shorted CPW, 400 µm pin-rim to short |
| probe feeds + launchers | 2 (free pins 11 and 0) | straight 1000 µm along the pin direction, then a 90° turn into a launcher (2·r lead-in, r = 100) |

The counts are derived from the tiling (V − E + F = 35 − 42 + 8 = 1 for the disk) and are not printed by the source.
Check them against `c.info["num_resonators"]` / `["num_couplers"]` if QPDK is ever run (not run here).
Vertex positions: the hyperbolic tiling in the unit disk, scaled by 6000 µm. Recompute them with the closed-form
heptagon tiling. The central polygon's circumradius in the Poincaré disk is `central_polygon_radius(7, 3)`; outer
vertices come from reflecting across geodesic edges (`_reflect`). The builder can port `qpdk/hyperbolic.py`
(pure numpy) as a generator.

### Components
| instance | catalog ref | key params | at | rot | notes |
|---|---|---|---|---|---|
| V_0…V_34 | `MISSING: hyperbolic_vertex_coupler` | q = 3 pins, pin_radius 40, pin_gap 4, ground_gap 6, lead_length 20 | tiling vertex × 6000 µm + (7000, 7000) | pin angles = edge tangents | a 40 µm-radius metal disk cut into 3 pie-slice pins by 4 µm radial gaps, 6 µm ground ring, each pin feeds a 20 µm CPW lead |
| P1, P2 | `BondPad` | default | end of each feed | facing the feed | launcher1/2 |

### Routes
| route | from → to | type, length | notes |
|---|---|---|---|
| R_ij (42) | V_i.pin_k → V_j.pin_l | meander **7500** (incl. 2 × 20 µm leads) | must stay inside its quadrilateral region (the vertices plus adjacent face centroids; for boundary edges the outer apex is the mirrored centroid × 0.6) |
| S_v (19) | V_v.free pin → free_end (short) | cpw 400 | λ/4 stub |
| F1, F2 | V.free pins 11, 0 → P1.a, P2.a | cpw ≈ 1000 + bends | probe lines |

### LOM node structure
42 identical λ/2 CPW resonators (7500 µm, ≈ 8.0 GHz on Si (ε_eff ≈ 6.2), our estimate) as nodes of the line graph.
Each vertex coupler is a 3-way capacitance network between the three resonator ends that meet there (pin_gap 4 µm).
19 stubs load the boundary. Two 50 Ω probe ports. No qubits, no control lines.

### Targets
None numeric. The design goal is identical hopping t on every coupler and identical ω₀ on every resonator.

### Simplifications for a first rebuild
1. Not a first-rebuild candidate. As a smoke test, build the central heptagon only: 7 vertices, 7 resonators,
   14 stubs, 2 probes. Use a `metal:StarQubit`-like 3-pad disk or three `FingerCapacitorSquare` stand-ins as the vertex coupler.
2. Requested component **hyperbolic_vertex_coupler**: a 40 µm-radius disk cut into q pie-slice pins by 4 µm radial
   gaps, inside a 6 µm ground ring. Each pin has a 20 µm CPW lead along `rotation + 360k/q`. Ports `o1…oq`, not Manhattan.
   The routing also needs an "exact length inside a polygon region" meander (QPDK `hyperbolic_edge_resonator`).
