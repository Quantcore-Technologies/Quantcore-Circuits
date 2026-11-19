"""Contract of the component catalog (``quantcore_circuits.layouts.catalog.catalog()``; the whole module skips until
it exists).

Every entry has a name, a ref and a valid category; its ref resolves and a default instance plans like any design
instance (cell built with default parameters, ports read); every port has a finite position and every routing port a
direction; every electrically meaningful component has a LOM model. The exception lists below are short and say why;
the LOM list shrinks as models land (its xfails are strict: an XPASS fails until the entry is removed).
"""

from __future__ import annotations

import importlib.util
import math
from fnmatch import fnmatchcase

import pytest

# categories in docs/components/INVENTORY.md; the catalog's own CATEGORIES win when it exports them
KNOWN_CATEGORIES = {
    "airbridge",
    "capacitor",
    "chip",
    "coupler",
    "element",
    "flip_chip",
    "junction",
    "launcher",
    "marker",
    "other",
    "qubit",
    "resonator",
    "route",
    "shape",
    "termination",
    "test_structure",
    "waveguide",
}
ELECTRICAL = {
    "qubit",
    "coupler",
    "capacitor",
    "resonator",
    "launcher",
    "termination",
    "junction",
    "waveguide",
    "airbridge",
}
HEAVY_CATEGORIES = {"chip"}  # whole KQC chips: seconds each to build → marked slow

# ref → reason: entries that cannot be built from default parameters alone
BUILD_EXCEPTIONS: dict[str, str] = {}
# ref → {port: reason}: routing ports without a direction (no ``port_<name>_corner`` refpoint)
DIRECTION_EXCEPTIONS: dict[str, dict[str, str]] = {
    "Swissmon": {"drive": "KQC Swissmon puts no port_drive_corner refpoint with default parameters"},
    "LauncherDC": {"port": "KQC LauncherDC adds port 'port' without a corner refpoint"},
}
# ref pattern (fnmatch; "module:<pattern>" matches the entry's module) → reason: electrically meaningful components
# still waiting for a LOM model (lom agent). Strict: an entry whose test XPASSes fails, so remove it when its model
# lands. Empty since 2026-11-03 (lom: quantcore_models.py for the legacy / CPW-E ports, bare KQC CPW segments).
LOM_XFAIL: dict[str, str] = {}


def _matches(entry: dict, pattern: str) -> bool:
    if pattern.startswith("module:"):
        return fnmatchcase(str(entry.get("module") or ""), pattern.split(":", 1)[1])
    return fnmatchcase(str(entry["ref"]), pattern)


def _lom_xfail(entry: dict) -> str | None:
    return next((why for pat, why in LOM_XFAIL.items() if _matches(entry, pat)), None)


# ports that are not CPW ends: junction leads / SQUID ends, and whole chips (reference cells per the catalog, not
# routed to; their port refpoints are chip-internal launcher / probe-line markers)
NON_ROUTING_CATEGORIES = {"junction", "chip"}
NON_ROUTING_PORT_PREFIXES = ("common", "squid", "junction_")


def _field(entry, key, default=None):
    return entry.get(key, default) if isinstance(entry, dict) else getattr(entry, key, default)


def _load():
    """(entries as dicts, valid categories, problem) — problem is set when the catalog exists but cannot be read."""
    if importlib.util.find_spec("quantcore_circuits.layouts.catalog") is None:
        return [], KNOWN_CATEGORIES, "quantcore_circuits.layouts.catalog is missing"  # a missing catalog fails, no skip
    try:
        from quantcore_circuits.layouts import catalog as mod  # pylint: disable=import-outside-toplevel

        data = mod.catalog()
    except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
        return [], KNOWN_CATEGORIES, f"catalog() failed: {type(e).__name__}: {e}"
    cats = getattr(mod, "CATEGORIES", None)
    valid = set(cats) if cats else KNOWN_CATEGORIES
    items = data.items() if isinstance(data, dict) else ((None, e) for e in data)
    entries = []
    for key, e in items:
        ref = _field(e, "ref") or _field(e, "cell") or key or _field(e, "name")
        entries.append(
            {
                "name": _field(e, "name") or key or ref,
                "ref": ref,
                "category": _field(e, "category"),
                "ports": _field(e, "ports"),
                "module": _field(e, "module"),
                "is_cell": _field(e, "cell") is not False,  # Component.cell=False: Metal routes, not cells
                "raw": e,
            }
        )
    return entries, valid, None


try:
    ENTRIES, CATEGORIES, LOAD_PROBLEM = _load()
except Exception as _e:  # noqa: BLE001  pylint: disable=broad-except
    ENTRIES, CATEGORIES, LOAD_PROBLEM = [], KNOWN_CATEGORIES, f"importing the catalog failed: {type(_e).__name__}: {_e}"

def _params(entries, *, electrical_only: bool = False, lom: bool = False):
    out = []
    for e in entries:
        if electrical_only and e["category"] not in ELECTRICAL:
            continue
        marks = []
        if e["category"] in HEAVY_CATEGORIES:
            marks.append(pytest.mark.slow)
        if lom and _lom_xfail(e):
            marks.append(pytest.mark.xfail(reason=_lom_xfail(e), strict=True))
        out.append(pytest.param(e, id=str(e["ref"]), marks=marks))
    return out or [pytest.param(None, id="none")]


def test_catalog_loads_and_is_well_formed():
    assert LOAD_PROBLEM is None, LOAD_PROBLEM
    assert ENTRIES, "catalog() is empty"
    problems = []
    for key in ("name", "ref", "category"):
        problems += [f"entry without {key}: {e['raw']!r}" for e in ENTRIES if not e[key]]
    refs = [e["ref"] for e in ENTRIES]
    problems += [f"duplicate ref {r}" for r in sorted({r for r in refs if refs.count(r) > 1})]
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("entry", _params(ENTRIES))
def test_category_is_valid(entry):
    if entry is None:
        pytest.skip("empty catalog")
    assert entry["category"] in CATEGORIES, (
        f"{entry['ref']}: category {entry['category']!r} not in {sorted(CATEGORIES)}"
    )


def _plan(ref: str):
    from quantcore_circuits.assembly import plan_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

    probe = {"schema": "qcc/0.1", "name": "catalog_probe", "instances": {"X": {"cell": ref, "place": {"at": [0, 0]}}}}
    return plan_design(load_design(probe)).instances["X"]


@pytest.mark.parametrize("entry", _params(ENTRIES))
def test_component_resolves_and_builds_with_defaults(entry):
    if entry is None:
        pytest.skip("empty catalog")
    ref = entry["ref"]
    if ref in BUILD_EXCEPTIONS:
        pytest.skip(f"{ref}: {BUILD_EXCEPTIONS[ref]}")
    if str(ref).startswith("static:"):
        pytest.skip("static cells have explicit ports, nothing to build")
    if not entry["is_cell"]:
        pytest.skip(f"{ref} is not a cell (catalog: cell=False)")
    if str(ref).startswith("metal:") and importlib.util.find_spec("qiskit_metal") is None:
        pytest.skip("qiskit_metal not installed")
    from quantcore_circuits.layouts.registry import resolve_cell

    resolve_cell(ref)
    placed = _plan(ref)
    problems = []
    for name, port in placed.local_ports.items():
        pos = port.pos
        if pos is None or not (math.isfinite(pos.x) and math.isfinite(pos.y)):
            problems.append(f"port {name}: no finite position ({pos})")
        routing = entry["category"] not in NON_ROUTING_CATEGORIES and not name.startswith(NON_ROUTING_PORT_PREFIXES)
        if routing and port.dir is None and name not in DIRECTION_EXCEPTIONS.get(ref, {}):
            problems.append(f"port {name}: routing port without a direction (add port_{name}_corner)")
        elif port.dir is not None and name in DIRECTION_EXCEPTIONS.get(ref, {}):
            problems.append(f"port {name} now has a direction: remove it from DIRECTION_EXCEPTIONS")
    declared = entry["ports"]
    if declared:
        names = {(_field(p, "name") if not isinstance(p, str) else p) for p in declared}
        if names != set(placed.local_ports):
            problems.append(f"declared ports {sorted(names)} != built ports {sorted(placed.local_ports)}")
    assert not problems, f"{ref}:\n  " + "\n  ".join(problems)


@pytest.mark.parametrize("entry", _params(ENTRIES, electrical_only=True, lom=True))
def test_electrical_component_has_lom_model(entry):
    if entry is None:
        pytest.skip("no electrically meaningful components in the catalog")
    import quantcore_circuits.lom  # noqa: F401  (registers the stock models)
    from quantcore_circuits.lom.fragment import lom_model

    assert lom_model(entry["ref"]) is not None, f"{entry['ref']} ({entry['category']}) has no LOM model"


def test_exception_lists_name_catalog_entries():
    """Keep the exception lists honest: every listed ref (or LOM pattern) matches a catalog entry."""
    refs = {e["ref"] for e in ENTRIES} | {e["name"] for e in ENTRIES}
    stale = sorted((set(BUILD_EXCEPTIONS) | set(DIRECTION_EXCEPTIONS)) - refs)
    stale += sorted(pat for pat in LOM_XFAIL if not any(_matches(e, pat) for e in ENTRIES))
    assert not stale, f"exception lists name refs not in the catalog: {stale}"
