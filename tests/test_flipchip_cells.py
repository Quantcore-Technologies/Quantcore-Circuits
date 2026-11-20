"""Flip-chip and TSV cells with ports on both faces: CpwTsvTransition (new), KQC FlipChipConnectorRf (ports from
registry.KQC_EXTRA_PORTS) and QcFlipChipConnectorRf (bump size); route faces from the ports, the netlist check and
the LOM through them."""

from __future__ import annotations

import json

import pytest
from kqcircuits.defaults import default_faces
from kqcircuits.pya_resolver import pya
from typer.testing import CliRunner

from quantcore_circuits.cli import app
from quantcore_circuits.layouts.catalog import catalog, find
from quantcore_circuits.layouts.others.flip_chip import CpwTsvTransition, other_side
from quantcore_circuits.layouts.ports import CellBuildError
from quantcore_circuits.layouts.registry import create_cell, element_ports, resolve_cell
from quantcore_circuits.lom.fragment import lom_model


def _ports(ref: str, **params) -> dict:
    return {n: p.as_dict() for n, p in element_ports(resolve_cell(ref), **params).items()}


def _layers(ref: str, **params) -> dict[tuple[str, str], pya.Region]:
    """(face, layer) → merged region (dbu) of a cell built with ``params``."""
    layout = pya.Layout()
    cell = create_cell(layout, resolve_cell(ref), **params)
    out = {}
    for face, layers in default_faces.items():
        for name in ("base_metal_gap_wo_grid", "through_silicon_via", "indium_bump", "underbump_metallization"):
            region = pya.Region(cell.begin_shapes_rec(layout.layer(layers[name]))).merged()
            if not region.is_empty():
                out[(face, name)] = region
    return out


def _fragment(ref: str, params: dict):
    from types import SimpleNamespace

    return lom_model(ref)("T", SimpleNamespace(cell=ref, params=params, junction=None), None)


# ---- CpwTsvTransition -------------------------------------------------------------------------------------------
def test_other_side():
    assert [other_side(f) for f in ("1t1", "1b1", "2b1", "2t1")] == ["1b1", "1t1", "2t1", "2b1"]
    with pytest.raises(ValueError):
        other_side("3t1")


def test_tsv_ports_and_faces():
    ports = _ports("CpwTsvTransition")
    assert ports["a"] == {"name": "a", "at": [-115.0, 0.0], "dir": 180.0, "a": 10.0, "b": 6.0, "face": "1t1"}
    assert ports["b"] == {"name": "b", "at": [115.0, 0.0], "dir": 0.0, "a": 10.0, "b": 6.0, "face": "1b1"}
    top = _ports("CpwTsvTransition", face_ids=["2b1"], taper_length=0, a2=8, b2=4)
    assert (top["a"]["face"], top["b"]["face"]) == ("2b1", "2t1")
    assert (top["a"]["at"], top["a"]["a"], top["a"]["b"]) == ([-15.0, 0.0], 40.0, 24.0)  # no taper: the pad edge
    assert (top["b"]["a"], top["b"]["b"]) == (8.0, 4.0)
    back_first = _ports("CpwTsvTransition", face_ids=["1b1"])
    assert (back_first["a"]["face"], back_first["b"]["face"]) == ("1b1", "1t1")


def test_tsv_geometry():
    """Front pad + taper on 1t1, back pad + taper on 1b1, 2 signal + 8 ground TSVs on both faces, nothing on chip 2."""
    layers = _layers("CpwTsvTransition")
    assert set(layers) == {(f, n) for f in ("1t1", "1b1") for n in ("base_metal_gap_wo_grid", "through_silicon_via")}
    dbu = 0.001
    assert layers[("1t1", "base_metal_gap_wo_grid")].bbox().to_dtype(dbu) == pya.DBox(-115, -44, 39, 44)
    assert layers[("1b1", "base_metal_gap_wo_grid")].bbox().to_dtype(dbu) == pya.DBox(-39, -44, 115, 44)
    for face in ("1t1", "1b1"):
        vias = layers[(face, "through_silicon_via")]
        assert vias.count() == 10 and vias.bbox().to_dtype(dbu) == pya.DBox(-55, -64, 55, 64)
        signal = vias & pya.Region(pya.DBox(-20, -20, 20, 20).to_itype(dbu))
        assert signal.count() == 2
    # the signal TSVs sit on the pad's centre conductor (not in its gap) on both faces
    for face in ("1t1", "1b1"):
        assert (layers[(face, "through_silicon_via")] & layers[(face, "base_metal_gap_wo_grid")]).is_empty()
    standard = _layers("CpwTsvTransition", tsv_type="Tsv Standard", n_ground_vias_per_side=0, n_signal_vias=1)
    assert standard[("1t1", "through_silicon_via")].count() == 1


def test_tsv_rejects_vias_that_do_not_fit():
    with pytest.raises(CellBuildError, match="do not fit"):
        _layers("CpwTsvTransition", n_signal_vias=3)  # 2 × 20 + 10 µm across a 40 µm pad
    with pytest.raises(CellBuildError, match="no other side"):
        _layers("CpwTsvTransition", face_ids=["9t9"])


def test_tsv_keepout_covers_the_vias():
    (box,) = CpwTsvTransition.qcc_keepout({"taper_length": 0})
    assert box.left <= -55 - 20 and box.right >= 55 + 20 and box.top >= 64 + 20 and box.bottom <= -64 - 20


# ---- FlipChipConnectorRf (KQC) and QcFlipChipConnectorRf ---------------------------------------------------------
@pytest.mark.parametrize("ref", ["FlipChipConnectorRf", "QcFlipChipConnectorRf"])
def test_connector_ports(ref):
    ports = _ports(ref)
    assert ports["a"] == {"name": "a", "at": [-60.0, 0.0], "dir": 180.0, "a": 10.0, "b": 6.0, "face": "1t1"}
    assert ports["b"] == {"name": "b", "at": [60.0, 0.0], "dir": 0.0, "a": 10.0, "b": 6.0, "face": "2b1"}
    flipped = _ports(ref, face_ids=["2b1", "1t1"], a2=20, b2=8)
    assert (flipped["a"]["face"], flipped["b"]["face"]) == ("2b1", "1t1")
    assert (flipped["b"]["a"], flipped["b"]["b"]) == (20.0, 8.0)
    turned = _ports(ref, output_rotation=90)
    assert turned["b"]["at"] == [0.0, -60.0] and turned["b"]["dir"] == -90.0


def test_kqc_connector_draws_its_default_bump():
    layers = _layers("FlipChipConnectorRf")
    bumps = layers[("1t1", "indium_bump")]
    assert bumps.count() == 5  # signal bump + KQC's 4 ground bumps, 25 µm
    assert bumps.interacting(pya.Region(pya.Box(-1, -1, 1, 1))).bbox().width() == pytest.approx(25000, abs=20)


def test_qc_connector_bump_size():
    layers = _layers("QcFlipChipConnectorRf", bump_diameter=15, ubm_diameter=20, n_ground_bumps=0, connector_a=30,
                     connector_b=6)
    for face in ("1t1", "2b1"):
        bump, ubm = layers[(face, "indium_bump")], layers[(face, "underbump_metallization")]
        assert bump.count() == 1 and bump.bbox().width() == pytest.approx(15000, abs=20)
        assert ubm.count() == 1 and ubm.bbox().width() == pytest.approx(20000, abs=20)
    assert _layers("QcFlipChipConnectorRf")[("1t1", "indium_bump")].count() == 5  # defaults: KQC's
    with pytest.raises(CellBuildError, match="n_ground_bumps"):
        _layers("QcFlipChipConnectorRf", n_ground_bumps=2)


# ---- catalog, CLI, LOM ------------------------------------------------------------------------------------------
def test_catalog_and_cli_list_the_cells():
    refs = {c.ref for c in catalog(category="flip_chip")}
    assert {"CpwTsvTransition", "QcFlipChipConnectorRf", "FlipChipConnectorRf"} <= refs
    assert find("CpwTsvTransition").port_names() == ["a", "b"]
    assert find("FlipChipConnectorRf").port_names() == ["a", "b"] and find("FlipChipConnectorRf").note
    runner = CliRunner()
    res = runner.invoke(app, ["components", "CpwTsvTransition", "--json"])
    assert res.exit_code == 0 and {p["name"]: p["face"] for p in json.loads(res.output)} == {"a": "1t1", "b": "1b1"}
    res = runner.invoke(app, ["components", "FlipChipConnectorRf"])
    assert res.exit_code == 0 and "face 2b1" in res.output


def test_lom_models_are_one_conductor():
    tsv = _fragment("CpwTsvTransition", {})
    (line,) = tsv.lines
    assert tsv.port_nodes == {"a": "line", "b": "line"} and line.through and line.length_um == pytest.approx(230)
    for ref in ("FlipChipConnectorRf", "QcFlipChipConnectorRf"):
        fc = _fragment(ref, {"connector_a": 30})
        (line,) = fc.lines
        assert fc.port_nodes == {"a": "line", "b": "line"} and line.through and line.length_um == pytest.approx(90)


# ---- a line through all four faces ------------------------------------------------------------------------------
def _chain(tmp_path, connector: str):
    from quantcore_circuits.designer import Designer

    d = Designer("fc_chain", box=(0, 0, 6000, 2000), live=False, verbose=False, out=tmp_path / "fc_chain.oas")
    d.add("P1", "BondPad", at=(500, 1000), rot=270)
    d.add("T1", "CpwTsvTransition", at=(1200, 1000))
    d.add("T2", "CpwTsvTransition", at=(1800, 1000), rot=180)
    d.add("FC", connector, at=(2400, 1000), connector_a=40, connector_b=6)
    d.add("T3", "CpwTsvTransition", at=(3000, 1000), face_ids=["2b1"])
    d.add("T4", "CpwTsvTransition", at=(3600, 1000), rot=180, face_ids=["2b1"])
    d.add("FC2", connector, at=(4200, 1000), connector_a=40, connector_b=6, face_ids=["2b1", "1t1"])
    d.add("P2", "BondPad", at=(5500, 1000), rot=90)
    d.route("R1", "P1.a", "T1.a")
    d.route("R2", "T1.b", "T2.b")  # 1b1: the face of both ports
    d.route("R3", "T2.a", "FC.a")
    d.route("R4", "FC.b", "T3.a")  # 2b1
    d.route("R5", "T3.b", "T4.b")  # 2t1
    d.route("R6", "T4.a", "FC2.a")  # 2b1
    d.route("R7", "FC2.b", "P2.a")
    return d


@pytest.mark.parametrize("connector", ["FlipChipConnectorRf", "QcFlipChipConnectorRf"])
def test_line_through_four_faces(tmp_path, connector):
    from quantcore_circuits.assembly.netlist import check_netlist

    d = _chain(tmp_path, connector)
    result = d.show()
    faces = {n: r.params["face_ids"][0] for n, r in result.plan.routes.items()}
    assert faces == {"R1": "1t1", "R2": "1b1", "R3": "1t1", "R4": "2b1", "R5": "2t1", "R6": "2b1", "R7": "1t1"}
    # each route is drawn on its face only
    layout = result.cell.layout()
    for name, face in faces.items():
        route = next(i for i in result.cell.each_inst() if i.property("id") == name)
        etch = {f: not pya.Region(route.cell.begin_shapes_rec(layout.layer(default_faces[f]["base_metal_gap_wo_grid"])))
                .is_empty() for f in default_faces}
        assert [f for f, drawn in etch.items() if drawn] == [face], name
    report = check_netlist(result)
    assert report.ok, [str(i) for i in report.issues]
    lb = d.lom()
    nodes = {lb.port_map[p] for p in ("P1.a", "T1.a", "T2.b", "FC.a", "FC.b", "T3.b", "FC2.a", "FC2.b", "P2.a")}
    assert len(nodes) == 1  # one conductor from pad to pad


def test_route_on_the_wrong_face_raises(tmp_path):
    from quantcore_circuits.designer import Designer
    from quantcore_circuits.route.router import RoutingError

    d = Designer("fc_wrong", box=(0, 0, 3000, 2000), live=False, verbose=False, out=tmp_path / "fc_wrong.oas")
    d.add("T1", "CpwTsvTransition", at=(1000, 1000))
    d.add("T2", "CpwTsvTransition", at=(2000, 1000), rot=180)
    d.route("R", "T1.b", "T2.b", face_ids=["1t1"])
    with pytest.raises(RoutingError, match="on face 1t1 but T1.b is on face 1b1"):
        d.show()


def test_faceless_ports_are_unchanged():
    """Ports of ordinary cells record no face; their dicts and their routes are as before."""
    for ref in ("WaveguideCoplanar", "BondPad", "Xmon"):
        for port in element_ports(resolve_cell(ref)).values():
            assert port.face is None and "face" not in port.as_dict()
