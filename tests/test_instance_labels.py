"""The instance name labels (KQC's ``instance_names`` layer): their height is a build option (``qcc build
--label-height``, ``DesignChip.instance_label_height``); the default is KQC's own call, so a default build is unchanged.
The KLayout plugin passes its Settings value (checked in a real KLayout by a GUI probe)."""

import re
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quantcore_circuits.assembly import build
from quantcore_circuits.cli import app
from quantcore_circuits.layouts.chips.design_chip import KQC_LABEL_HEIGHT, LABEL_CAP_RATIO

pya = pytest.importorskip("klayout.db")

ROOT = Path(__file__).resolve().parents[1]


def _layer(result, layer: int):
    ly = result.layout
    r = pya.Region()
    for i in ly.layer_indexes():
        if ly.get_info(i).layer == layer and ly.get_info(i).datatype == 0:
            r += pya.Region(result.top.begin_shapes_rec(i))
    r.merge()
    return r


def _label_heights(result) -> set[float]:
    """The heights of the label cells (KLayout's Basic TEXT) the chip places, one per named instance."""
    ly = result.layout
    return {round(ly.cell(i.cell_index).dbbox().height(), 3) for i in result.cell.each_inst()
            if ly.cell(i.cell_index).name.startswith("TEXT")}


def test_label_height_option(example_path):
    default = build(example_path)
    small = build(example_path, instance_label_height=70.0)
    none = build(example_path, instance_label_height=0.0)
    assert KQC_LABEL_HEIGHT == pytest.approx(400 * LABEL_CAP_RATIO)
    assert _label_heights(default) == {KQC_LABEL_HEIGHT}  # KQC's magnification 400: 280 µm capitals
    assert _label_heights(small) == {70.0}
    assert _label_heights(none) == set() and _layer(none, 222).is_empty()
    assert not _layer(default, 222).is_empty()
    for layer in (1, 2, 3, 4):  # the label layer only: every drawn layer is the same
        a, b = _layer(default, layer), _layer(small, layer)
        assert (a ^ b).is_empty(), layer
    assert default.hash == small.hash == none.hash  # the design is unchanged


def test_cli_label_height(example_path, tmp_path):
    runner = CliRunner()
    out = tmp_path / "small.oas"
    res = runner.invoke(app, ["build", str(example_path), "-o", str(out), "--label-height", "70"])
    assert res.exit_code == 0, res.output
    assert out.exists()
    bad = runner.invoke(app, ["build", str(example_path), "-o", str(tmp_path / "bad.oas"), "--label-height", "-1"])
    # on GitHub Actions Typer forces rich colours, and its option highlighter splits "--label-height" with ANSI codes
    assert bad.exit_code != 0 and "label-height" in re.sub(r"\x1b\[[0-9;]*m", "", bad.output)


def test_plugin_passes_the_settings_height(monkeypatch):
    sys.path.insert(0, str(ROOT / "kplugin" / "python"))
    from qcc_kplugin import session  # pylint: disable=import-outside-toplevel

    values = {}
    monkeypatch.setattr(session, "config", lambda key, default="": values.get(key) or default)
    assert session.label_args() == ["--label-height", "70"]  # the plugin's default (KQC: 280)
    values[session.CFG_LABEL_HEIGHT] = "0"
    assert session.label_args() == ["--label-height", "0"]
    values[session.CFG_LABEL_HEIGHT] = "abc"
    assert session.label_height() == session.DEFAULT_LABEL_HEIGHT
    text = (ROOT / "kplugin" / "python" / "qcc_kplugin" / "session.py").read_text(encoding="utf-8")
    assert '"--keep-going", *label_args()' in text and '"--no-klive", *label_args()' in text
