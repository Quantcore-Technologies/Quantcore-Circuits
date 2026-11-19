"""Per-instance values of the KLayout plugin: collecting target / LOM / FEM / consensus and colouring by error.
Pure logic (no KLayout)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kplugin" / "python"))

from qcc_kplugin import instance_values as iv  # noqa: E402


@pytest.mark.parametrize(
    ("value", "target", "tol", "expected"),
    [(5.11, 5.1, 0.02, "ok"), (5.13, 5.1, 0.02, "near"), (5.2, 5.1, 0.02, "off"), (5.1, 5.1, 0.02, "ok"),
     (None, 5.1, 0.02, "none"), (5.1, None, 0.02, "none"), (5.1, 5.1, None, "none")],
)
def test_grade(value, target, tol, expected):
    assert iv.grade(value, target, tol) == expected


def src():
    return {
        "targets": {"Q1": {"f_q_GHz": 5.1, "alpha_MHz": -220}, "R1": {"f_GHz": 7.2, "chi_MHz": -1.0}},
        "lom": {"Q1.f_q_GHz": 5.227, "Q1.alpha_MHz": -321.9, "R1.f_GHz": 7.205, "R1.chi_MHz": -0.95, "Q1.EJ_GHz": 13},
        "results": {"Q1": {"params": [{"key": "Q1.f_q_GHz", "value": 5.105, "source": "hfss_eigenmode"},
                                      {"key": "Q1.alpha_MHz", "value": -300.0, "source": "lom"}]}},
        "consensus": [{"param": "Q1.alpha_MHz", "chosen": -321.5, "spread_rel": 0.0029,
                       "values": {"metal_lom": -321.9, "qucat": -321.0}}],
    }


def test_collect_values_targets_and_grades():
    out = iv.collect(src())
    q = {r["key"]: r for r in out["Q1"]}
    assert set(q) == {"f_q_GHz", "alpha_MHz"}  # EJ is not shown
    assert q["f_q_GHz"]["fem"] == 5.105 and q["f_q_GHz"]["lom"] == 5.227
    assert q["f_q_GHz"]["value"] == 5.105 and q["f_q_GHz"]["grade"] == "ok"  # judged on the FEM value
    assert q["alpha_MHz"]["fem"] is None and q["alpha_MHz"]["value"] == -321.9  # a "lom" source is not FEM
    assert q["alpha_MHz"]["grade"] == "off" and q["alpha_MHz"]["consensus"] == -321.5
    r = {x["key"]: x for x in out["R1"]}
    assert set(r) == {"f_GHz", "chi_MHz"} and r["f_GHz"]["tol"] == 0.01
    assert r["f_GHz"]["grade"] == "ok" and r["chi_MHz"]["grade"] == "ok"
    assert iv.worst(out["Q1"]) == "off" and iv.worst(out["R1"]) == "ok"


def test_fem_from_the_consensus_methods_and_value_order():
    s = {"targets": {}, "lom": {"Q1.f_q_GHz": 5.0},
         "consensus": [{"param": "Q1.f_q_GHz", "chosen": 5.2, "values": {"hfss": 5.3, "qucat": 5.1}}]}
    row = iv.collect(s)["Q1"][0]
    assert (row["fem"], row["lom"], row["value"], row["target"], row["grade"]) == (5.3, 5.0, 5.3, None, "none")
    s["consensus"][0]["values"] = {"qucat": 5.1}
    assert iv.collect(s)["Q1"][0]["value"] == 5.0  # no FEM: the LOM value
    s["lom"] = {}
    assert iv.collect(s)["Q1"][0]["value"] == 5.2  # only the consensus


def test_target_without_value_draws_nothing():
    assert iv.collect({"targets": {"Q1": {"f_q_GHz": 5.1}}, "lom": {}}) == {}


def test_texts():
    out = iv.collect(src())
    f_q = out["Q1"][0]
    assert iv.line(f_q) == "f_q 5.105 GHz  (target 5.1 ± 0.02)"
    lom, fem, cons, tgt, grade = iv.detail(out["Q1"][1])
    assert (lom, fem, tgt, grade) == ("-321.9", "–", "-220 ± 10", "off") and "spread 0.29 %" in cons
    text = iv.readout("Q1", out["Q1"])
    assert text.splitlines()[0] == "Q1" and "α" in text


def test_sources_read_the_files(tmp_path):
    (tmp_path / "d.json").write_text(json.dumps({"targets": {"Q1": {"f_q_GHz": 5.1}}}), encoding="utf-8")
    run = tmp_path / "build" / "d"
    run.mkdir(parents=True)
    (run / "lom.json").write_text(json.dumps({"params": {"Q1.f_q_GHz": 5.11}}), encoding="utf-8")
    (run / "consensus.json").write_text("not json", encoding="utf-8")
    s = iv.sources(tmp_path / "d.json", {"results": {}})
    assert s["lom"] == {"Q1.f_q_GHz": 5.11} and s["consensus"] == []
    assert iv.collect(s)["Q1"][0]["grade"] == "ok"
    assert iv.sources(tmp_path / "missing.json")["targets"] == {}
