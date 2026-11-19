"""The KQCircuits files a PyPI kqcircuits lacks (``quantcore_circuits.kqc_files``): KQC's own folder, the
``QCC_KQC_SCRIPTS`` folder, or the cache ``qcc kqc-files`` fills. No network: the fetch reads a local folder or
zip."""

import io
import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from quantcore_circuits import kqc_files


def _fake_checkout(root: Path) -> Path:
    """A KQCircuits checkout with stub scripts and font: returns its ``klayout_package/python``."""
    py = root / "klayout_package" / "python"
    for n in ("simulations/ansys", "simulations/post_process", "simulations/elmer", "simulations/elmer_modules"):
        (py / "scripts" / n).mkdir(parents=True)
        (py / "scripts" / n / "x.py").write_text("# stub\n", encoding="utf-8")
    (py / kqc_files.FONT).parent.mkdir(parents=True)
    (py / kqc_files.FONT).write_bytes(b"font")
    return py


@pytest.fixture
def pypi_kqc(monkeypatch, tmp_path):
    """KQC as a PyPI install sees it: no scripts folder, no label font."""
    from kqcircuits import defaults
    from kqcircuits.util import label_polygons

    gone = tmp_path / "nowhere" / "scripts" / "simulations"
    monkeypatch.setattr(defaults, "ANSYS_SCRIPT_PATHS", [gone / "ansys", gone / "post_process"])
    monkeypatch.setattr(defaults, "ELMER_SCRIPT_PATHS", [gone / "elmer", gone / "post_process"])
    monkeypatch.setattr(defaults, "SIM_SCRIPT_PATH", gone)
    monkeypatch.setattr(label_polygons, "OAS_PATH", str(tmp_path / "nowhere" / "font_polygons.oas"))
    monkeypatch.setenv(kqc_files.ENV_CACHE, str(tmp_path / "cache"))
    monkeypatch.delenv(kqc_files.ENV_SCRIPTS, raising=False)
    monkeypatch.setattr(kqc_files, "kqc_version", lambda: "9.9.9")
    return defaults, label_polygons


def test_own_files_win():
    from kqcircuits import defaults

    own = Path(defaults.ANSYS_SCRIPT_PATHS[0]).parents[1]
    if not (own / "simulations" / "ansys").is_dir():
        pytest.skip("kqcircuits here has no scripts of its own (a PyPI install)")
    assert kqc_files.find_kqc_scripts() == (own, "kqcircuits")
    before = list(defaults.ANSYS_SCRIPT_PATHS)
    assert kqc_files.ensure_kqc_scripts() == own
    assert defaults.ANSYS_SCRIPT_PATHS == before  # untouched


def test_missing_files_say_what_to_run(pypi_kqc):
    assert kqc_files.find_kqc_scripts() == (None, "")
    assert kqc_files.ensure_kqc_data() is None
    with pytest.raises(FileNotFoundError, match="qcc kqc-files"):
        kqc_files.ensure_kqc_scripts()


def test_env_checkout_is_used_and_kqc_points_at_it(pypi_kqc, tmp_path, monkeypatch):
    defaults, label_polygons = pypi_kqc
    py = _fake_checkout(tmp_path / "KQCircuits")
    monkeypatch.setenv(kqc_files.ENV_SCRIPTS, str(py / "scripts"))
    ansys_list = defaults.ANSYS_SCRIPT_PATHS
    assert kqc_files.ensure_kqc_scripts() == py / "scripts"
    sims = py / "scripts" / "simulations"
    assert ansys_list == [sims / "ansys", sims / "post_process"]  # changed in place
    assert defaults.SIM_SCRIPT_PATH == sims
    assert kqc_files.ensure_kqc_data() == py / kqc_files.FONT
    assert label_polygons.OAS_PATH == str(py / kqc_files.FONT)


def test_fetch_from_a_checkout_fills_the_cache(pypi_kqc, tmp_path):
    _fake_checkout(tmp_path / "KQCircuits")
    dest = kqc_files.fetch_kqc_files(source=tmp_path / "KQCircuits")
    assert dest == tmp_path / "cache" / "kqcircuits-9.9.9"
    assert kqc_files.find_kqc_scripts() == (dest / "scripts", "cache")
    assert kqc_files.ensure_kqc_data() == dest / kqc_files.FONT
    assert kqc_files.fetch_kqc_files(source=tmp_path / "missing") == dest  # cached: not fetched again


def test_fetch_from_a_source_zip_takes_only_scripts_and_font(pypi_kqc, tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in ("ansys/a.py", "post_process/p.py", "elmer/e.py"):
            z.writestr(f"KQCircuits-9.9.9/klayout_package/python/scripts/simulations/{n}", "# stub\n")
        z.writestr(f"KQCircuits-9.9.9/klayout_package/python/{kqc_files.FONT}", "font")
        z.writestr("KQCircuits-9.9.9/klayout_package/python/kqcircuits/elements/element.py", "not copied\n")
        z.writestr("KQCircuits-9.9.9/README.md", "not copied\n")
    src = tmp_path / "v9.9.9.zip"
    src.write_bytes(buf.getvalue())
    dest = kqc_files.fetch_kqc_files(source=src)
    assert sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file()) == [
        kqc_files.FONT, "scripts/simulations/ansys/a.py", "scripts/simulations/elmer/e.py",
        "scripts/simulations/post_process/p.py"]


def test_zip_member_outside_the_cache_is_refused(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("K/klayout_package/python/scripts/../../../../evil.py", "x")
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as z, pytest.raises(ValueError, match="unsafe"):
        kqc_files._extract(z, tmp_path / "dest")


def test_cli_kqc_files_from_a_checkout(pypi_kqc, tmp_path):
    from quantcore_circuits.cli import app

    _fake_checkout(tmp_path / "KQCircuits")
    res = CliRunner().invoke(app, ["kqc-files", "--source", str(tmp_path / "KQCircuits")])
    assert res.exit_code == 0, res.output
    assert "kqcircuits-9.9.9" in res.output
