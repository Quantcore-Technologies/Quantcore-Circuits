"""The examples stay runnable: every notebook executes, every saved design builds, passes the fast DRC and gives a
node-connected LOM netlist.

* **Notebooks** (``examples/**/*.ipynb``, marked ``slow``) run with nbclient in the ``python3`` kernel, from their own
  folder, with ``QCC_LIVE=0`` and ``BROWSER=qcc-no-browser``. A hidden first cell (never saved) keeps the
  KLayout window and browser out of it whatever the notebook does: the klive and GUI-command ports are unreachable,
  ``open_klayout`` never starts KLayout, ``gui_snapshot`` renders headless and ``webbrowser.open`` does nothing.
* Each notebook must also honour ``QCC_LIVE`` on its own (fast static check): no
  ``live=True`` literal, and calls that push to KLayout sit under a condition on ``live`` / ``QCC_LIVE``.
* **Design files**: every ``examples/**/*.json`` with a design schema (the saved designs under ``examples/designs/**``
  and the top-level examples). Under ``examples/designs/`` an unreadable JSON file counts as a broken design.
* **Deliverable shape**: every ``examples/designs/<group>/<id>.ipynb`` has its saved ``<id>.json``
  and vice versa, and has a FEM-export cell (``export_sims`` / ``export_job``); so does any other notebook that defines
  sim groups. After a slow run, the export cell must have left a ``build/jobs/*/job.json`` for every sim group it
  exports, with ports and named nets. (Every sim group × analysis of every design is exported directly by
  ``tests/test_sim_tools.py::test_every_design_sim_group_exports``.)
* **Dashboard cards** of the synthesised examples (``two_qubit_synth.json``, ``five_qubit_synth.json``), built as
  ``reviewer/scripts/make_states.py`` does (LOM-only ``loop.analyse`` + ``loop.feedback`` into a temporary run):
  unique card / element ids, and every ``from[].ref``, ``plot``, element link and parameter card resolves.
"""

from __future__ import annotations

import ast
import json
import math
import re
import time
from functools import cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
DESIGNS = EXAMPLES / "designs"
DESIGN_SCHEMAS = {"qcc/0.1", "qcd/0.1"}
NON_ROUTING_PORT_PREFIXES = ("squid", "junction_")  # junction attachment points, never route ends
SKIP_DIRS = {"build", ".ipynb_checkpoints", "__pycache__", "jobs", "runs", "fem"}  # fem/: kept FEM results
# <id>.v1.ipynb: the one-cell-layout notebooks kept beside their v2 rewrites
# They save the same <id>.json as <id>.ipynb, so they are not walked: the
# pairing, export-cell and execution tests run on the v2 notebook only.
KEPT_SUFFIX = ".v1.ipynb"
CELL_TIMEOUT_S = 1800  # per cell; some cells run LOM sweeps or synthesis
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _walk(pattern: str) -> list[Path]:
    return sorted(
        p
        for p in EXAMPLES.rglob(pattern)
        if not SKIP_DIRS & set(p.relative_to(EXAMPLES).parts[:-1]) and not p.name.endswith(KEPT_SUFFIX)
    )


def _design_files() -> list[Path]:
    out = []
    for path in _walk("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            if DESIGNS in path.parents:
                out.append(path)  # a broken file where designs live: let the load test say so
            continue
        if isinstance(data, dict) and data.get("schema") in DESIGN_SCHEMAS:
            out.append(path)
    return out


NOTEBOOKS = _walk("*.ipynb")
DESIGN_FILES = _design_files()


# ---- notebooks -----------------------------------------------------------------------------------------------------

# Prepended to the in-memory copy of each notebook. Only acts when QCC_LIVE=0, so it is a no-op for users.
_GUARD = r"""
import os as _qcc_os
if _qcc_os.environ.get("QCC_LIVE", "1") == "0":
    import socket as _qcc_socket
    import webbrowser as _qcc_wb

    _qcc_connect = _qcc_socket.create_connection

    def _qcc_guarded_connect(address, *args, **kwargs):
        host, port = address[0], address[1]
        if str(host) in ("127.0.0.1", "localhost", "::1") and int(port) in (8082, 8083):
            raise ConnectionRefusedError(f"QCC_LIVE=0 (test run): KLayout port {port} is off limits")
        return _qcc_connect(address, *args, **kwargs)

    _qcc_socket.create_connection = _qcc_guarded_connect
    if _qcc_os.environ.get("BROWSER") == "qcc-no-browser":
        _qcc_wb.open = _qcc_wb.open_new = _qcc_wb.open_new_tab = lambda *a, **k: True

    import quantcore_circuits.live as _qcc_live
    import quantcore_circuits.live.klayout as _qcc_kl
    import quantcore_circuits.live.klive as _qcc_klive
    import quantcore_circuits.live.snapshot as _qcc_snap

    def _qcc_no_klive(*args, **kwargs):
        return {}

    def _qcc_klive_down(*args, **kwargs):
        return False

    def _qcc_no_open(*args, **kwargs):
        return {"started": False, "klive": False, "hint": "QCC_LIVE=0: KLayout not started"}

    def _qcc_headless(png, size=(1600, 1600), layout=None, box=None, port=None, timeout=None, fallback=None):
        source = fallback if fallback is not None else layout
        if source is None:
            raise RuntimeError("QCC_LIVE=0: gui_snapshot needs a layout or fallback to render headless")
        return _qcc_snap.snapshot(source, png, size=size, box=box), "headless"

    for _qcc_m in (_qcc_live, _qcc_klive, _qcc_kl):
        _qcc_m.klive_available = _qcc_klive_down
    _qcc_live.send_to_klive = _qcc_klive.send_to_klive = _qcc_no_klive
    _qcc_kl.open_klayout = _qcc_no_open
    _qcc_kl._spawn_detached = lambda *a, **k: None
    _qcc_snap.gui_available = _qcc_klive_down
    _qcc_snap.gui_snapshot = _qcc_headless
"""

# calls that reach the user's KLayout window (by function / attribute name); qcc.show is checked separately
_PUSHERS = {"send_to_klive", "open_klayout", "gui_snapshot"}


def _code_cells(nb: dict) -> list[tuple[int, str]]:
    return [
        (i, "".join(c["source"]) if isinstance(c["source"], list) else c["source"])
        for i, c in enumerate(nb["cells"])
        if c["cell_type"] == "code"
    ]


def _python_source(cell: str) -> str:
    try:
        from IPython.core.inputtransformer2 import TransformerManager  # pylint: disable=import-outside-toplevel

        return TransformerManager().transform_cell(cell)
    except ImportError:
        return "\n".join("" if line.lstrip().startswith(("%", "!")) else line for line in cell.splitlines())


def _live_violations(source: str) -> list[str]:
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

    def guarded(node) -> bool:
        while node in parents:
            node = parents[node]
            if isinstance(node, ast.If | ast.IfExp | ast.While):
                test = ast.unparse(node.test)
                if "live" in test.lower():
                    return True
        return False

    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg == "live" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                out.append(f"line {node.lineno}: live=True (use live=os.environ.get('QCC_LIVE', '1') == '1')")
        f = node.func
        name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)
        is_qcc_show = isinstance(f, ast.Attribute) and f.attr == "show" and ast.unparse(f.value) == "qcc"
        if (name in _PUSHERS or is_qcc_show) and not guarded(node):
            what = "qcc.show" if is_qcc_show else name
            out.append(f"line {node.lineno}: {what}(...) pushes to KLayout but is not under `if live:`")
    return out


@pytest.mark.parametrize("nb_path", NOTEBOOKS or [None], ids=lambda p: _rel(p) if p else "no-notebooks")
def test_notebook_honours_qcc_live(nb_path):
    """Run as the user would (QCC_LIVE unset → live), but with QCC_LIVE=0 nothing may reach KLayout."""
    if nb_path is None:
        pytest.skip("no notebooks under examples/")
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    problems = []
    for i, cell in _code_cells(nb):
        try:
            found = _live_violations(_python_source(cell))
        except SyntaxError as e:
            found = [f"syntax error: {e.msg} (line {e.lineno})"]
        problems += [f"cell {i}, {p}" for p in found]
    assert not problems, f"{_rel(nb_path)}: QCC_LIVE contract\n  " + "\n  ".join(problems)


@pytest.mark.slow
@pytest.mark.filterwarnings("ignore:Proactor event loop:RuntimeWarning")
@pytest.mark.filterwarnings("ignore:Cell is missing an id field")
@pytest.mark.parametrize("nb_path", NOTEBOOKS or [None], ids=lambda p: _rel(p) if p else "no-notebooks")
def test_notebook_executes(nb_path, monkeypatch):
    if nb_path is None:
        pytest.skip("no notebooks under examples/")
    nbformat = pytest.importorskip("nbformat")
    nbclient = pytest.importorskip("nbclient")
    pytest.importorskip("ipykernel")
    from nbclient.exceptions import CellExecutionError, CellTimeoutError, DeadKernelError

    monkeypatch.setenv("QCC_LIVE", "0")
    monkeypatch.setenv("BROWSER", "qcc-no-browser")
    monkeypatch.setenv("PYDEVD_DISABLE_FILE_VALIDATION", "1")
    nb = nbformat.read(str(nb_path), as_version=4)
    nb.cells.insert(0, nbformat.v4.new_code_cell(_GUARD))
    client = nbclient.NotebookClient(
        nb,
        timeout=CELL_TIMEOUT_S,
        startup_timeout=180,
        kernel_name="python3",
        resources={"metadata": {"path": str(nb_path.parent)}},
    )
    error = None
    t0 = time.time()
    try:
        client.execute()
    except (CellExecutionError, CellTimeoutError, DeadKernelError) as e:
        error = e
    if error is not None:  # outside the except block: no chained duplicate traceback
        failed = next(
            (i for i, c in enumerate(nb.cells) if any(o.get("output_type") == "error" for o in c.get("outputs", []))),
            None,
        )
        where = f"cell {failed - 1}" if failed else "a cell"  # -1: the guard cell is not part of the notebook
        pytest.fail(f"{_rel(nb_path)}: {where} failed\n{_ANSI.sub('', str(error))}", pytrace=False)
    problems = _exported_job_problems(nb_path, t0)
    assert not problems, f"{_rel(nb_path)}: FEM-export cell\n  " + "\n  ".join(problems)


# ---- FEM-export cell and notebook / design pairing -----------------------------------------------------------------

# send_fem_jobs: the _common helper of the step-by-step design notebooks; it exports like
# export_sims (same design / groups arguments) and, with run=True, solves the jobs in a batch AEDT
_EXPORTERS = {"export_sims", "export_job", "send_fem_jobs"}
_CAP_ANALYSES = {"q3d_cmatrix", "elmer_cap", "palace_cap"}  # C-matrix analyses: their jobs must name nets


def _calls(nb: dict) -> list[ast.Call]:
    out = []
    for _, cell in _code_cells(nb):
        try:
            tree = ast.parse(_python_source(cell))
        except SyntaxError:
            continue  # reported by test_notebook_honours_qcc_live
        out += [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    return out


def _call_name(node: ast.Call) -> str | None:
    f = node.func
    return f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else None)


def _saved_design(nb_path: Path) -> dict | None:
    """The notebook's saved design (``<id>.json`` next to ``<id>.ipynb``), raw JSON; None if there is none."""
    path = nb_path.with_suffix(".json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schema") in DESIGN_SCHEMAS else None


def _design_notebooks() -> list[Path]:
    return [p for p in NOTEBOOKS if DESIGNS in p.parents]


@pytest.mark.parametrize("nb_path", NOTEBOOKS or [None], ids=lambda p: _rel(p) if p else "no-notebooks")
def test_notebook_has_fem_export_cell(nb_path):
    """Design notebooks (and any notebook that defines sim groups) export their FEM jobs."""
    if nb_path is None:
        pytest.skip("no notebooks under examples/")
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    names = {_call_name(c) for c in _calls(nb)}
    design = _saved_design(nb_path) or {}
    defines_groups = "sim_group" in names or bool(design.get("sim_groups"))
    if not (DESIGNS in nb_path.parents or defines_groups):
        pytest.skip("not a design notebook and no sim groups")
    groups = f"; the design has sim groups {sorted(design.get('sim_groups') or [])}" if defines_groups else ""
    assert names & _EXPORTERS, f"{_rel(nb_path)}: no FEM-export cell (`C.export_sims(DESIGN)` / `export_job`){groups}"


def test_design_notebooks_and_jsons_pair_up():
    """``examples/designs/<group>/<id>.ipynb`` saves ``<id>.json`` beside it (or, for a notebook of several designs,
    ``<id>/*.json``); every saved design has its notebook."""
    nbs = {p.with_suffix("") for p in _design_notebooks()}
    jsons = [p for p in DESIGN_FILES if DESIGNS in p.parents]
    stems = {p.with_suffix("") for p in jsons}
    folders = {p.parent for p in jsons}
    problems = [
        f"{_rel(p)}.ipynb: no saved design {p.name}.json (or {p.name}/*.json)"
        for p in sorted(nbs)
        if p not in stems and p not in folders
    ]
    problems += [
        f"{_rel(p)}: no notebook {p.stem}.ipynb (or ../{p.parent.name}.ipynb)"
        for p in sorted(jsons)
        if p.with_suffix("") not in nbs and p.parent not in nbs
    ]
    assert not problems, "\n".join(problems)


def test_kept_v1_notebooks_sit_beside_their_rewrite():
    """A kept ``<id>.v1.ipynb`` (the notebook before its v2 rewrite, outputs kept) has its ``<id>.ipynb`` beside it:
    the v1 copy is a reference, never the deliverable."""
    kept = sorted(p for p in DESIGNS.rglob("*" + KEPT_SUFFIX) if ".ipynb_checkpoints" not in p.parts)
    lonely = [_rel(p) for p in kept if not p.with_name(p.name[: -len(KEPT_SUFFIX)] + ".ipynb").exists()]
    assert not lonely, "kept v1 notebooks without their rewrite:\n" + "\n".join(lonely)


def _exported_job_problems(nb_path: Path, t0: float) -> list[str]:
    """After a notebook ran: the jobs its ``export_sims`` call wrote (``build/jobs/*/job.json`` newer than ``t0``,
    for its design) cover the groups it exports, each with ports and, for C-matrix analyses, named nets."""
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    calls = [c for c in _calls(nb) if _call_name(c) in ("export_sims", "send_fem_jobs")]
    design = _saved_design(nb_path)
    if not calls or design is None or not design.get("sim_groups"):
        return []
    want: set[str] = set()  # groups that must have a job: all of them unless the call lists some
    for c in calls:
        arg = c.args[1] if len(c.args) > 1 else next((k.value for k in c.keywords if k.arg == "groups"), None)
        if arg is None or (isinstance(arg, ast.Constant) and arg.value is None):
            want |= set(design["sim_groups"])
            continue
        try:
            listed = ast.literal_eval(arg)
        except ValueError:
            continue  # a variable: at least one job (checked below)
        want |= set(listed) if isinstance(listed, list | tuple) else set()
    problems, seen = [], set()
    for job in sorted((ROOT / "build" / "jobs").glob("*/job.json")):
        try:
            if job.stat().st_mtime < t0 - 1:
                continue
            meta = json.loads(job.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if meta.get("design") != design.get("name"):
            continue
        group, where = meta.get("group"), _rel(job.parent)
        seen.add(group)
        if not meta.get("ports"):
            problems.append(f"{where}: no ports")
        nets = meta.get("nets") or {}
        if meta.get("analysis") in _CAP_ANALYSES and not nets:
            problems.append(f"{where}: no C-matrix nets")
        problems += [f"{where}: net {k} has no name" for k, v in sorted(nets.items()) if not v]
    if not seen:
        problems.append(f"no build/jobs/*/job.json written for design {design.get('name')!r}")
    problems += [f"sim group {g}: no job.json written" for g in sorted(want - seen)]
    return problems


# ---- dashboard cards of the synthesised examples ------------------------------------------------------------------

CARD_EXAMPLES = [EXAMPLES / "two_qubit_synth.json", EXAMPLES / "five_qubit_synth.json"]


@pytest.fixture(scope="module", params=CARD_EXAMPLES, ids=lambda p: _rel(p))
def dashboard_state(request, tmp_path_factory):
    """Cards / elements / plots as ``make_states.lom_only_run`` makes them (no screenshots), in a temporary run."""
    path = request.param
    if not path.exists():
        pytest.skip(f"{_rel(path)} does not exist")
    from quantcore_circuits import loop
    from quantcore_circuits.track import Run

    run = Run(str(path), tmp_path_factory.mktemp(path.stem), reset=True)
    an = loop.analyse(str(path), None, run=run, readout=False)
    loop.feedback(an, run=run, design_source=str(path))  # adds the feedback cards and the residual plot
    st = run.state
    assert st.get("cards") and st.get("elements"), f"{_rel(path)}: no cards / elements in the run state"
    return st


def _ref_resolves(ref: str, st: dict) -> bool:
    """As the dashboard's resolver (reviewer/src/tabs/ParametersTab.tsx): a card id or index, an element id,
    ``chip``, or a section letter. Stricter than the contract on purpose (``reviewer/contract/state.ts`` CardRef also
    allows a plain non-link word such as ``"design"``): a plain word renders like a broken link, so ``cards.py`` links
    every dependency it can (or leaves ``ref`` out) and a stray word fails here."""
    r = ref.strip()
    cards = st["cards"]
    if re.fullmatch(r"\d{1,3}", r):
        return any(c["index"] == int(r) for c in cards)
    if r == "chip" or any(c["id"] == r for c in cards) or any(e["id"] == r for e in st["elements"]):
        return True
    return bool(re.fullmatch(r"[A-Z]", r)) and any(s.get("letter") == r for s in st["sections"])


def test_cards_and_elements_have_unique_ids(dashboard_state):
    st = dashboard_state
    problems = []
    for what, items in (("card", st["cards"]), ("element", st["elements"]), ("section", st["sections"])):
        ids = [x["id"] for x in items]
        problems += [f"{what} id {i!r} used twice" for i in sorted({i for i in ids if ids.count(i) > 1})]
    # cards._Cards.card() renames a repeated id to "<id>#<n>": references to the first one then hit the wrong card
    problems += [f"card id {c['id']!r}: renamed duplicate" for c in st["cards"] if "#" in c["id"]]
    assert not problems, "\n".join(problems)


def test_card_references_resolve(dashboard_state):
    st = dashboard_state
    elements = {e["id"] for e in st["elements"]} | {"chip"}
    sections = {s["id"] for s in st["sections"]}
    plots = {p["id"] for p in st.get("plots") or []}
    problems = []
    for c in st["cards"]:
        cid = c["id"]
        for f in c.get("from") or []:
            if f.get("ref") is not None and not _ref_resolves(str(f["ref"]), st):
                problems.append(f"card {cid}: from {f.get('label')!r} → ref {f['ref']!r} is no card or element")
        if c.get("plot") and c["plot"] not in plots:
            problems.append(f"card {cid}: plot {c['plot']!r} not in the state's plots {sorted(plots)}")
        if c.get("element") not in elements:
            problems.append(f"card {cid}: element {c.get('element')!r} is not an element")
        if c.get("partner") and c["partner"] not in elements:
            problems.append(f"card {cid}: partner {c['partner']!r} is not an element")
        if c.get("section") not in sections:
            problems.append(f"card {cid}: section {c.get('section')!r} is not a section")
    assert not problems, "\n".join(problems)


def test_element_links_resolve(dashboard_state):
    st = dashboard_state
    elements = {e["id"] for e in st["elements"]}
    cards = {c["id"] for c in st["cards"]}
    problems = []
    for e in st["elements"]:
        for link in e.get("links") or []:
            if link.get("to") not in elements:
                problems.append(f"element {e['id']}: link ({link.get('role')}) to {link.get('to')!r}: no such element")
        for prm in e.get("params") or []:
            if prm.get("card") and prm["card"] not in cards:
                problems.append(f"element {e['id']}: param {prm.get('key')} → card {prm['card']!r}: no such card")
            if prm.get("of") and prm["of"] not in elements:
                problems.append(f"element {e['id']}: param {prm.get('key')} of {prm['of']!r}: no such element")
    assert not problems, "\n".join(problems)


# ---- design files --------------------------------------------------------------------------------------------------

_design_ids = [_rel(p) for p in DESIGN_FILES] or ["no-designs"]
_design_params = pytest.mark.parametrize("path", DESIGN_FILES or [None], ids=_design_ids)


@cache
def _built(path: Path):
    from quantcore_circuits import build  # pylint: disable=import-outside-toplevel

    return build(path)


@_design_params
def test_design_file_loads(path):
    if path is None:
        pytest.skip("no design files under examples/")
    from quantcore_circuits import load_design

    design = load_design(path)
    # a replica of a launcher-only chip (KQC Launchers) has nothing but the chip's launchers
    assert design.instances or design.chip.launchers, f"{_rel(path)} has no instances and no chip launchers"


@_design_params
def test_design_builds_and_fast_drc_has_no_errors(path):
    if path is None:
        pytest.skip("no design files under examples/")
    from quantcore_circuits.assembly import drc

    result = _built(path)
    assert result.cell is not None
    for name, length in result.route_lengths().items():
        assert length is None or (math.isfinite(length) and length > 0), f"route {name}: length {length}"
    report = drc.check(result, netlist=False)
    assert report.ok, f"{_rel(path)}: fast DRC errors\n{report}"


@_design_params
def test_design_lom_netlist_is_node_connected(path):
    """Every component port lands on a circuit node (or ground, or a control line), every route end is resolved,
    every branch joins existing nodes, and no node floats or is left without a branch."""
    if path is None:
        pytest.skip("no design files under examples/")
    from quantcore_circuits.lom import lom_from_design

    result = _built(path)
    b = lom_from_design(result.design, plan=result.plan)
    m = b.model
    nodes = set(m.nodes)
    gnd = m.ground
    problems = []
    for iname, placed in result.plan.instances.items():
        for port in placed.local_ports:
            if f"{iname}.{port}" not in b.port_map and not port.startswith(NON_ROUTING_PORT_PREFIXES):
                problems.append(f"port {iname}.{port}: no LOM node (the component's model does not map it)")
    for ref, node in sorted(b.port_map.items()):
        if node.startswith("control:"):
            if not node.split(":", 1)[1]:
                problems.append(f"port {ref}: control line without a kind ({node!r})")
        elif node not in nodes:
            problems.append(f"port {ref} → node {node!r}, which is not in the circuit (no element on it)")
    problems += [f"route not resolved: {n}" for n in b.notes if "not in the selection" in n]
    for bname, br in m.branches.items():
        problems += [f"branch {bname}: unknown node {n!r}" for n in br.nodes if n not in nodes]
    referenced = {n for br in m.branches.values() for n in br.nodes}
    problems += [f"node {n}: no branch on it" for n in sorted(nodes - referenced - {gnd})]
    reached, frontier = {gnd}, [gnd]
    while frontier:
        n = frontier.pop()
        for br in m.branches.values():
            if n in br.nodes:
                other = br.nodes[1] if br.nodes[0] == n else br.nodes[0]
                if other not in reached:
                    reached.add(other)
                    frontier.append(other)
    problems += [f"node {n}: floating (no path to ground)" for n in sorted(nodes - reached)]
    assert not problems, f"{_rel(path)}: LOM netlist\n  " + "\n  ".join(problems)
