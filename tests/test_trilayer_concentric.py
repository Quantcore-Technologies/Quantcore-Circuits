"""TrilayerConcentricTransmon: the Quantcore copy of KQC ConcentricTransmon with the PDK trilayer junction."""

import importlib.util
import json
import math
from pathlib import Path

import pytest
from kqcircuits.pya_resolver import pya

from quantcore_circuits.layouts import ensure_loaded
from quantcore_circuits.layouts.catalog import find
from quantcore_circuits.layouts.ports import cell_ports
from quantcore_circuits.layouts.registry import create_cell, resolve_cell
from tests.test_oblique_join import _design, _join, _route_merges, _slivers

KQC, NEW = "ConcentricTransmon", "TrilayerConcentricTransmon"


def _build(name: str, **params):
    ensure_loaded()
    layout = pya.Layout()
    return layout, create_cell(layout, resolve_cell(name), name, **params)


def _area(layout, cell, layer: str) -> int:
    from kqcircuits.defaults import default_faces

    return pya.Region(cell.begin_shapes_rec(layout.layer(default_faces["1t1"][layer]))).area()


def _plain(layout, cell, layer_no: int) -> int:
    return pya.Region(cell.begin_shapes_rec(layout.layer(layer_no, 0))).area()


@pytest.mark.parametrize("rot", [0.0, 37.0])
def test_builds_with_ports_equal_to_kqc(rot):
    ports = {}
    for name in (KQC, NEW):
        layout, cell = _build(name)
        assert not [c for c in layout.each_cell() if "error" in c.name.lower()]
        t = pya.DCplxTrans(1, rot, False, 0, 0)
        ports[name] = {k: (t * p.pos, t * p.dir) for k, p in cell_ports(cell).items()}
    assert set(ports[KQC]) == set(ports[NEW]) == {"coupler_1", "coupler_2", "coupler_3", "drive"}
    for k, (pos, d) in ports[KQC].items():
        assert ports[NEW][k][0].distance(pos) < 1e-6
        assert (ports[NEW][k][1] - d).length() < 1e-6


def test_same_parameters_but_the_junction():
    kqc, new = resolve_cell(KQC).get_schema(), resolve_cell(NEW).get_schema()
    assert set(new) - set(kqc) == {"junction_params"}
    assert {k for k in kqc if kqc[k].default != new[k].default} == {"junction_type"}
    assert new["junction_type"].default == "Quantcore Squid"
    choices = set(new["junction_type"].kwargs["choices"])
    assert {"Quantcore Junction", "Quantcore Squid", "Trilayer Junction", "Trilayer Squid"} <= choices


def test_junction_layers_are_trilayer_not_manhattan():
    lk, ck = _build(KQC)
    ln, cn = _build(NEW)
    assert _area(lk, ck, "SIS_shadow") > 0 and _area(ln, cn, "SIS_shadow") == 0  # KQC's Manhattan shadow
    assert _area(lk, ck, "SIS_junction") > 0
    for layer in ("SIS_junction", "SIS_junction_2"):  # fab 2/0 and 4/0
        assert _area(ln, cn, layer) > 0
    for no in (50, 51, 52, 53):  # spacer and gradient
        assert _plain(ln, cn, no) > 0, no
    assert _plain(lk, ck, 50) == 0


def test_junction_lands_where_kqc_squid_lands():
    lk, ck = _build(KQC)
    ln, cn = _build(NEW)
    bk, bn = ck.dbbox_per_layer(lk.layer(*_info(lk, "SIS_junction"))), cn.dbbox_per_layer(
        ln.layer(*_info(ln, "SIS_junction"))
    )
    assert bk.center().distance(bn.center()) < 15  # both on the squid_angle site, same ring-to-disc gap


def _info(layout, name):
    from kqcircuits.defaults import default_faces

    info = default_faces["1t1"][name]
    return (info.layer, info.datatype)


def test_junction_params_size_the_junction():
    _, _ = _build(NEW, junction_params=json.dumps({"lj_nH": 12.0}))
    from quantcore_circuits.lom.fragment import drawn_junction

    assert drawn_junction({"junction_type": "Quantcore Squid", "junction_params": {"lj_nH": 12.0}})[0] == pytest.approx(
        12.0, rel=0.02
    )


def test_listed_in_the_catalog_as_a_qubit():
    c = find(NEW)
    assert c is not None and c.category == "qubit" and c.source == "quantcore"


def test_lom_junction_from_the_pdk():
    from quantcore_circuits.lom import lom_from_design
    from quantcore_circuits.lom.fragment import lom_model

    assert lom_model(NEW) is not None
    design = {
        "schema": "qcc/0.1", "name": "t", "pdk": "quantcore_nb_sapphire_v1",
        "chip": {"box": [0, 0, 7500, 7500], "params": {"name_chip": "T"}},
        "instances": {"Q": {"cell": NEW, "place": {"at": [3000, 3000], "rot": 0}}}, "routes": {},
    }
    branches = lom_from_design(design).model.branches
    j = branches["J_Q"]
    assert j.type == "SQUID" and j.nodes == ("Q.island1", "Q.island2")
    assert j.value["Lj_nH"] == pytest.approx(6.73, abs=0.02) and j.value["Cj_fF"] == 15.0
    assert "PDK" in j.value["source"]
    # the other branches are KQC's
    design["instances"]["Q"]["cell"] = KQC
    kqc = lom_from_design(design).model.branches
    assert {k for k in branches if k != "J_Q"} == {k for k in kqc if k != "J_Q"}
    design["instances"]["Q"]["cell"] = NEW
    design["instances"]["Q"]["junction"] = {"Lj_nH": 9.0, "Cj_fF": 2.0}
    assert lom_from_design(design).model.branches["J_Q"].value["Lj_nH"] == 9.0  # a design value wins


@pytest.mark.parametrize(
    "pin, at, direction, ab",
    [
        ("coupler_1", (310.099, -112.867), (math.cos(math.radians(340)), math.sin(math.radians(340))), None),
        ("coupler_2", (165.0, 285.788), (0.5, math.sqrt(3) / 2), (10, 6)),
    ],
)
def test_oblique_join_has_no_sliver(pin, at, direction, ab):
    res, port, a, b, _, fab = _join(_design(NEW, pin, at, direction, ab=ab))
    assert _route_merges(res, port)
    assert _slivers(fab, port, a, b, res.layout.dbu) == 0.0


def _audit_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_sim_export.py"
    spec = importlib.util.spec_from_file_location("check_sim_export", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("analysis", ["q3d_cmatrix", "hfss_eigenmode"])
def test_sim_export_is_clean(tmp_path, analysis):
    audit = _audit_module()
    comp = find(NEW)
    context, data, kind = audit.scratch_designs(comp)[0]
    data["instances"]["X"]["junction"] = {"Lj_nH": 10.0, "Cj_fF": 2.0}  # explicit: independent of the PDK default
    path = tmp_path / "d.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    row = audit.export_case(path, kind, analysis, tmp_path / "job")
    assert row["export"] == "ok", row["reason"]
    assert row["check"]["errors"] == [] and row["kqc_warnings"] == []
    assert ("junction", "X.junction") in [tuple(p) for p in row["ports"]]  # the junction port bridges the gap
