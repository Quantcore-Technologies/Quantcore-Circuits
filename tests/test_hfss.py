"""HFSS render path (no AEDT needed): whole-chip sim group, render command, project summary."""

from pathlib import Path

import pytest

from quantcore_circuits.sim_tools import hfss
from quantcore_circuits.sim_tools.builder import build_simulation, group_spec


def test_whole_chip_group_keeps_everything(example_path):
    from quantcore_circuits.design import load_design

    g = group_spec(load_design(example_path), "chip")
    assert set(g.select) >= {"Q1", "FL", "R1"} and all(v == "keep" for v in g.ports.values())


def test_whole_chip_eigenmode_ports(example_path):
    setup = build_simulation(example_path, "chip", "hfss_eigenmode")
    kinds = [(p.kind, p.name) for p in setup.ports]
    assert kinds[0] == ("junction", "Q1.junction")
    assert {n for k, n in kinds if k == "lumped"} == {"PAD_W.pad", "PAD_E.pad", "PAD_F.pad"}
    assert (setup.box.width(), setup.box.height()) == (7500, 7500)
    data = setup.simulation.get_port_data()
    assert all("polygon" in d for d in data)  # every port found its signal and ground edges
    assert data[0]["junction"] and data[0]["inductance"] == pytest.approx(12e-9)


def test_job_targets_aedt_2024_and_sapphire(example_path, tmp_path, monkeypatch):
    from quantcore_circuits.sim_tools import export_job

    monkeypatch.delenv("QCC_ANSYS_EXECUTABLE", raising=False)
    monkeypatch.setattr("quantcore_circuits.sim_tools.ansys.find_ansys_executable", lambda *a, **k: None)
    job = export_job(build_simulation(example_path, "Q1R1", "hfss_eigenmode"), tmp_path / "j")
    assert "v241" in (job / "simulation.bat").read_text()
    import json

    sim_name = json.loads((job / "job.json").read_text())["simulation_name"]
    sim = json.loads((job / f"{sim_name}.json").read_text())
    assert sim["material_dict"]["sapphire"]["permittivity"] == 10.25
    assert sim["layers"]["substrate_1"]["thickness"] == 650.0
    assert sim["tool"] == sim["ansys_tool"] == "eigenmode"


def test_render_command_non_graphical(tmp_path):
    (tmp_path / "job.json").write_text('{"simulation_name": "s"}')
    exe = Path("C:/AnsysEM/v242/Win64/ansysedt.exe")
    cmd = hfss.render_command(tmp_path, exe)
    assert cmd[1:3] == ["-ng", "-features=SF6694_NON_GRAPHICAL_COMMAND_EXECUTION"]
    assert cmd[-3:] == [f"scripts/{hfss.RENDER_SCRIPT}", "-ScriptArgs", "s.json"]
    assert "-ng" not in hfss.render_command(tmp_path, exe, graphical=True)
    assert hfss.aedt_env()["ANSYSEM_FEATURE_SF6694_NON_GRAPHICAL_COMMAND_EXECUTION_ENABLE"] == "1"
    compile(hfss._RENDER_SOURCE, "qcc_render.py", "exec")  # noqa: SLF001


def test_aedt_version_parsing():
    from quantcore_circuits.sim_tools.ansys import aedt_version

    assert aedt_version(r"C:\Program Files\AnsysEM\v242\Win64\ansysedt.exe") == 242
    assert aedt_version(r"D:\SOFTWARE\AnsysEM\AnsysEM21.1\Win64\ansysedt.exe") == 211
