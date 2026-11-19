"""A failed route must not block the design: ``build(keep_going=True)``, last good routes, LOM, DRC, fab export."""

import json
import warnings

import pytest

from quantcore_circuits.assembly import build, last_good, plan_design, write_layout
from quantcore_circuits.assembly.drc import check
from quantcore_circuits.design import Design
from quantcore_circuits.route.router import RoutingError

BAD_NODES = [[2400, 2500], [2410, 2510]]  # 14 µm apart: far too short for the bends


def broken(example_dict, route="FLUX", nodes=BAD_NODES):
    d = example_dict
    d["routes"][route]["nodes"] = nodes
    return d


def test_strict_build_still_raises(example_dict):
    with pytest.raises(RoutingError, match="bends need"):
        build(broken(example_dict))


def test_keep_going_builds_everything_else(example_dict, tmp_path):
    import copy

    clean = copy.deepcopy(example_dict)
    r = build(broken(example_dict), keep_going=True)
    assert set(r.failed_routes) == {"FLUX"}
    assert "FLUX" not in r.plan.routes and set(r.route_lengths()) == {"FL", "R1"}
    assert r.failed_routes["FLUX"].error.startswith("route FLUX: ")
    # the failed route is not in the layout, the others are
    ids = {i.property("id") for i in r.cell.each_inst()} - {None}
    assert "FLUX" not in ids and {"FL", "R1", "Q1"} <= ids
    out = write_layout(r, tmp_path / "chip.oas")
    side = json.loads(out.with_name("chip.qcc.json").read_text(encoding="utf-8"))
    assert "FLUX" not in side["routes"]
    f = side["failed_routes"]["FLUX"]
    assert "bends need" in f["error"] and f["last_good"] is None
    # shaped like a built route, so the plugin's route handles work on it: ends and nodes, indices of the nodes
    assert f["polyline"][1:3] == BAD_NODES and f["waypoint_index"] == [1, 2] and f["waypoints"] == BAD_NODES
    assert any(i["rule"] == "route_failed" and i["objects"] == ["FLUX"] for i in side["drc"])
    ok = write_layout(build(clean, keep_going=True), tmp_path / "c.oas")
    assert "failed_routes" not in json.loads(ok.with_name("c.qcc.json").read_text(encoding="utf-8"))  # clean: no field


def test_last_good_route_survives_a_failing_rebuild(example_dict, tmp_path):
    import copy

    good = build(copy.deepcopy(example_dict), keep_going=True)
    out = write_layout(good, tmp_path / "chip.oas")
    store = last_good.load(last_good.store_path(out))
    assert set(store) == {"FL", "R1", "FLUX"} and store["FLUX"]["length"] == pytest.approx(good.plan.routes["FLUX"].length)
    bad = build(broken(example_dict), layout=None, keep_going=True, last_good=store)
    assert bad.failed_routes["FLUX"].last_good["polyline"] == store["FLUX"]["polyline"]
    write_layout(bad, out)
    again = last_good.load(last_good.store_path(out))
    assert again["FLUX"] == store["FLUX"]  # kept while it fails
    assert json.loads(out.with_name("chip.qcc.json").read_text(encoding="utf-8"))["failed_routes"]["FLUX"][
        "last_good"]["length"] == pytest.approx(store["FLUX"]["length"])
    # the route builds again: its entry is replaced
    fixed = copy.deepcopy(example_dict)
    fixed["routes"]["FLUX"]["nodes"] = [{"at": [2964.5, 1800.0], "a": 1, "b": 7.5}]
    write_layout(build(fixed, keep_going=True, last_good=again), out)
    assert last_good.load(last_good.store_path(out))["FLUX"]["polyline"] != store["FLUX"]["polyline"]


def test_route_hanging_on_a_failed_route_fails_with_its_own_reason(example_dict):
    r = build(broken(example_dict, "FL", [[2000, 3900], [2010, 3910]]), keep_going=True)
    assert set(r.failed_routes) == {"FL", "R1"}
    assert "hangs on route 'FL'" in r.failed_routes["R1"].error or "hangs on route 'FL'" in r.failed_routes["R1"].error
    assert r.failed_routes["R1"].error.startswith("route R1: ")
    assert set(r.route_lengths()) == {"FLUX"}


def test_lom_uses_the_last_good_route_and_warns(example_dict, tmp_path):
    import copy

    from quantcore_circuits.lom import lom_from_design

    design_path = tmp_path / "chip.json"
    design_path.write_text(json.dumps(example_dict), encoding="utf-8")
    good = build(design_path, keep_going=True)
    write_layout(good, tmp_path / "build" / "chip.oas")  # where the plugin's builds keep the store
    lom_ok = lom_from_design(design_path)
    d = copy.deepcopy(example_dict)
    d["routes"]["R1"]["nodes"] = [[2975, 3000], [2985, 3010]]
    design_path.write_text(json.dumps(d), encoding="utf-8")
    with pytest.warns(RuntimeWarning, match="route R1 failed to build"):
        lom = lom_from_design(design_path)
    assert any(n.startswith("WARNING: route R1") for n in lom.notes)
    assert set(lom.model.branches) == set(lom_ok.model.branches)  # the line is still in the circuit
    # without a stored last good route a failed route stays an error that names it
    last_good.store_path(tmp_path / "build" / "chip.oas").unlink()
    with pytest.raises(RoutingError, match="route R1"):
        lom_from_design(design_path)


def test_resolve_names_a_failed_route_without_last_good(example_dict):
    plan = plan_design(Design.model_validate(broken(example_dict)), keep_going=True)
    with pytest.raises(RoutingError, match=r"no route for FLUX .*no earlier good route"):
        last_good.resolve(plan)


def test_drc_reports_the_failed_route_and_fab_export_refuses(example_dict, tmp_path):
    from quantcore_circuits.layouts.wafers.fab_export import export_fab

    r = build(broken(example_dict), keep_going=True)
    report = check(r, netlist=True)
    assert [i.rule for i in report.issues if i.severity == "error"].count("route_failed") == 1
    assert not any(i.rule in ("open", "open_conductor") and "FLUX" in " ".join(i.objects) for i in report.issues)
    with pytest.raises(RoutingError, match="fab export refused: route FLUX"):
        export_fab(r, tmp_path / "fab.oas")
    assert not (tmp_path / "fab.oas").exists()
    assert check(broken(example_dict) | {}, netlist=False, keep_going=True).issues  # design dicts too


def test_cli_build_keep_going_option(example_dict, tmp_path):
    from typer.testing import CliRunner

    from quantcore_circuits.cli import app

    path = tmp_path / "chip.json"
    path.write_text(json.dumps(broken(example_dict)), encoding="utf-8")
    runner = CliRunner()
    strict = runner.invoke(app, ["build", str(path), "-o", str(tmp_path / "s.oas")])
    assert strict.exit_code != 0 and not (tmp_path / "s.oas").exists()  # the default stays strict
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = runner.invoke(app, ["build", str(path), "-o", str(tmp_path / "k.oas"), "--keep-going"])
    assert res.exit_code == 0, res.output
    assert "FAILED route FLUX" in res.output and (tmp_path / "k.oas").exists()
    assert (tmp_path / "k.last_good_routes.json").exists()
