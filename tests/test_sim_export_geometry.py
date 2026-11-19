"""Exported FEM geometry is what AEDT accepts (no solve, no AEDT): nets disjoint, junction ports with a KQC-built
polygon, no floating metal to the domain boundary (``sim_tools.geometry_check``).

Regression for the Flipmon Q3D failure (2026-11-15): the "Sim" junction's 12 + 13 µm pads overlapped in the 20 µm
disc–ring gap (one conductor; KQC "Unable to create polygon for port 1") and ended on the curved disc at one vertex
(KQC joined disc and pads, Q3D did not: "Object '1t1_signal_1_2' in Net 'Net1' and object '1t1_signal_1_3' … are
touching"); the indium bump ran as PEC to the top of the box.
"""

from __future__ import annotations

import json
import logging

import pytest

from quantcore_circuits.layouts.junctions.sim_gap import SIM_PAD_OVERLAP_UM, sim_junction_in_gap
from quantcore_circuits.sim_tools.geometry_check import MetalObject, check_job, check_nets

LJ = {"Lj_nH": 10.0, "Cj_fF": 2.0}

# (cell, params, readout port, rotation that points the readout port down to the feedline)
QUBITS = [
    ("Flipmon", {}, "coupler", 270.0),  # build/test.json's F1
    ("TransmonTaperedInsets", {"connection_pads": {"readout": {}}}, "readout", 180.0),
    ("Xmon", {}, "claw_n", 180.0),
    ("TwoPadTransmon", {}, "right", 270.0),
]


@pytest.fixture(autouse=True)
def _headless(monkeypatch):
    monkeypatch.setenv("QCC_LIVE", "0")
    monkeypatch.setenv("QCC_TRACK", "0")


def _design(cell: str, params: dict, port: str, rot: float) -> dict:
    """A qubit with a hanger readout on a pad-to-pad feedline, like the GUI's build/test.json."""
    return {
        "schema": "qcc/0.1",
        "name": f"geo_{cell.lower()}",
        "pdk": "quantcore_nb_sapphire_v1",
        "chip": {"box": [0.0, 0.0, 10000.0, 10000.0], "params": {"name_chip": "GEO"}},
        "instances": {
            "BP_W": {"cell": "BondPad", "place": {"at": [800.0, 5000.0], "rot": 270.0}},
            "BP_E": {"cell": "BondPad", "place": {"at": [9200.0, 5000.0], "rot": 90.0}},
            "Q": {"cell": cell, "params": params, "junction": LJ, "place": {"at": [5000.0, 7000.0], "rot": rot}},
        },
        "routes": {
            "FL": {"from": "BP_W.a", "to": "BP_E.a", "type": "cpw"},
            "R": {"from": f"Q.{port}", "type": "cpw",
                  "to": {"hanger": "FL", "near": [5000.0, 5000.0], "length": 500.0, "side": "left", "end": "short"}},
        },
        "sim_groups": {},
    }


def _gatemon_design() -> dict:
    """Gatemon with its GatemonCoupler on the readout edge; the feedline runs through the coupler."""
    d = _design("Xmon", {}, "claw_n", 0.0)
    d["name"] = "geo_gatemon"
    d["instances"]["Q"] = {"cell": "Gatemon", "junction": LJ, "place": {"at": [5000.0, 4880.0], "rot": 0.0}}
    d["instances"]["GC"] = {"cell": "GatemonCoupler", "place": {"snap": "qubit", "to": "Q.readout"}}
    d["routes"] = {"FL_W": {"from": "BP_W.a", "to": "GC.o1", "type": "cpw"},
                   "FL_E": {"from": "GC.o2", "to": "BP_E.a", "type": "cpw"}}
    return d


def _export(tmp_path, data: dict, analysis: str, caplog):
    from quantcore_circuits.guiflow import export_manual

    path = tmp_path / f"{data['name']}.json"
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        caplog.clear()
        jobs = export_manual(path, names=["Q"], analysis=analysis, out=tmp_path / analysis, say=lambda *a, **k: None)
        logged = [r.getMessage() for r in caplog.records if "Unable to create polygon" in r.getMessage()]
    return jobs, logged


CASES = [pytest.param(c, p, port, rot, a, id=f"{c}-{a}") for c, p, port, rot in QUBITS
         for a in ("q3d_cmatrix", "hfss_eigenmode")]


@pytest.mark.parametrize(("cell", "params", "port", "rot", "analysis"), CASES)
def test_qubit_subset_export_is_aedt_clean(cell, params, port, rot, analysis, tmp_path, caplog):
    """The GUI's Simulate export of each Quantcore qubit: every junction port gets KQC's own polygon (no log line),
    no two nets touch, every island is a net of its own, nothing floats to the domain boundary."""
    (job,), logged = _export(tmp_path, _design(cell, params, port, rot), analysis, caplog)
    assert not logged
    r = check_job(job)
    assert not r["errors"], r["errors"]
    meta = json.loads((job / "job.json").read_text(encoding="utf-8"))
    junction = next(p for p in meta["ports"] if p["kind"] == "junction")
    if cell in ("Flipmon", "TransmonTaperedInsets", "TwoPadTransmon"):  # floating: both islands are nets
        assert {"Q.island1", "Q.island2"} <= set(meta["nets"].values()), meta["nets"]
    assert junction["excitation"] in meta["nets"].values()


@pytest.mark.parametrize("analysis", ["q3d_cmatrix", "hfss_eigenmode"])
def test_gatemon_subset_export_is_aedt_clean(analysis, tmp_path, caplog):
    (job,), logged = _export(tmp_path, _gatemon_design(), analysis, caplog)
    assert not logged
    assert not check_job(job)["errors"]


def test_flipmon_sim_junction_and_bump(tmp_path, caplog):
    """build/test.json's case in detail: the junction port sheet sits in the disc–ring gap between the two pads, the
    disc and the ring are separate nets (island2 / island1), and the one-face export drops the indium bump."""
    (job,), _ = _export(tmp_path, _design("Flipmon", {}, "coupler", 270.0), "q3d_cmatrix", caplog)
    meta = json.loads((job / "job.json").read_text(encoding="utf-8"))
    sim = json.loads((job / f"{meta['simulation_name']}.json").read_text(encoding="utf-8"))
    assert sorted(meta["nets"].values()) == ["Q.coupler", "Q.island1", "Q.island2"]
    port = next(p for p in sim["ports"] if p.get("junction"))
    ys = sorted(v[1] for v in port["polygon"])
    # rot 270: the disc edge (r = 60) is at y = 7000 - 60, the ring's inner edge (r = 80) at 7000 - 80; 8 µm port
    assert ys[0] == pytest.approx(7000 - 80 + 6) and ys[-1] == pytest.approx(7000 - 60 - 6)
    assert not [k for k in sim["layers"] if "indium_bump" in k]
    assert meta["geometry"]["indium_bump_shapes"] == 2 and any("indium bumps dropped" in n for n in meta["notes"])


def test_neighbour_flipmon_window_point_contact_is_joined(tmp_path):
    """flipmon_test_chip Q1R1: Q2 (in the box, not simulated) keeps its fab trilayer window, which ends on its curved
    disc at one vertex — the same KQC-joins / Q3D-splits contact. The builder joins it with a small patch."""
    from pathlib import Path

    from quantcore_circuits.sim_tools import build_simulation, export_job

    path = Path(__file__).resolve().parents[1] / "examples" / "designs" / "qpdk" / "flipmon_test_chip.json"
    s = build_simulation(path, "Q1R1", "q3d_cmatrix")
    assert s.geometry.get("vertex_contacts_joined") == 1
    assert any("touching at a single point" in n for n in s.notes)
    assert {"Q1.island1", "Q1.island2"} <= set(s.nets.values())
    job = export_job(s, tmp_path / "job")
    assert not check_job(job)["errors"]


def test_sim_junction_in_gap():
    shift, p = sim_junction_in_gap(20.0)  # Flipmon / TransmonTaperedInsets default gap
    assert shift == SIM_PAD_OVERLAP_UM and p["junction_total_length"] == 20.0 + 2 * shift
    lower, upper = p["junction_lower_pad_length"] - shift, p["junction_upper_pad_length"] - shift  # in the gap
    assert lower == upper == 6.0 and 20.0 - lower - upper == 8.0  # KQC's 8 µm port, centred
    assert not p["include_background_gap"]
    _, wide = sim_junction_in_gap(100.0)  # wide gap (floating_transmon): KQC's 12 / 13 µm pads in the gap, as before
    assert (wide["junction_lower_pad_length"], wide["junction_upper_pad_length"]) == (12.0 + shift, 13.0 + shift)
    _, narrow = sim_junction_in_gap(6.0)
    assert narrow["junction_lower_pad_length"] - shift == pytest.approx(1.5)  # 3 µm port in a 6 µm gap


def test_check_nets_flags_point_contacts_and_touching_nets():
    """The two Q3D failure modes, on synthetic objects: a net joined only at a vertex, and two nets that touch."""
    import klayout.db as kdb

    def obj(name, exc, box):
        r = kdb.Region(kdb.Box(*box))
        return MetalObject(name, name, exc, 0.0, 0.0, r, r.bbox())

    dbu = 0.001
    disc = obj("1t1_signal_1_0", 1, (0, 0, 1000, 1000))
    pad_corner = obj("1t1_signal_1_1", 1, (1000, 1000, 2000, 2000))  # touches the disc at one corner only
    errors, warnings = check_nets([disc, pad_corner], dbu)
    assert any("touch without overlapping" in e for e in errors) and warnings
    other = obj("1t1_signal_2_0", 2, (1000, 0, 2000, 900))  # shares an edge with net 1
    errors, _ = check_nets([disc, other], dbu)
    assert any("nets 1 and 2 touch" in e for e in errors)
    joined = obj("1t1_signal_1_2", 1, (900, 0, 2000, 900))  # overlaps: one conductor, fine
    assert check_nets([disc, joined], dbu) == ([], [])
