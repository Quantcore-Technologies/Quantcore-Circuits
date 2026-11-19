"""``qcc selftest``: the check that runs after an install."""

import json

from typer.testing import CliRunner

from quantcore_circuits import selftest
from quantcore_circuits.cli import app


def test_design_resource_is_a_valid_design():
    from quantcore_circuits.design import load_design

    d = load_design(selftest.DESIGN_RESOURCE)
    assert {"Q1", "R1"} <= set(d.instances) | set(d.routes)


def test_pyproject_ships_the_selftest_design():
    from pathlib import Path

    text = (Path(selftest.__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    assert "data/*.json" in text


def test_selftest_runs_and_reports_each_check(monkeypatch):
    # the chip checks need only the core; the extras may be missing on a minimal env
    res = CliRunner().invoke(app, ["selftest", "--allow-missing", "--json"])
    assert res.exit_code == 0, res.output
    checks = {c["name"]: c for c in json.loads(res.output[res.output.index("["):])}
    for name in ("build Q1 + R1 chip", "DRC", "LOM netlist", "export sim job (q3d_cmatrix)", "ansysedt"):
        assert name in checks
    assert checks["build Q1 + R1 chip"]["status"] == "ok"
    assert checks["DRC"]["status"] == "ok"
    assert checks["ansysedt"]["status"] in ("ok", "skip")  # never FAIL, never started


def test_selftest_exits_non_zero_on_a_failure(monkeypatch):
    monkeypatch.setitem(selftest.IMPORTS, "analysis", [("nonexistent", "no_such_module_qcc", "no-such-dist")])
    res = CliRunner().invoke(app, ["selftest"])
    assert res.exit_code == 1
    assert "FAIL" in res.output and "import nonexistent" in res.output
    # the same missing extra is only a skip with --allow-missing
    res = CliRunner().invoke(app, ["selftest", "--allow-missing"])
    assert res.exit_code == 0, res.output


def test_selftest_stops_when_core_is_broken(monkeypatch):
    monkeypatch.setitem(selftest.IMPORTS, "core", [("nonexistent", "no_such_module_qcc", "no-such-dist")])
    results = selftest.run_checks()
    assert any(c.status == "FAIL" for c in results)
    assert not any(c.name.startswith("build") for c in results)
