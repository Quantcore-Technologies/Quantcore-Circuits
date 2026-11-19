"""Sphinx configuration of the Quantcore circuits docs.

Build locally (any env with ``pip install -r docs/requirements.txt``; the library itself is not needed)::

    sphinx-build -b html docs docs/_build/html

GitHub Pages serves the same build (``.github/workflows/docs.yml``). How to host it: ``docs/hosting.md``.

``QCC_DOCS_FAST=1`` skips the API reference (sphinx-autoapi): a build in seconds while writing pages, and several builds
can run side by side (autoapi writes ``reference/api/`` into the source tree while it builds).
"""

from __future__ import annotations

import datetime
import os
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]

project = "Quantcore circuits"
author = "Quantcore"
copyright = f"{datetime.date.today().year}, Quantcore"  # noqa: A001  (Sphinx's name)
release = version = _PROJECT["version"]

FAST = os.environ.get("QCC_DOCS_FAST") == "1"

extensions = [
    "myst_parser",  # Markdown pages (MyST)
    "sphinx_copybutton",
]
if not FAST:
    extensions.append("autoapi.extension")  # API reference read from the source: nothing imported (no KLayout / KQC)

root_doc = "index"
source_suffix = {".md": "markdown", ".rst": "restructuredtext"}
exclude_patterns = [
    "_build",
    *(["reference/api/**"] if FAST else []),
    "other-images/**",  # a local folder of raw image copies, when there is one (not part of the site)
    "components/notes/**",  # hand-written notes, included by the generated cell pages
    "Thumbs.db",
    ".DS_Store",
]

# ---- MyST ---------------------------------------------------------------------------------------------------------
myst_enable_extensions = ["colon_fence", "deflist", "dollarmath", "fieldlist", "attrs_inline"]
myst_heading_anchors = 3  # [text](page.md#a-heading) links work
# The older pages skip heading levels and link source files outside docs/ (shown as plain text): don't flood the log.
suppress_warnings = ["myst.header", "myst.xref_missing", "ref.python"]  # ref.python: ambiguous names in signatures
if FAST:
    suppress_warnings.append("toc.excluded")  # the API pages are not built

# ---- API reference (sphinx-autoapi) -------------------------------------------------------------------------------
autoapi_type = "python"
autoapi_dirs = [str(ROOT / "src" / "quantcore_circuits"), str(ROOT / "kplugin" / "python" / "qcc_kplugin")]
autoapi_root = "reference/api"
autoapi_add_toctree_entry = False  # listed in index.md ▸ Reference
autoapi_keep_files = False
autoapi_member_order = "groupwise"
autoapi_options = ["members", "undoc-members", "show-inheritance", "show-module-summary"]
autoapi_ignore = ["*/review/static/*", "*/__pycache__/*"]


# The docstrings are written to be read in the source: |x| is an absolute value or a bra-ket, not an RST substitution,
# and a summary line may stop inside ``a literal``. Make them valid reStructuredText for the API pages only.
_LITERAL = re.compile(r"(``.+?``|`[^`]+`)")
_TABLE_ROW = re.compile(r"\s*(\+[-=+]|\| )")


def _escape_bars(line: str) -> str:
    """``|`` -> ``\\|`` outside literals and interpreted text (the docs never use RST substitutions)."""
    if _TABLE_ROW.match(line):  # a grid-table border or row, or a line block ("| text")
        return line
    parts = _LITERAL.split(line)
    return "".join(p if i % 2 else re.sub(r"(?<!\\)\|", r"\\|", p) for i, p in enumerate(parts))


def _rst_safe_docstring(app, what, name, obj, options, lines):  # noqa: ARG001  (autodoc-process-docstring)
    """Escape stray ``|``; when the first line leaves inline markup open, join the first paragraph into one line
    (autoapi's summary tables show the first line alone)."""
    lines[:] = [_escape_bars(x) for x in lines]
    if lines and (lines[0].count("``") % 2 or lines[0].replace("``", "").count("`") % 2 or lines[0].count("**") % 2):
        end = next((i for i, x in enumerate(lines) if not x.strip()), len(lines))
        lines[:end] = [" ".join(x.strip() for x in lines[:end])]


def setup(app):
    if not FAST:
        if "autodoc-process-docstring" not in app.events.events:
            app.add_event("autodoc-process-docstring")  # autoapi emits it when it exists (autodoc is not loaded)
        app.connect("autodoc-process-docstring", _rst_safe_docstring)


# ---- HTML ---------------------------------------------------------------------------------------------------------
html_theme = "furo"
html_title = f"Quantcore circuits {release}"
html_baseurl = "https://quantcore-technologies.github.io/Quantcore-Circuits/"  # GitHub Pages (canonical links, sitemap)
html_static_path = ["_static"]  # the logos (assets/logo-circuits-*.png: the dashboard's wordmark) and custom.css
html_css_files = ["custom.css"]  # smaller headings, a wider sidebar
html_favicon = "_static/favicon.png"
html_theme_options = {
    "light_logo": "logo-circuits-black.png",
    "dark_logo": "logo-circuits-white.png",
    "sidebar_hide_name": True,
    "navigation_with_keys": True,
}
