"""Causes C3–C9 of docs/components/SIM_EXPORT_AUDIT.md: the simulation export of junction cells, galvanic leads,
Metal junction pins, line cuts on bends, unlabelled nets, oversized GDS polygons and SquidTermination's lead (export
only, no AEDT, nothing solved; ``sim_tools.geometry_check`` judges each job)."""

from __future__ import annotations

import json
import logging

import pytest

from quantcore_circuits.sim_tools.geometry_check import check_job

from .test_sim_export_geometry import LJ, _design, _export

PADS = {"BP_W": {"cell": "BondPad", "place": {"at": [800.0, 5000.0], "rot": 270.0}},
        "BP_E": {"cell": "BondPad", "place": {"at": [9200.0, 5000.0], "rot": 90.0}}}
HANGER = {"hanger": "FL", "near": [5000.0, 5000.0], "length": 500.0, "side": "left", "end": "short",
          "direction": "forward"}


@pytest.fixture(autouse=True)
def _headless(monkeypatch):
    monkeypatch.setenv("QCC_LIVE", "0")
    monkeypatch.setenv("QCC_TRACK", "0")


def _cell_design(name: str, instances: dict, routes: dict | None = None) -> dict:
    """A scratch design like the audit's: the cell X (plus pads / lines), sim group "cell" = X, margin 100 µm."""
    return {"schema": "qcc/0.1", "name": name, "pdk": "quantcore_nb_sapphire_v1",
            "chip": {"box": [0.0, 0.0, 10000.0, 10000.0], "params": {"name_chip": "GEO"}},
            "instances": instances, "routes": routes or {},
            "sim_groups": {"cell": {"select": ["X"], "margin_um": 100.0, "analyses": ["q3d_cmatrix"]}}}


def _cell_export(tmp_path, data: dict, analysis: str, caplog=None):
    """build_simulation + export_job (fast, no solve) of group "cell"; returns (setup, job, check, KQC log lines)."""
    from quantcore_circuits.sim_tools import build_simulation, export_job

    path = tmp_path / f"{data['name']}.json"
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    if caplog is not None:
        caplog.set_level(logging.WARNING)
        caplog.clear()
    setup = build_simulation(path, "cell", analysis)
    job = export_job(setup, tmp_path / f"{data['name']}_{analysis}", overwrite=True, fast=True)
    logged = [r.getMessage() for r in caplog.records if "Unable to create polygon" in r.getMessage()] if caplog else []
    return setup, job, check_job(job), logged


# ---- C3: junction cells on their own --------------------------------------------------------------------------------
@pytest.mark.parametrize("cell", ["Manhattan", "NoSquid", "TrilayerJunction", "metal:SNAIL"])
def test_junction_cell_alone_is_not_a_qubit(cell, tmp_path):
    """A junction cell on its own is not a qubit (no shorted junction port) and needs no L_J for eigenmode (NoSquid
    used to fail with "eigenmode analysis needs instances.X.junction.Lj_nH")."""
    from quantcore_circuits.design import Design
    from quantcore_circuits.sim_tools.builder import is_junction_cell
    from quantcore_circuits.sim_tools.subset import has_junction

    data = _cell_design(f"geo_jj_{cell.replace(':', '_').lower()}",
                        {"X": {"cell": cell, "place": {"at": [5000.0, 7000.0], "rot": 0.0}}})
    assert is_junction_cell(cell) and not has_junction(Design.model_validate(data), "X")
    for analysis in ("q3d_cmatrix", "hfss_eigenmode"):
        setup, _, r, _ = _cell_export(tmp_path, data, analysis)
        assert not [p for p in setup.ports if p.kind == "junction"]
        assert any("does not bridge two conductors" in n for n in setup.notes)
        assert not r["errors"], r["errors"]


def test_junction_inside_a_qubit_keeps_its_port():
    """C3 leaves qubits alone: a qubit (whose junction is a sub-cell) is still a qubit with a junction port."""
    from quantcore_circuits.sim_tools.builder import _is_qubit, is_junction_cell

    for cell in ("Xmon", "TwoPadTransmon", "Flipmon", "metal:StarQubit", "DoublePads", "SquidTermination"):
        assert not is_junction_cell(cell) and _is_qubit(cell), cell


# ---- C4: galvanic leads ---------------------------------------------------------------------------------------------
def test_two_pad_transmon_unrouted_lead_gets_an_open_end_in_the_sim_only(tmp_path, caplog):
    """TwoPadTransmon's unrouted 'left' lead ends on the pocket edge; the simulation etches an open end there, so
    island1 is not the ground plane (q3d used to label the whole ground plane "Q.island1"). The fab build keeps the
    lead on the pocket edge."""
    from kqcircuits.defaults import default_faces
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.assembly import build

    data = _design("TwoPadTransmon", {}, "right", 270.0)
    (job,), _ = _export(tmp_path, data, "q3d_cmatrix", caplog)
    meta = json.loads((job / "job.json").read_text(encoding="utf-8"))
    assert meta["geometry"]["lead_open_ends"] == ["Q.left"]
    assert any("open end etched" in n for n in meta["notes"])
    assert {"Q.island1", "Q.island2"} <= set(meta["nets"].values())
    assert not check_job(job)["errors"]
    # fab: no etch beyond the left lead (rot 270: the lead points +y and ends at y = 7000 + 5 + 20 + 10)
    r = build(data)
    gap = pya.Region(r.top.begin_shapes_rec(r.layout.find_layer(default_faces["1t1"]["base_metal_gap_wo_grid"])))
    assert (gap & pya.Region(pya.DBox(4999.0, 7036.0, 5001.0, 7040.0).to_itype(r.layout.dbu))).is_empty()


def test_open_end_only_where_the_own_island_is_grounded():
    """examples/designs/kqc/xmonsdirectcoupling.json: QB1's unrouted cplr2 port lies inside QB2's island (direct
    coupling); that island is not joined to ground, so no open end is etched there (an early version notched it)."""
    from pathlib import Path

    from quantcore_circuits.sim_tools import build_simulation

    path = Path(__file__).resolve().parents[1] / "examples" / "designs" / "kqc" / "xmonsdirectcoupling.json"
    s = build_simulation(path, "qubits", "q3d_cmatrix")
    assert "lead_open_ends" not in s.geometry
    assert {"QB1.island", "QB2.island", "QB3.island"} <= set(s.nets.values())


@pytest.mark.parametrize(("cell", "port", "rot"), [("TwoPadTransmon", "right", 270.0), ("LumpedJpa", "signal", 90.0)])
def test_galvanic_readout_cut_by_the_box_is_terminated(cell, port, rot, tmp_path, caplog):
    """In the eigenmode box (the qubit alone) the galvanic readout line is cut by the box edge; it is terminated in
    50 Ω there instead of joining the island to the box edge (ground), and each island keeps its own net."""
    data = _design(cell, {}, port, rot)
    (job,), _ = _export(tmp_path, data, "hfss_eigenmode", caplog)
    meta = json.loads((job / "job.json").read_text(encoding="utf-8"))
    assert ["edge_lumped", "R"] in [[p["kind"], p["name"]] for p in meta["ports"]]
    assert any("galvanic to a junction island" in n for n in meta["notes"])
    assert not check_job(job)["errors"]
    islands = {"TwoPadTransmon": {"Q.island1", "Q.island2"}, "LumpedJpa": {"Q.island"}}[cell]
    assert islands <= set(meta["nets"].values()), meta["nets"]


# ---- C5: junction pins off the metal edges --------------------------------------------------------------------------
def test_junction_gap_finds_the_edges_on_the_axis():
    """The junction port spans the gap between the two conductors along the junction axis, wherever the pins are: on
    the edges, short of them (inwards), overlapping into the metal, or the island pin in a slot of its island."""
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.sim_tools.builder import FaceMetal, junction_gap, junction_sheet

    def etch(*boxes):
        return pya.Region([pya.DBox(*b).to_itype(0.001) for b in boxes])

    box = pya.DBox(0, 0, 200, 200)
    # an island 80…120 × 60…100 in a pocket 60…140 × 40…120; the junction runs down from the island to the ground
    fm = FaceMetal.from_etch(etch((60, 40, 140, 120)) - etch((80, 60, 120, 100)), box)
    for a, b in (((100, 60), (100, 40)), ((100, 55), (100, 45)), ((100, 70), (100, 30))):  # on, inwards, overlapping
        sig, gnd = junction_gap(fm, pya.DPoint(*a), pya.DPoint(*b))
        assert (round(sig.x, 3), round(sig.y, 3), round(gnd.y, 3)) == (100.0, 60.0, 40.0)
    # the island pin sits in a 10 µm slot cut 15 µm into the island (StarQubit): the island edge is the slot end
    slot = etch((60, 40, 140, 120)) - etch((80, 60, 95, 100), (105, 60, 120, 100), (95, 75, 105, 100))
    fm2 = FaceMetal.from_etch(slot, box)
    sig, gnd = junction_gap(fm2, pya.DPoint(100, 62), pya.DPoint(100, 30))
    assert (round(sig.y, 3), round(gnd.y, 3)) == (75.0, 40.0)
    poly, width = junction_sheet(fm2, sig, gnd)
    assert width < 10.0  # narrowed to fit the slot
    assert (pya.Region(pya.DPolygon(poly).to_itype(0.001)) & fm2.metal).area() == 0
    # both pins on one conductor (a junction cell on the ground plane) or zero length: no gap
    plain = FaceMetal.from_etch(etch((95, 95, 105, 96)), box)
    assert junction_gap(plain, pya.DPoint(90, 100), pya.DPoint(110, 100)) is None
    assert junction_gap(fm, pya.DPoint(100, 50), pya.DPoint(100, 50)) is None


def test_star_qubit_junction_port_spans_the_gap(tmp_path, caplog):
    """metal:StarQubit's junction pins lie off the metal edges (the island pin between its two leads); the port is the
    sheet between the ground edge and the island along the junction axis: KQC finds both edges, no metal lies in the
    sheet, the signal side is the island (was: KQC "Unable to create polygon", 201 µm² of metal in the stand-in
    sheet, no metal beyond its signal end)."""
    inst = {**PADS, "X": {"cell": "metal:StarQubit", "junction": LJ,
                          "place": {"at": [5000.0, 7000.0], "rot": 216.00011884881656}}}
    data = _cell_design("geo_star", inst, {"FL": {"from": "BP_W.a", "to": "BP_E.a", "type": "cpw"},
                                           "R": {"from": "X.pin_rdout", "type": "cpw", "to": HANGER}})
    for analysis in ("q3d_cmatrix", "hfss_eigenmode"):
        setup, _, r, logged = _cell_export(tmp_path, data, analysis, caplog)
        assert not logged and not r["errors"], r["errors"]
        assert any("junction port spans the gap" in n for n in setup.notes)
        assert "X.island" in setup.nets.values()


# ---- C6: 50 Ω edge ports on a bend ----------------------------------------------------------------------------------
def test_eigenmode_box_edge_moves_off_a_bend(tmp_path, caplog):
    """The box edge cut SpiralLine's feed line in a bend, so its 50 Ω edge port had no polygon (AEDT skipped it); the
    edge moves until every line leaves the box on a straight section at 90°."""
    inst = {**PADS, "X": {"cell": "SpiralLine", "place": {"at": [5000.0, 5000.0], "rot": 271.8309107723719}}}
    data = _cell_design("geo_spiralline", inst, {"L_W": {"from": "BP_W.a", "to": "X.a", "type": "cpw"},
                                                 "L_E": {"from": "X.b", "to": "BP_E.a", "type": "cpw"}})
    setup, _, r, logged = _cell_export(tmp_path, data, "hfss_eigenmode", caplog)
    assert not logged and not r["errors"], r["errors"]
    assert any("box edge(s) moved" in n for n in setup.notes)
    assert sorted(p.name for p in setup.ports if p.kind == "edge_lumped") == ["L_E", "L_W"]


def test_edge_port_ok_and_crossing_square():
    """C6 criteria on synthetic lines: a straight line across the box edge passes, a line the edge runs along fails."""
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.sim_tools.builder import crossing_square, edge_port_ok

    box = pya.DBox(0, 0, 1000, 1000)
    line = pya.Region(pya.DBox(495, -50, 505, 300).to_itype(0.001))  # a = 10 µm line crossing the bottom edge
    gaps = pya.Region([pya.DBox(489, -50, 495, 300).to_itype(0.001), pya.DBox(505, -50, 511, 300).to_itype(0.001)])
    assert edge_port_ok(gaps, box, pya.DPoint(500, 0), 10, 6, 0.001)
    assert crossing_square(line, box, pya.DPoint(500, 0), 10, 6, 0.001)
    along = pya.Region(pya.DBox(300, -5, 700, 5).to_itype(0.001))  # the bottom edge runs along the line
    assert not crossing_square(along, box, pya.DPoint(500, 0), 10, 6, 0.001)
    etched = pya.Region(pya.DBox(480, -50, 520, 300).to_itype(0.001))  # the port points lie in a gap (a bend's side)
    assert not edge_port_ok(etched, box, pya.DPoint(500, 0), 10, 6, 0.001)


# ---- C7: nets without a design label --------------------------------------------------------------------------------
def test_floating_conductors_get_design_labels(tmp_path):
    """Every C-matrix net carries a design label: JtwpaChain's inner islands X.n1…X.n15 (the cell declares
    qcc_probes; its resonator buses are part of their islands, no X.floating), CapacitiveXCoupler's floating cross (X.floating), SpiralResonatorPolygon's pieces cut where its
    dropped airbridges crossed (X.res#k) and the ground it encloses (X.floating<k>)."""
    jtwpa = _cell_design("geo_jtwpa", {**PADS, "X": {"cell": "JtwpaChain",
                                                     "place": {"at": [5000.0, 7000.0], "rot": 90.0}}},
                         {"FL": {"from": "BP_W.a", "to": "BP_E.a", "type": "cpw"},
                          "R": {"from": "X.a", "type": "cpw", "to": HANGER}})
    setup, _, r, _ = _cell_export(tmp_path, jtwpa, "q3d_cmatrix")
    assert {f"X.n{k}" for k in range(1, 16)} <= set(setup.nets.values())
    assert not [n for n in setup.nets.values() if "floating" in n]  # the resonator buses join their islands (fab fix)
    assert not [w for w in r["warnings"] if "without a design label" in w]
    cross = _cell_design("geo_xcoupler", {"X": {"cell": "CapacitiveXCoupler",
                                                "place": {"at": [5000.0, 7000.0], "rot": 0.0}}})
    setup, _, r, _ = _cell_export(tmp_path, cross, "q3d_cmatrix")
    assert list(setup.nets.values()) == ["X.floating"]
    assert not [w for w in r["warnings"] if "without a design label" in w]
    spiral = _cell_design("geo_spiral", {**PADS, "X": {"cell": "SpiralResonatorPolygon",
                                                       "place": {"at": [5000.0, 5000.0], "rot": 0.0}}},
                          {"L_W": {"from": "BP_W.a", "to": "X.a", "type": "cpw"},
                           "L_E": {"from": "X.b", "to": "BP_E.a", "type": "cpw"}})
    setup, _, r, _ = _cell_export(tmp_path, spiral, "q3d_cmatrix")
    assert not [w for w in r["warnings"] if "without a design label" in w]
    assert "X.res" in setup.nets.values()


# ---- C8: GDS polygons above 4095 points -----------------------------------------------------------------------------
@pytest.mark.parametrize(("cell", "port", "holes"),
                         [("CoupledConnector", None, False), ("NeckTermination", "o1", True)])
def test_sim_polygons_stay_below_the_gds_record_limit(cell, port, holes, tmp_path):
    """Long meanders keyhole 4100–5600 points into one ground / line polygon (GDS XY record > 0x8000 bytes). The
    simulation simplifies the bends by ≤ 0.05 µm (CoupledConnector: enough). Flux-trap holes (NeckTermination) are no
    bends: an HFSS job writes that polygon as overlapping pieces of one conductor (the checker sees one conductor); a
    Q3D job keeps it whole (AutoIdentifyNets would make each piece a net), so its > 4095-point warning stays."""
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.sim_tools.builder import GDS_MAX_POINTS

    if port is None:
        inst = {**PADS, "X": {"cell": cell, "place": {"at": [5000.0, 5000.0], "rot": 90.0}}}
        routes = {"L_W": {"from": "BP_W.a", "to": "X.start", "type": "cpw"},
                  "L_E": {"from": "X.end", "to": "BP_E.a", "type": "cpw"}}
    else:
        inst = {"BP_W": PADS["BP_W"], "X": {"cell": cell, "place": {"at": [5000.0, 5000.0], "rot": 0.0}}}
        routes = {"L_W": {"from": "BP_W.a", "to": f"X.{port}", "type": "cpw"}}
    for analysis in ("q3d_cmatrix", "hfss_eigenmode"):
        setup, job, r, _ = _cell_export(tmp_path, _cell_design(f"geo_{cell.lower()}", inst, routes), analysis)
        assert setup.geometry.get("bends_simplified_um") == 0.05
        split = holes and analysis == "hfss_eigenmode"
        assert bool(setup.geometry.get("gds_polygons_split")) == split
        assert not r["errors"], r["errors"]
        too_big = [w for w in r["warnings"] if "points in one GDS polygon" in w]
        assert bool(too_big) == (holes and not split), too_big
        layout = pya.Layout()
        layout.read(str(next(job.glob("*.gds"))))
        top = layout.top_cell()
        most = max(p.num_points() for li in layout.layer_indexes() for p in pya.Region(top.begin_shapes_rec(li)).each())
        assert (most <= GDS_MAX_POINTS) == (not too_big)


# ---- C9: SquidTermination -------------------------------------------------------------------------------------------
def test_squid_termination_lead_reaches_ground_only_through_the_squid(tmp_path):
    """The 28 µm landing head was wider than the CPW (a + 2b = 22 µm) and touched the ground beside the lead, so the
    lead was shorted past the SQUID (fab too). Now the pocket starts b before the head: without the junction gap the
    lead is its own conductor; the sim export has a junction port between the island (lead + head) and ground."""
    from kqcircuits.defaults import default_faces
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.assembly import build

    def box(*b):
        return pya.Region(pya.DBox(*b).to_itype(0.001))

    for params in ({"junction_type": "No Squid"}, {}):
        r = build(_cell_design("geo_st_cell", {"X": {"cell": "SquidTermination", "params": params,
                                                     "place": {"at": [1000.0, 1000.0], "rot": 0.0}}}))
        layers = default_faces["1t1"]
        gap = pya.Region(r.top.begin_shapes_rec(r.layout.find_layer(layers["base_metal_gap_wo_grid"])))
        add_i = r.layout.find_layer(layers["base_metal_addition"])
        add = pya.Region(r.top.begin_shapes_rec(add_i)) if add_i is not None else pya.Region()
        # just inside port a (the unrouted port meets the ground), without the junction gap (x 16…36 µm)
        metal = (box(1000.5, 700, 1100, 1100) - (gap - add) - box(1016, 983, 1036, 1017)).merged()
        pieces = [pya.Region(p) for p in metal.each()]
        lead = [k for k, p in enumerate(pieces) if not p.interacting(box(1004.9, 999.9, 1005.1, 1000.1)).is_empty()]
        ground = [k for k, p in enumerate(pieces) if not p.interacting(box(1098.9, 1098.9, 1099.1, 1099.1)).is_empty()]
        assert lead and ground and lead != ground, params
    inst = {"BP_W": PADS["BP_W"], "X": {"cell": "SquidTermination", "junction": LJ,
                                        "place": {"at": [5000.0, 5000.0], "rot": 0.0}}}
    data = _cell_design("geo_st", inst, {"L_W": {"from": "BP_W.a", "to": "X.a", "type": "cpw"}})
    for analysis in ("q3d_cmatrix", "hfss_eigenmode"):
        setup, _, chk, _ = _cell_export(tmp_path, data, analysis)
        assert not chk["errors"], chk["errors"]
        assert setup.ports[0].kind == "junction" and "X.island" in setup.nets.values()


def test_squid_termination_catalog_entry():
    """SquidTermination is listed with its ports and category (what the KLayout component list shows)."""
    from quantcore_circuits.layouts.catalog import catalog

    comp = next(c for c in catalog(chips=False) if c.ref == "SquidTermination")
    assert {"a", "pump", "squid_a", "squid_b"} <= set(comp.ports_of())
    assert comp.category == "termination"
