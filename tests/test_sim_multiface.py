"""Multi-face sim groups (flip-chip bumps, TSVs): the export simulates the faces a group's lines run on.

Tiny designs, no solver, no AEDT: a line on 1t1 that a ``face_id`` waypoint takes through KQC's bump connector onto
2b1, and a line on 1t1 joined by a TSV to a line on 1b1. Checked: the KQC face stack and chip gap, both faces' metal
in one net with the bump / TSV pillar, ports on the face their line leaves the box on, and
``sim_tools.geometry_check`` finds nothing AEDT would reject.
"""

from __future__ import annotations

import json

import pytest

from quantcore_circuits.sim_tools import build_simulation, export_job
from quantcore_circuits.sim_tools.builder import (
    face_stack_of,
    multiface_params,
    selection_faces,
    strip_unpaired_joins,
)
from quantcore_circuits.sim_tools.geometry_check import check_job

PDK = "quantcore_nb_sapphire_v1"
CHIP = {"box": [0.0, 0.0, 10000.0, 10000.0], "params": {"name_chip": "MF"}}


@pytest.fixture(autouse=True)
def _headless(monkeypatch):
    monkeypatch.setenv("QCC_LIVE", "0")
    monkeypatch.setenv("QCC_TRACK", "0")


def _flip_chip(settings: dict | None = None) -> dict:
    """Route L starts on 1t1, a ``face_id`` waypoint at x = 2500 puts KQC's bump connector there and L continues on
    2b1 to the stub W2 (placed on 2b1), then L2 runs on 2b1 to an open end."""
    return {
        "schema": "qcc/0.1", "name": "mf_flipchip", "pdk": PDK, "chip": CHIP,
        "instances": {
            "W2": {"cell": "WaveguideCoplanar", "params": {"path": [[-15.0, 0], [15.0, 0]], "face_ids": ["2b1", "1t1"]},
                   "place": {"at": [3600.0, 5000.0], "rot": 0.0}},
        },
        "routes": {
            "L": {"from": {"at": [1500.0, 5000.0], "dir": 0.0, "term": 20.0}, "to": "W2.a", "type": "cpw",
                  "nodes": [{"at": [2500.0, 5000.0], "params": {"face_id": "2b1"}}]},
            "L2": {"from": "W2.b", "to": {"at": [5000.0, 5000.0], "dir": 180.0, "term": 20.0}, "type": "cpw",
                   "params": {"face_ids": ["2b1"]}},
        },
        "sim_groups": {
            # the whole line, both faces, nothing cut
            "FC": {"select": ["L", "W2", "L2"], "margin_um": 200.0, "ports": {"L": "keep", "L2": "keep"},
                   "analyses": ["q3d_cmatrix"], "settings": settings or {}},
            # the 2b1 stub alone: L and L2 leave the box on 2b1
            "W2": {"select": ["W2"], "margin_um": 150.0, "analyses": ["q3d_cmatrix", "hfss_eigenmode", "hfss_driven"]},
        },
    }


def _tsv() -> dict:
    """A 40 µm line on 1t1 (TOP), a TSV transition (T_1t1, T_SV, T_1b1) and a line on 1b1 (BOT)."""
    wg = {"path": [[-15.0, 0], [15.0, 0]], "a": 40.0, "b": 24.0}
    return {
        "schema": "qcc/0.1", "name": "mf_tsv", "pdk": PDK, "chip": CHIP,
        "instances": {
            "T_1t1": {"cell": "WaveguideCoplanar", "params": {**wg, "term2": 24.0, "face_ids": ["1t1", "1b1"]},
                      "place": {"at": [2000.0, 5000.0], "rot": 0.0}},
            "T_1b1": {"cell": "WaveguideCoplanar", "params": {**wg, "term1": 24.0, "face_ids": ["1b1", "1t1"]},
                      "place": {"at": [2002.0, 5000.0], "rot": 0.0}},
            "T_SV": {"cell": "TsvEllipse", "params": {"face_ids": ["1t1", "1b1"], "tsv_diameter": 10.0,
                                                      "tsv_elliptical_width": 20.0, "tsv_margin": 2.0},
                     "place": {"at": [2000.0, 5000.0], "rot": 0.0}},
        },
        "routes": {
            "TOP": {"from": {"at": [1000.0, 5000.0], "dir": 0.0, "term": 20.0}, "to": "T_1t1.a", "type": "cpw",
                    "a": 40.0, "b": 24.0},
            "BOT": {"from": "T_1b1.b", "to": {"at": [3000.0, 5000.0], "dir": 180.0, "term": 20.0}, "type": "cpw",
                    "a": 40.0, "b": 24.0, "params": {"face_ids": ["1b1"]}},
        },
        "sim_groups": {"TSV": {"select": ["T_1t1", "T_1b1", "T_SV"], "margin_um": 200.0,
                               "analyses": ["q3d_cmatrix", "hfss_eigenmode"]}},
    }


def _write(tmp_path, data: dict):
    path = tmp_path / f"{data['name']}.json"
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return path


def _export(tmp_path, data: dict, group: str, analysis: str):
    setup = build_simulation(_write(tmp_path, data), group, analysis)
    job = export_job(setup, tmp_path / f"{group}_{analysis}", fast=True)
    meta = json.loads((job / "job.json").read_text(encoding="utf-8"))
    sim = json.loads((job / f"{meta['simulation_name']}.json").read_text(encoding="utf-8"))
    return setup, job, meta, sim


def _metal_by_net(sim: dict) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for name, layer in sim["layers"].items():
        if "excitation" in layer:
            out.setdefault(layer["excitation"], set()).add(name)
    return out


def test_face_stack_of_runs_the_kqc_order():
    assert face_stack_of({"1t1"}) == ["1t1"]
    assert face_stack_of({"1t1", "2b1"}) == ["1t1", "2b1"]
    assert face_stack_of({"1t1", "1b1"}) == ["1b1", "1t1"]
    assert face_stack_of({"1t1", "2t1"}) == ["1t1", "2b1", "2t1"]  # the face in between is simulated too
    assert face_stack_of({"2t1", "1b1", "1t1"}) == ["1b1", "1t1", "2b1", "2t1"]
    with pytest.raises(ValueError, match="3b1"):
        face_stack_of({"1t1", "3b1"})


def test_multiface_params_from_the_pdk_stack():
    from quantcore_circuits.pdk import get_pdk

    pdk = get_pdk(PDK)
    s = pdk.stack
    two = multiface_params(pdk, ["1t1", "2b1"])
    assert two["face_stack"] == ["1t1", "2b1"] and two["lower_box_height"] == 0.0
    assert two["chip_distance"] == [s.chip_distance] == [8.0]
    assert two["substrate_height"] == [s.substrate_height] * 2
    assert two["substrate_material"] == [s.substrate_material] * 2
    tsv = multiface_params(pdk, ["1b1", "1t1"])
    assert tsv["lower_box_height"] == s.upper_box_height and "chip_distance" not in tsv
    assert tsv["substrate_height"] == [s.substrate_height]
    assert multiface_params(pdk, ["1t1", "2b1"], chip_distance=12.0)["chip_distance"] == [12.0]


def test_two_face_line_through_a_bump_is_one_net(tmp_path):
    """q3d of the whole line: both faces' metal, the bump pillar between them, all one net; chip gap set."""
    setup, job, meta, sim = _export(tmp_path, _flip_chip(), "FC", "q3d_cmatrix")
    p = sim["parameters"]
    assert p["face_stack"] == ["1t1", "2b1"] and p["chip_distance"] == [8.0] and p["lower_box_height"] == 0.0
    assert meta["geometry"]["face_stack"] == ["1t1", "2b1"] and meta["geometry"]["chip_distance_um"] == 8.0
    nets = _metal_by_net(sim)
    signals = {k: v for k, v in nets.items() if k != 0}
    assert len(signals) == 1, nets  # line on 1t1 + bump + line on 2b1: one conductor
    (layers,) = signals.values()
    assert {"1t1_signal_1", "2b1_signal_1"} <= layers and any("indium_bump" in n for n in layers), layers
    bump = next(v for k, v in sim["layers"].items() if "indium_bump" in k)
    assert (bump["z"], bump["thickness"]) == (0.0, 8.0)  # from the 1t1 sheet up to the 2b1 sheet
    assert {"1t1_ground", "2b1_ground"} <= nets[0]
    assert not any("indium bumps dropped" in n for n in meta["notes"])
    r = check_job(job)
    assert not r["errors"] and not r["warnings"], r


@pytest.mark.parametrize("analysis", ["q3d_cmatrix", "hfss_eigenmode", "hfss_driven"])
def test_lines_leaving_the_box_on_2b1_get_their_port_on_2b1(analysis, tmp_path):
    setup, job, meta, sim = _export(tmp_path, _flip_chip(), "W2", analysis)
    face_index = setup.simulation.face_ids.index("2b1")
    ports = sim["ports"]
    assert len(ports) == 2 and all(pt["face"] == face_index and "polygon" in pt for pt in ports), ports
    assert all(pt["signal_location"][2] == pytest.approx(8.0) for pt in ports)  # on the 2b1 sheet
    assert meta["geometry"]["port_faces"] == {"1": "2b1", "2": "2b1"}
    assert {pt["type"] for pt in ports} == {"InternalPort" if analysis == "hfss_eigenmode" else "EdgePort"}
    if analysis != "q3d_cmatrix":  # the fast gap seed is on both faces' gaps
        assert set(meta["settings"]["mesh_size"]) >= {"1t1_gap", "2b1_gap"}
    r = check_job(job)
    assert not r["errors"], r["errors"]


def test_tsv_joins_1t1_and_1b1(tmp_path):
    """q3d of a TSV transition: face stack 1b1 + 1t1 with a vacuum box below, the TSV pillar overlaps both face
    sheets (a join, not a touch along the hole edge) and carries the line's net; BOT's port is on 1b1."""
    setup, job, meta, sim = _export(tmp_path, _tsv(), "TSV", "q3d_cmatrix")
    p = sim["parameters"]
    assert p["face_stack"] == ["1b1", "1t1"] and p["lower_box_height"] == 1000.0
    nets = _metal_by_net(sim)
    assert {"1t1_signal_1", "1b1_signal_1", "1b1_1t1_through_silicon_via"} <= nets[1], nets
    tsv = sim["layers"]["1b1_1t1_through_silicon_via"]
    assert (tsv["z"], tsv["thickness"]) == (-650.0, 650.0)
    assert meta["geometry"]["port_faces"] == {"2": "1b1"}
    assert sorted(meta["nets"].values()) == ["TOP"]
    r = check_job(job)
    assert not r["errors"] and not r["warnings"], r


def test_tsv_eigenmode_ports_on_both_faces(tmp_path):
    setup, job, meta, sim = _export(tmp_path, _tsv(), "TSV", "hfss_eigenmode")
    idx = setup.simulation.face_ids
    assert sorted(pt["face"] for pt in sim["ports"]) == sorted([idx.index("1t1"), idx.index("1b1")])
    assert all("polygon" in pt for pt in sim["ports"])
    assert not check_job(job)["errors"]


def test_group_settings_choose_the_faces_and_the_gap(tmp_path):
    """``settings["face_stack"]`` overrides the detection (one face: the export as before, bumps dropped);
    ``settings["chip_distance"]`` sets the gap."""
    one = build_simulation(_write(tmp_path, _flip_chip({"face_stack": ["1t1"]})), "FC", "q3d_cmatrix")
    assert one.simulation.face_stack == ["1t1"] and "face_stack" not in one.geometry
    assert one.geometry.get("indium_bump_shapes") and any("indium bumps dropped" in n for n in one.notes)
    gap = build_simulation(_write(tmp_path, _flip_chip({"chip_distance": 12.0})), "FC", "q3d_cmatrix")
    assert gap.simulation.chip_distance == [12.0] and gap.geometry["chip_distance_um"] == 12.0


def test_one_face_group_keeps_the_pdk_stack(tmp_path):
    """A group on 1t1 only (here the 1t1 part of the flip-chip line, cut at the box) is exported as before."""
    data = _flip_chip()
    data["instances"]["P"] = {"cell": "WaveguideCoplanar", "params": {"path": [[-15.0, 0], [15.0, 0]]},
                              "place": {"at": [6000.0, 7000.0], "rot": 0.0}}
    data["sim_groups"]["P"] = {"select": ["P"], "margin_um": 100.0, "analyses": ["q3d_cmatrix"]}
    s = build_simulation(_write(tmp_path, data), "P", "q3d_cmatrix")
    assert s.simulation.face_stack == ["1t1"] and s.simulation.lower_box_height == 0.0
    assert "face_stack" not in s.geometry and not any("faces simulated" in n for n in s.notes)


def test_flipmon_top_disc_does_not_add_a_face(tmp_path):
    """A qubit on 1t1 that draws a top-chip disc and a bump (Flipmon) keeps the one-face export by default."""
    from quantcore_circuits.assembly import build
    from quantcore_circuits.design import load_design
    from quantcore_circuits.pdk import get_pdk

    data = {"schema": "qcc/0.1", "name": "mf_flipmon", "pdk": PDK, "chip": CHIP,
            "instances": {"Q": {"cell": "Flipmon", "place": {"at": [5000.0, 5000.0], "rot": 0.0}}},
            "routes": {}, "sim_groups": {}}
    design = load_design(_write(tmp_path, data))
    assert selection_faces(design, build(design), ["Q"], get_pdk(PDK)) == {"1t1"}


def test_qubit_on_another_face_is_a_clear_error(tmp_path):
    data = {"schema": "qcc/0.1", "name": "mf_q2b1", "pdk": PDK, "chip": CHIP,
            "instances": {"Q": {"cell": "Swissmon", "params": {"face_ids": ["2b1", "1t1"]},
                                "junction": {"Lj_nH": 10.0, "Cj_fF": 2.0}, "place": {"at": [5000.0, 5000.0]}}},
            "routes": {}, "sim_groups": {"Q": {"select": ["Q"], "margin_um": 200.0, "analyses": ["q3d_cmatrix"]}}}
    with pytest.raises(ValueError, match="junction on face 2b1"):
        build_simulation(_write(tmp_path, data), "Q", "q3d_cmatrix")


def test_unpaired_tsvs_are_dropped(tmp_path):
    """A TSV on 1t1 in a 1t1 + 2b1 stack has no 1b1 to land on: KQC would run it to the bottom of the box."""
    from quantcore_circuits.assembly import build
    from quantcore_circuits.design import load_design

    result = build(load_design(_write(tmp_path, _tsv())))
    dropped = strip_unpaired_joins(result, ["1t1", "2b1"], 0.0)
    assert set(dropped) == {"1t1_through_silicon_via"} and dropped["1t1_through_silicon_via"] >= 1
