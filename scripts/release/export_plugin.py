"""Export the KLayout plugin (``kplugin/``) as a stand-alone Salt package.

KLayout's package manager (Salt) fetches one ref of a Git repository (depth 1) and downloads that commit's whole tree,
even when the URL names a sub-folder. So the plugin is published on its own orphan branch of this repository,
``klayout-plugin``, which holds the package alone with ``grain.xml`` at the root; the Salt URL is
``git+https://github.com/Quantcore-Technologies/Quantcore-Circuits.git[klayout-plugin]``. This script writes that tree
(into a worktree of the branch, or a folder for the release zip):

    python scripts/release/export_plugin.py --out ../Quantcore-Circuits-plugin --clean
    python scripts/release/export_plugin.py --out dist/plugin --zip dist/quantcore-circuits-klayout-0.3.0.zip \
        --check-version 0.3.0

* copies the files KLayout needs (``grain.xml``, ``pymacros/``, ``python/``, the tool icons) plus the README, the
  Q1 + R1 tutorial and the licence; development probes, smoke scripts and the repository loader stay behind;
* embeds ``kplugin/icons/salt_icon.png`` (64 x 64) and ``salt_screenshot.png`` in the exported ``grain.xml``
  (``scripts/release/make_salt_images.py`` makes them);
* checks the grain: name, version (``--check-version`` and ``pyproject.toml``), licence, URL, images;
* ``--clean`` empties ``--out`` first but keeps its ``.git`` (so it can be a worktree of the ``klayout-plugin`` branch);
* ``--zip`` also writes a zip with the package under a ``quantcore-circuits/`` folder (unzip into
  ``<KLayout home>/salt/`` to install by hand).
"""

from __future__ import annotations

import argparse
import base64
import io
import re
import shutil
import sys
import tomllib
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "kplugin"
FILES = ["grain.xml", "README.md", "TUTORIAL_q1_r1.md"]
TREES = ["pymacros", "python"]
ICON_GLOB = "icons/qcc_*.png"
SKIP_PARTS = {"__pycache__", ".pytest_cache"}
IMAGES = {"icon": SRC / "icons" / "salt_icon.png", "screenshot": SRC / "icons" / "salt_screenshot.png"}
PACKAGE_DIR = "quantcore-circuits"


def _files() -> list[Path]:
    out = [SRC / f for f in FILES if (SRC / f).exists()]
    for tree in TREES:
        out += [
            p
            for p in sorted((SRC / tree).rglob("*"))
            if p.is_file() and not SKIP_PARTS & set(p.parts) and p.suffix not in {".pyc", ".pyo"}
        ]
    out += sorted(SRC.glob(ICON_GLOB))
    return out


def _png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _grain_xml(version_check: str | None) -> tuple[str, dict]:
    text = (SRC / "grain.xml").read_text(encoding="utf-8")
    root = ET.fromstring(text)
    info = {k: (root.findtext(k) or "").strip() for k in ("name", "version", "license", "url", "doc-url", "title")}
    problems = []
    if info["name"] != PACKAGE_DIR:
        problems.append(f"grain name is {info['name']!r}, expected {PACKAGE_DIR!r}")
    py_version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if info["version"] != py_version:
        problems.append(f"grain version {info['version']} != pyproject version {py_version}")
    if version_check and info["version"] != version_check.lstrip("v"):
        problems.append(f"grain version {info['version']} != --check-version {version_check}")
    if not info["license"].startswith("GPL"):
        problems.append(f"licence is {info['license']!r}")
    if not info["url"].startswith("git+https://"):
        problems.append(f"url is {info['url']!r} (Salt expects git+https://...)")
    for tag in IMAGES:
        if root.find(tag) is not None:
            problems.append(f"kplugin/grain.xml already has <{tag}>; keep the source grain free of images")
    blocks = []
    for tag, path in IMAGES.items():
        data = path.read_bytes()
        w, h = _png_size(data)
        if tag == "icon" and (w > 64 or h > 64):
            problems.append(f"{path.name} is {w} x {h}; Salt icons are at most 64 x 64")
        blocks.append(f" <{tag}>{base64.b64encode(data).decode('ascii')}</{tag}>\n")
        info[tag] = f"{w} x {h}, {len(data)} bytes"
    if problems:
        raise SystemExit("grain check failed:\n  " + "\n  ".join(problems))
    out, n = re.subn(r"( *<dependencies\s*/?>)", lambda m: "".join(blocks) + m.group(1), text, count=1)
    if n != 1:
        raise SystemExit("grain.xml has no <dependencies> element to insert the images before")
    ET.fromstring(out)  # still well-formed
    return out, info


def export(out: Path, clean: bool, zip_path: Path | None, version_check: str | None) -> None:
    grain, info = _grain_xml(version_check)
    out.mkdir(parents=True, exist_ok=True)
    if clean:
        for child in out.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    elif any(c.name != ".git" for c in out.iterdir()):
        raise SystemExit(f"{out} is not empty; pass --clean to replace its contents (its .git is kept)")
    written: dict[str, bytes] = {}
    for src in _files():
        rel = src.relative_to(SRC).as_posix()
        written[rel] = grain.encode("utf-8") if rel == "grain.xml" else src.read_bytes()
    written["LICENSE"] = (ROOT / "LICENSE").read_bytes()
    for rel, data in written.items():
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    if zip_path:
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for rel, data in sorted(written.items()):
                z.writestr(f"{PACKAGE_DIR}/{rel}", data)
        zip_path.write_bytes(buf.getvalue())
    size = sum(len(d) for d in written.values())
    print(
        f"plugin {info['name']} {info['version']} ({info['license']}) -> {out}: {len(written)} files, "
        f"{size / 1e3:.0f} kB"
    )
    print(f"  url      {info['url']}")
    print(f"  doc-url  {info['doc-url']}")
    print(f"  icon     {info['icon']};  screenshot {info['screenshot']}")
    if zip_path:
        print(f"  zip      {zip_path} ({zip_path.stat().st_size / 1e3:.0f} kB)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True, help="folder to write the package into")
    ap.add_argument("--clean", action="store_true", help="empty --out first (keeps its .git)")
    ap.add_argument("--zip", type=Path, help="also write a zip of the package")
    ap.add_argument("--check-version", help="fail unless grain.xml has this version (e.g. the release tag)")
    a = ap.parse_args(argv)
    export(a.out.resolve(), a.clean, a.zip.resolve() if a.zip else None, a.check_version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
