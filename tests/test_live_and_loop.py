"""klive client, watch/rebuild, optimiser, KLayout-plugin sync, fab export, CLI."""

import copy
import json
import socket
import sys
import threading
import time
from pathlib import Path

import klayout.db as db
import pytest
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]


# ---- klive ----------------------------------------------------------------------------------------------------------
def test_klive_message_format(tmp_path):
    from quantcore_circuits.live.klive import send_to_klive

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    got = {}

    def serve():
        conn, _ = srv.accept()
        data = b""
        while not data.endswith(b"\n"):
            data += conn.recv(4096)
        got["msg"] = json.loads(data)
        conn.sendall(json.dumps({"type": "open", "file": got["msg"]["gds"]}).encode())
        conn.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    oas = tmp_path / "x.oas"
    reply = send_to_klive(oas, port=port)
    t.join(2)
    assert got["msg"] == {"gds": str(oas.resolve()), "keep_position": True}  # klive needs keep_position
    assert reply["type"] == "open"


def test_klive_unavailable_is_clear():
    from quantcore_circuits.live.klive import KliveUnavailable, send_to_klive

    with pytest.raises(KliveUnavailable, match="klive"):
        send_to_klive("x.oas", port=1, timeout=0.2)


# ---- watch ----------------------------------------------------------------------------------------------------------
def test_rebuild_keeps_last_good_layout(example_dict, tmp_path):
    from quantcore_circuits.live.watch import rebuild

    src, out, log = tmp_path / "d.json", tmp_path / "d.oas", []
    src.write_text(json.dumps(example_dict))
    assert rebuild(src, out, klive=False, log=log.append)
    good = out.read_bytes()
    bad = copy.deepcopy(example_dict)
    bad["routes"]["R1"]["length"] = 100  # too short → build error
    src.write_text(json.dumps(bad))
    assert not rebuild(src, out, klive=False, log=log.append)
    assert out.read_bytes() == good and "FAILED" in log[-2]


# ---- optimiser ------------------------------------------------------------------------------------------------------
def test_optimise_hits_target_with_few_evaluations(example_path):
    from quantcore_circuits.optimise import get_knob, optimise, set_knob

    calls = []

    def evaluate(d):  # surrogate: f_q falls with cross length (C_Σ grows), mildly nonlinear
        L = d.instances["Q1"].params["cross_length"]
        calls.append(L)
        return {"Q1": {"f_q_GHz": 7.6 - 0.0085 * L + 2e-6 * L**2}}

    res = optimise(
        example_path,
        {"Q1.cross_length": (150, 450)},
        {"Q1.f_q_GHz": 5.4},
        evaluate,
        tolerance={"Q1.f_q_GHz": 0.05},
        max_iter=6,
        log=lambda *_: None,
    )
    assert res.converged and len(calls) <= 6
    assert abs(res.history[-1].error["Q1.f_q_GHz"]) <= 0.05 or any(
        abs(it.error["Q1.f_q_GHz"]) <= 0.05 for it in res.history
    )
    d2 = set_knob(res.design, "R1.length", 4300)
    assert get_knob(d2, "R1.length") == 4300 and get_knob(d2, "Q1.claw_length") == 100  # default from cell


# ---- KLayout plugin sync (GUI-free part) ----------------------------------------------------------------------------
def test_kplugin_sync_moved_instance(example_path, tmp_path):
    sys.path.insert(0, str(ROOT / "kplugin" / "python"))
    from qcc_kplugin import design_io

    import quantcore_circuits as qcc

    oas = qcc.write_layout(qcc.build(example_path), tmp_path / "chip.oas")
    ly = db.Layout()
    ly.read(str(oas))
    chip = design_io.find_chip_cell(ly.top_cell())
    for inst in chip.each_inst():  # "drag" Q1 by (+100, -50) and rotate it
        if inst.property("id") == "Q1":
            inst.transform(db.DCplxTrans(1, 0, False, 100, -50))
    design = design_io.read_design(example_path)
    design, report = design_io.sync_placements(design, chip)
    assert design["instances"]["Q1"]["place"]["at"] == [3075.0, 2150.0]
    assert report and report[0].startswith("Q1")
    design, _ = design_io.sync_placements(design, chip)
    assert design["instances"]["PAD_W"]["place"]["at"] == [1125, 3750]  # untouched


# ---- fab export -----------------------------------------------------------------------------------------------------
def test_fab_export_layers_and_polarity(example_path):
    from quantcore_circuits.assembly import build
    from quantcore_circuits.layouts.wafers.fab_export import fab_regions

    r = build(example_path)
    neg = fab_regions(r.cell)
    assert {"M1", "JJ_STRAIGHT", "M3", "JJ_BENT", "HSQ"} <= {k for k, v in neg.items() if not v.is_empty()}
    cheese = neg["M1"] - fab_regions(r.cell, grid=False)["M1"]  # the PDK band the build drew
    assert (neg["M1"] - cheese - neg["M3"]).is_empty()  # M3 envelope contains M1 (the cheese stays outside it)
    box = db.DBox(0, 0, 7500, 7500)
    pos = fab_regions(r.cell, polarity={"M1": "positive"}, box=box)
    total = box.area() / (r.layout.dbu**2)
    assert pos["M1"].area() + neg["M1"].area() == pytest.approx(total, rel=1e-6)


# ---- CLI ------------------------------------------------------------------------------------------------------------
def test_cli_smoke(example_path, tmp_path):
    from quantcore_circuits.cli import app

    runner = CliRunner()
    assert "quantcore-circuits" in runner.invoke(app, ["--version"]).output
    out = runner.invoke(app, ["design", "validate", str(example_path)])
    assert out.exit_code == 0 and "4 instances" in out.output
    ports = json.loads(runner.invoke(app, ["design", "ports", str(example_path), "--json"]).output)
    assert ports["Q1.claw_n"]["dir"] == pytest.approx(90)
    out = runner.invoke(app, ["build", str(example_path), "-o", str(tmp_path / "c.oas")])
    assert out.exit_code == 0 and (tmp_path / "c.oas").exists()


def test_fab_export_kqc_demo_chip_both_polarities():
    """M1 acceptance: a KQC demo chip exports to the fab layers in both polarities (area invariant)."""
    from kqcircuits.chips.demo import Demo

    from quantcore_circuits.layouts.wafers.fab_export import fab_regions

    layout = db.Layout()
    chip = Demo.create(layout, with_grid=False)
    box = db.DBox(0, 0, 10000, 10000)
    neg = fab_regions(chip, box=box)
    pos = fab_regions(chip, polarity={name: "positive" for name in neg}, box=box)
    total = box.area() / (layout.dbu**2)
    for name in ("M1", "M3", "JJ_STRAIGHT"):
        assert not neg[name].is_empty()
        assert pos[name].area() + neg[name].area() == pytest.approx(total, rel=1e-6)
        assert (pos[name] & neg[name]).is_empty()  # XOR invariant: the two polarities never overlap


@pytest.mark.slow
def test_fab_export_cheese_adds_ground_grid(example_path):
    from quantcore_circuits.assembly import build
    from quantcore_circuits.layouts.wafers.fab_export import fab_regions

    plain_chip, cheese_chip = build(example_path), build(example_path, with_grid=True)  # keep layouts alive
    plain = fab_regions(plain_chip.cell)["M1"]
    cheese = fab_regions(cheese_chip.cell)["M1"]
    assert cheese.area() > plain.area() and (plain - cheese).is_empty()


def test_watch_rebuilds_when_the_design_changes(example_dict, tmp_path):
    """``qcc watch`` (headless, no klive): one build at start, one more after the file changes."""
    from quantcore_circuits.live.watch import watch

    src, out, log = tmp_path / "d.json", tmp_path / "d.oas", []
    src.write_text(json.dumps(example_dict))
    t = threading.Thread(
        target=watch,
        args=(src, out),
        kwargs=dict(interval=0.05, debounce=0.05, klive=False, max_builds=2, log=log.append),
    )
    t.start()
    for _ in range(400):  # first build done?
        if any("built" in m for m in log):
            break
        time.sleep(0.05)
    changed = copy.deepcopy(example_dict)
    changed["instances"]["Q1"]["params"]["cross_length"] = 320
    src.write_text(json.dumps(changed))
    t.join(timeout=60)
    assert not t.is_alive()
    assert sum("built" in m for m in log) == 2 and out.exists()


def test_headless_designer_rebuild_meets_the_live_loop_target(example_path, tmp_path):
    """M4 in the VM (no GUI): a warm ``Designer(live=False)`` edit + rebuild stays under the 2 s target (≈ 0.1 s)."""
    import shutil

    from quantcore_circuits.designer import Designer

    d = Designer.load(shutil.copy(example_path, tmp_path / "d.json"), out=tmp_path / "d.oas", verbose=False)
    d.show()  # cold: imports, PCell registration
    times = []
    for length in (310, 320, 330):
        t0 = time.perf_counter()
        d["Q1"].set(cross_length=length)
        d.show()
        times.append(time.perf_counter() - t0)
    assert sorted(times)[1] < 2.0, times
