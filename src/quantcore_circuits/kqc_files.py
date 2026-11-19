"""KQCircuits files that the ``kqcircuits`` wheel on PyPI does not ship, taken from KQCircuits itself.

* The simulation scripts: KQC's ``export_ansys`` / ``export_elmer`` copy the scripts in
  ``kqcircuits.defaults.ANSYS_SCRIPT_PATHS`` / ``ELMER_SCRIPT_PATHS`` (and ``SIM_SCRIPT_PATH / "elmer_modules"``) into
  each job folder. They live in the KQCircuits repository (``klayout_package/python/scripts``), outside the package.
* ``kqcircuits/util/font_polygons.oas``: the font of KQC's polygon labels (``ChipFrame`` and the chips built on it).

A KQCircuits git checkout (editable install) or KQC's KLayout Salt package has them. quantcore-circuits copies none of
KQCircuits' code: it uses KQCircuits' own files, found in this order:

1. KQC's own location (a checkout, an editable install, ``KQC_ROOT_PATH``);
2. ``QCC_KQC_SCRIPTS``: the ``klayout_package/python/scripts`` folder of a KQCircuits checkout (the font is read from
   the checkout's ``klayout_package/python/kqcircuits`` beside it);
3. the user cache that ``qcc kqc-files`` fills from the KQCircuits release of the installed version on GitHub
   (``QCC_CACHE_DIR`` moves the cache).

:func:`ensure_kqc_scripts` (before an export) and :func:`ensure_kqc_data` (when the KQC libraries load) point KQC at
the first one found, and change nothing when KQC has its own.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from importlib import metadata
from pathlib import Path

ENV_SCRIPTS = "QCC_KQC_SCRIPTS"
ENV_CACHE = "QCC_CACHE_DIR"
REPO = "https://github.com/iqm-finland/KQCircuits"
PY_IN_REPO = "klayout_package/python"
NEEDED = ("simulations/ansys", "simulations/post_process")  # what every AEDT export copies
FONT = "kqcircuits/util/font_polygons.oas"  # relative to klayout_package/python


def cache_root() -> Path:
    """The quantcore-circuits user cache (``QCC_CACHE_DIR``, else the platform's user cache folder)."""
    if os.environ.get(ENV_CACHE):
        return Path(os.environ[ENV_CACHE])
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "quantcore-circuits" / "cache"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "quantcore-circuits"


def kqc_version() -> str:
    """The installed kqcircuits version (``0.0.1`` for a checkout without git tags)."""
    return metadata.version("kqcircuits")


def cached_root(version: str | None = None) -> Path:
    """The cache folder of one kqcircuits version: ``scripts/`` and ``kqcircuits/util/font_polygons.oas``, laid out
    like ``klayout_package/python`` of a checkout."""
    return cache_root() / f"kqcircuits-{version or kqc_version()}"


def _complete(scripts: Path) -> bool:
    return all((scripts / n).is_dir() for n in NEEDED)


def _candidates() -> list[tuple[Path, str]]:
    """``klayout_package/python``-like roots other than KQC's own: ``QCC_KQC_SCRIPTS``'s parent, then the cache."""
    out = []
    if os.environ.get(ENV_SCRIPTS):
        out.append((Path(os.environ[ENV_SCRIPTS]).parent, ENV_SCRIPTS))
    try:
        out.append((cached_root(), "cache"))
    except metadata.PackageNotFoundError:
        pass
    return out


def find_kqc_scripts() -> tuple[Path | None, str]:
    """``(scripts folder, where)``: the first complete KQCircuits ``scripts`` folder, or ``(None, "")``."""
    from kqcircuits import defaults  # pylint: disable=import-outside-toplevel

    own = Path(defaults.ANSYS_SCRIPT_PATHS[0]).parents[1]
    if _complete(own):
        return own, "kqcircuits"
    if os.environ.get(ENV_SCRIPTS) and _complete(Path(os.environ[ENV_SCRIPTS])):
        return Path(os.environ[ENV_SCRIPTS]), ENV_SCRIPTS
    for root, where in _candidates():
        if where == "cache" and _complete(root / "scripts"):
            return root / "scripts", where
    return None, ""


def missing_message() -> str:
    try:
        ver = kqc_version()
    except metadata.PackageNotFoundError:
        ver = "?"
    return (
        f"KQCircuits' simulation scripts are not installed (kqcircuits {ver} from PyPI has no scripts/ folder). "
        f"Run `qcc kqc-files` once (it downloads them from {REPO} at tag v{ver}), or set {ENV_SCRIPTS} to "
        f"<KQCircuits checkout>/{PY_IN_REPO}/scripts."
    )


def ensure_kqc_scripts() -> Path:
    """Return the KQCircuits ``scripts`` folder the export uses; point KQC at it when it is not KQC's own.

    The lists in ``kqcircuits.defaults`` are changed in place, so the names KQC's export modules imported from it see
    the change; ``SIM_SCRIPT_PATH`` (a path imported by name) is also set in ``elmer_export``.
    """
    from kqcircuits import defaults  # pylint: disable=import-outside-toplevel

    scripts, where = find_kqc_scripts()
    if scripts is None:
        raise FileNotFoundError(missing_message())
    if where == "kqcircuits":
        return scripts
    sims = scripts / "simulations"
    defaults.ANSYS_SCRIPT_PATHS[:] = [sims / "ansys", sims / "post_process"]
    defaults.ELMER_SCRIPT_PATHS[:] = [sims / "elmer", sims / "post_process"]
    defaults.SIM_SCRIPT_PATH = sims
    try:
        from kqcircuits.simulations.export.elmer import elmer_export  # pylint: disable=import-outside-toplevel
    except ImportError:  # the Elmer export is optional
        return scripts
    elmer_export.SIM_SCRIPT_PATH = sims
    return scripts


def ensure_kqc_data() -> Path | None:
    """Point KQC's polygon-label font at KQCircuits' own file from ``QCC_KQC_SCRIPTS`` or the cache when the installed
    kqcircuits lacks it. Returns the font file in use (None when there is none; KQC then fails on a label)."""
    try:
        from kqcircuits.util import label_polygons  # pylint: disable=import-outside-toplevel
    except ImportError:
        return None
    if Path(label_polygons.OAS_PATH).is_file():
        return Path(label_polygons.OAS_PATH)
    for root, _where in _candidates():
        if (root / FONT).is_file():
            label_polygons.OAS_PATH = str(root / FONT)
            return root / FONT
    return None


def _extract(archive: zipfile.ZipFile, dest: Path) -> int:
    """Copy ``<top>/klayout_package/python/scripts/**`` and the font of a KQCircuits source archive into ``dest``
    (laid out like ``klayout_package/python``)."""
    n = 0
    root = dest.resolve()
    for info in archive.infolist():
        parts = info.filename.split("/", 1)
        if len(parts) < 2 or info.is_dir() or not parts[1].startswith(PY_IN_REPO + "/"):
            continue
        rel = parts[1][len(PY_IN_REPO) + 1 :]
        if not (rel.startswith("scripts/") or rel == FONT):
            continue
        target = (dest / rel).resolve()
        if root not in target.parents:  # a member that would land outside the cache folder
            raise ValueError(f"unsafe path in the archive: {info.filename}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(info))
        n += 1
    return n


def fetch_kqc_files(version: str | None = None, source: str | Path | None = None, force: bool = False) -> Path:
    """Fill the cache with KQCircuits' ``scripts`` folder and label font for ``version`` (default: the installed one).

    ``source``: a KQCircuits checkout (or its ``klayout_package/python`` folder), or a source zip, instead of the
    download of ``<REPO>/archive/refs/tags/v<version>.zip``. Returns the cache folder of that version.
    """
    version = version or kqc_version()
    dest = cached_root(version)
    if _complete(dest / "scripts") and (dest / FONT).is_file() and not force:
        return dest
    cache_root().mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".kqc_files_", dir=cache_root()))  # same disk as dest: the move is a rename
    try:
        work = tmp / "files"
        if source is not None and Path(source).is_dir():
            src = Path(source)
            src = src / PY_IN_REPO if (src / PY_IN_REPO).is_dir() else src
            if not _complete(src / "scripts"):
                raise FileNotFoundError(f"{source} is not a KQCircuits checkout (no {PY_IN_REPO}/scripts)")
            shutil.copytree(src / "scripts", work / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
            if (src / FONT).is_file():
                (work / FONT).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src / FONT, work / FONT)
        else:
            if source is not None:
                data = Path(source).read_bytes()
            else:
                url = f"{REPO}/archive/refs/tags/v{version}.zip"
                req = urllib.request.Request(url, headers={"User-Agent": "quantcore-circuits"})
                with urllib.request.urlopen(req, timeout=120) as r:  # noqa: S310 - fixed https URL
                    data = r.read()
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if not _extract(z, work):
                    raise FileNotFoundError(f"no {PY_IN_REPO}/scripts in the KQCircuits archive")
        if not _complete(work / "scripts"):
            raise FileNotFoundError(f"the KQCircuits scripts for {version} lack {', '.join(NEEDED)}")
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(work), str(dest))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return dest
