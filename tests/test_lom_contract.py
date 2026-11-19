"""Generic contract of every registered LOM model (see :mod:`quantcore_circuits.lom.fragment`), checked on a default
instance of its component (default cell parameters, no junction values and typical ones).

Models come from ``register_lom`` (keys are class names; ``"metal:<Class>"`` refs when the key is a Quantum Metal
class), from ``qcc_lom`` classmethods on Quantcore / exported cells, and from the component catalog once it exists.
Each model, built for an instance ``XA``, must give:

* elements between fragment nodes or ``"gnd"`` (two distinct ends), of a ``circuit.json`` branch type, with unique
  names that carry the instance name (branch names are global), and finite, positive estimates where present;
* ``port_nodes`` whose keys are real ports of the component and whose targets are fragment nodes, ``"gnd"`` or
  ``"control:<kind>"``; every port of the component mapped (an unmapped port silently drops the routes on it),
  junction attachment ports (``squid*``, ``junction_*``) excepted;
* lines (distributed CPW sections) on fragment nodes, their end ports mapped to that node, length >= 0 (0 marks a
  termination) and positive widths, ends ``"short"`` / ``"open"``, couplings to fragment nodes;
* hangers (coupled sections of a line to an outside conductor) on a line of the fragment, at one of its
  terminated ends, with a finite positive coupling length (no longer than the line) and ground gap;
* no fragment node without an element, line or port (a dead node: the builder drops it);
* nothing shared between two instances (``XA`` / ``XB``): element / line names, FEM island labels and knobs differ;
* knob ranges ``lo <= hi``, finite.

Every electrical catalog entry with a model is checked here (one ref per model and class).
"""

from __future__ import annotations

import math
import re
from functools import cache
from typing import get_args

import pytest

INSTANCE, OTHER = "XA", "XB"
JUNCTIONS = {"no-junction": None, "junction": {"Lj_nH": 10.0, "Cj_fF": 2.0}}
# value keys that are physical quantities (unit suffix): finite and >= 0; "estimate" and these must be > 0
_UNIT = re.compile(r"_(fF|pF|nH|pH|uH|GHz|MHz|kHz|ohm|um|mm|m_s)$")
_STRICTLY_POSITIVE = {"estimate", "Lj_nH", "R_ohm", "f_GHz", "Z0_ohm", "length_um", "vp_m_s"}
# junction attachment points (refpoints for the simulation's junction port), never route ends: mapping is optional
NON_ROUTING_PORT_PREFIXES = ("squid", "junction_")


def _catalog_refs() -> list[str]:
    try:
        from quantcore_circuits.layouts.catalog import catalog  # pylint: disable=import-outside-toplevel
    except ImportError:
        return []
    entries = catalog()
    items = entries.items() if isinstance(entries, dict) else ((None, e) for e in entries)
    refs = []
    for key, e in items:
        ref = e.get("ref") if isinstance(e, dict) else getattr(e, "ref", None)
        refs.append(str(ref or key))
    return refs


def _collect() -> tuple[list[str], list[str]]:
    """(refs with a LOM model, one per model/class; problems found while collecting)."""
    from quantcore_circuits.layouts import pcell_classes  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.layouts.registry import list_components  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom import fragment  # pylint: disable=import-outside-toplevel

    problems: list[str] = []
    try:
        registry = fragment.registered() if hasattr(fragment, "registered") else dict(fragment._REGISTRY)
    except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
        problems.append(f"lom.fragment.registered() failed: {type(e).__name__}: {e}")
        registry = dict(getattr(fragment, "_REGISTRY", {}))
    candidates: list[str] = []
    try:
        candidates += _catalog_refs()
    except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
        problems.append(f"layouts.catalog.catalog() failed: {type(e).__name__}: {e}")
    candidates += [c.__name__ for c in [*pcell_classes(), *list_components().values()] if hasattr(c, "qcc_lom")]
    candidates += list(registry)
    seen: dict[tuple, str] = {}
    for ref in candidates:
        try:
            fn = fragment.lom_model(ref)
        except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
            problems.append(f"lom_model({ref!r}) raised {type(e).__name__}: {e}")
            continue
        if fn is None:
            if ref in registry and not _is_known_base(ref):
                problems.append(f"register_lom({ref!r}): no cell or base class of a cell has this name")
            continue
        seen.setdefault((fn, _cls_key(ref)), ref)
    return sorted(set(seen.values())), problems


def _is_known_base(key: str) -> bool:
    """A registry key may name a base class (subclasses inherit the model through their MRO), e.g. ``Airbridge``;
    ``metal:<Class>`` keys must name a qlibrary class."""
    if key.startswith("metal:"):
        try:
            from quantcore_circuits.layouts.metal import qlibrary_index  # pylint: disable=import-outside-toplevel
        except ImportError:
            return True
        return key.split(":", 1)[1] in qlibrary_index()
    from kqcircuits.elements.element import Element  # pylint: disable=import-outside-toplevel

    stack, seen = [Element], set()
    while stack:
        cls = stack.pop()
        if cls.__name__ == key:
            return True
        for sub in cls.__subclasses__():
            if sub not in seen:
                seen.add(sub)
                stack.append(sub)
    return False


def _cls_key(ref: str):
    try:
        from quantcore_circuits.layouts.registry import resolve_cell  # pylint: disable=import-outside-toplevel

        return resolve_cell(ref)
    except Exception:  # noqa: BLE001  pylint: disable=broad-except
        return ref


try:
    MODEL_REFS, COLLECT_PROBLEMS = _collect()
except Exception as _e:  # noqa: BLE001  pylint: disable=broad-except
    MODEL_REFS, COLLECT_PROBLEMS = [], [f"collecting LOM models failed: {type(_e).__name__}: {_e}"]

models = pytest.mark.parametrize("ref", MODEL_REFS or [None], ids=MODEL_REFS or ["no-models"])


def _need(ref):
    if ref is None:
        pytest.skip("no LOM models registered")


@cache
def _fragment(ref: str, junction: str, name: str = INSTANCE):
    from quantcore_circuits.design.schema import Instance  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom.fragment import lom_model  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    j = JUNCTIONS[junction]
    inst = Instance.model_validate({"cell": ref, "params": {}, "place": {"at": [0, 0]}, "junction": j})
    return lom_model(ref)(name, inst, get_pdk())


@cache
def _ports(ref: str) -> frozenset[str]:
    """Port names of a default instance, through the same planning path as any design (wrapper cells included)."""
    from quantcore_circuits.assembly import plan_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

    probe = {"schema": "qcc/0.1", "name": "lom_probe", "instances": {INSTANCE: {"cell": ref, "place": {"at": [0, 0]}}}}
    return frozenset(plan_design(load_design(probe)).instances[INSTANCE].local_ports)


def test_lom_registry_is_consistent():
    """Every ``register_lom`` key resolves to a cell (a typo would silently leave the cell without a model)."""
    assert not COLLECT_PROBLEMS, "\n".join(COLLECT_PROBLEMS)


@models
@pytest.mark.parametrize("junction", list(JUNCTIONS))
def test_model_builds_a_fragment(ref, junction):
    _need(ref)
    from quantcore_circuits.lom.fragment import Fragment

    frag = _fragment(ref, junction)
    assert isinstance(frag, Fragment), f"{ref}: model returned {type(frag).__name__}, not a Fragment"


@models
@pytest.mark.parametrize("junction", list(JUNCTIONS))
def test_elements_are_well_formed(ref, junction):
    _need(ref)
    from quantcore_circuits.circuit.schema import BranchType

    types = set(get_args(BranchType))
    frag = _fragment(ref, junction)
    known = set(frag.nodes) | {"gnd"}
    problems = []
    names = [e.name for e in frag.elements]
    problems += [f"duplicate element name {n}" for n in sorted({n for n in names if names.count(n) > 1})]
    for e in frag.elements:
        if INSTANCE not in e.name:
            problems.append(f"{e.name}: name does not carry the instance name {INSTANCE!r} (branch names are global)")
        if e.type not in types:
            problems.append(f"{e.name}: type {e.type!r} is not a branch type {sorted(types)}")
        if len(e.nodes) != 2:
            problems.append(f"{e.name}: {len(e.nodes)} nodes, need 2")
            continue
        problems += [f"{e.name}: node {n!r} is not a fragment node or 'gnd'" for n in e.nodes if n not in known]
        if e.nodes[0] == e.nodes[1]:
            problems.append(f"{e.name}: both ends on {e.nodes[0]!r}")
        for key, v in (e.value or {}).items():
            if isinstance(v, bool) or not isinstance(v, int | float):
                if key in _STRICTLY_POSITIVE and v is not None and not isinstance(v, list):
                    problems.append(f"{e.name}: {key} = {v!r} is not a number")
                continue
            if not math.isfinite(v):
                problems.append(f"{e.name}: {key} = {v} is not finite")
            elif key in _STRICTLY_POSITIVE and v <= 0:
                problems.append(f"{e.name}: {key} = {v} must be > 0")
            elif _UNIT.search(key) and v < 0:
                problems.append(f"{e.name}: {key} = {v} must be >= 0")
    assert not problems, f"{ref}:\n  " + "\n  ".join(problems)


@models
def test_port_nodes_target_fragment_nodes(ref):
    _need(ref)
    frag = _fragment(ref, "junction")
    known = set(frag.nodes) | {"gnd"}
    bad = {
        p: n
        for p, n in frag.port_nodes.items()
        if not (n in known or (n.startswith("control:") and len(n) > len("control:")))
    }
    assert not bad, f"{ref}: port_nodes targets must be fragment nodes, 'gnd' or 'control:<kind>': {bad}"


@models
def test_port_nodes_keys_are_component_ports(ref):
    _need(ref)
    ports = _ports(ref)
    extra = sorted(set(_fragment(ref, "junction").port_nodes) - ports)
    assert not extra, f"{ref}: port_nodes name port(s) {extra} the default cell does not have (ports: {sorted(ports)})"


@models
def test_every_component_port_is_mapped(ref):
    _need(ref)
    ports = {p for p in _ports(ref) if not p.startswith(NON_ROUTING_PORT_PREFIXES)}
    missing = sorted(ports - set(_fragment(ref, "junction").port_nodes))
    assert not missing, f"{ref}: port(s) {missing} have no LOM node; routes on them would be dropped from the netlist"


def _lines(frag) -> list:
    return list(getattr(frag, "lines", None) or [])


@models
def test_lines_are_well_formed(ref):
    _need(ref)
    frag = _fragment(ref, "junction")
    lines = _lines(frag)
    if not lines:
        return
    ports = _ports(ref)
    problems = []
    names = [ln.name for ln in lines] + [e.name for e in frag.elements]
    problems += [f"name {n} used twice (lines + elements)" for n in sorted({n for n in names if names.count(n) > 1})]
    for ln in lines:
        if INSTANCE not in ln.name:
            problems.append(f"line {ln.name}: name does not carry the instance name {INSTANCE!r}")
        if ln.node not in frag.nodes:
            problems.append(f"line {ln.name}: node {ln.node!r} is not a fragment node")
        if len(ln.ports) != 2 or len(ln.term) != 2:
            problems.append(f"line {ln.name}: needs two ends (ports {ln.ports}, term {ln.term})")
        for p in ln.ports:
            if p is None:
                continue
            if p not in ports:
                problems.append(f"line {ln.name}: end port {p!r} is not a port of the cell ({sorted(ports)})")
            elif frag.port_nodes.get(p) != ln.node:
                problems.append(f"line {ln.name}: end port {p!r} maps to {frag.port_nodes.get(p)!r}, not {ln.node!r}")
        problems += [f"line {ln.name}: end {t!r} is not 'short'/'open'" for t in ln.term if t not in ("short", "open")]
        for key in ("length_um", "a_um", "b_um"):
            v = getattr(ln, key)
            # length 0 is a termination marker (OpenToGround / ShortToGround): the routes into it give the length
            ok = isinstance(v, int | float) and math.isfinite(v) and (v >= 0 if key == "length_um" else v > 0)
            if not ok:
                problems.append(
                    f"line {ln.name}: {key} = {v!r} must be finite and {'>= 0' if key == 'length_um' else '> 0'}"
                )
        for c in ln.couplings or []:
            if c.get("node") not in frag.nodes:
                problems.append(f"line {ln.name}: coupling to {c.get('node')!r}, not a fragment node")
            for k, v in c.items():
                if isinstance(v, int | float) and not isinstance(v, bool) and not (math.isfinite(v) and v >= 0):
                    problems.append(f"line {ln.name}: coupling {k} = {v} must be finite and >= 0")
    assert not problems, f"{ref}:\n  " + "\n  ".join(problems)


HANGER_KEYS = {"line", "coupling_length_um", "ground_gap_um", "end", "source"}  # lom.fragment module docstring


@models
def test_hangers_are_well_formed(ref):
    _need(ref)
    frag = _fragment(ref, "junction")
    hangers = list(getattr(frag, "hangers", None) or [])
    if not hangers:
        return
    lines = {ln.name: ln for ln in _lines(frag)}
    problems = []
    for h in hangers:
        if not isinstance(h, dict):
            problems.append(f"hanger {h!r} is not a dict")
            continue
        tag = f"hanger on {h.get('line')!r}"
        problems += [f"{tag}: unknown key {k!r} (known: {sorted(HANGER_KEYS)})" for k in sorted(set(h) - HANGER_KEYS)]
        ln = lines.get(h.get("line"))
        if ln is None:
            problems.append(f"{tag}: names no line of the fragment ({sorted(lines)})")
        if h.get("end") not in ("short", "open"):
            problems.append(f"{tag}: end {h.get('end')!r} is not 'short'/'open'")
        elif ln is not None and h["end"] not in ln.term:
            problems.append(f"{tag}: at a {h['end']!r} end, but the line ends are {ln.term}")
        for key in ("coupling_length_um", "ground_gap_um"):
            v = h.get(key)
            if isinstance(v, bool) or not isinstance(v, int | float) or not (math.isfinite(v) and v > 0):
                problems.append(f"{tag}: {key} = {v!r} must be finite and > 0")
        cl = h.get("coupling_length_um")
        if ln is not None and isinstance(cl, int | float) and ln.length_um > 0 and cl > ln.length_um:
            problems.append(f"{tag}: coupled section {cl} um longer than the line ({ln.length_um:.0f} um)")
        if "source" in h and not isinstance(h["source"], str):
            problems.append(f"{tag}: source {h['source']!r} is not a string")
    assert not problems, f"{ref}:\n  " + "\n  ".join(problems)


def test_contract_covers_every_catalog_model():
    """Each catalog ref that has a LOM model is one of the refs checked above (none hides behind another ref)."""
    from quantcore_circuits.lom.fragment import lom_model  # pylint: disable=import-outside-toplevel

    refs = _catalog_refs()
    if not refs:
        pytest.skip("no component catalog")
    checked = set(MODEL_REFS)
    keys = {(lom_model(r), _cls_key(r)) for r in checked}
    missing = sorted(r for r in refs if lom_model(r) is not None and (lom_model(r), _cls_key(r)) not in keys)
    assert not missing, f"catalog refs with a model the contract does not check: {missing}"


@models
def test_fragment_nodes_carry_elements(ref):
    _need(ref)
    frag = _fragment(ref, "junction")
    used = {n for e in frag.elements for n in e.nodes}
    for ln in _lines(frag):
        used |= {ln.node} | {c.get("node") for c in ln.couplings or []}
    used |= set(frag.port_nodes.values())  # a wire-only node (splitter, airbridge) merges with what its ports join
    bare = sorted(set(frag.nodes) - used)
    assert not bare, f"{ref}: node(s) {bare} have no element, line or port (dead: the builder drops them)"


@models
def test_two_instances_do_not_collide(ref):
    _need(ref)
    a, b = _fragment(ref, "junction", INSTANCE), _fragment(ref, "junction", OTHER)

    def names(f):
        return {e.name for e in f.elements} | {ln.name for ln in _lines(f)}

    def islands(f):
        out = set()
        for s in f.nodes.values():
            out |= {s["island"]} if s.get("island") else set()
            out |= set(s.get("aliases", []))
        return out

    shared = names(a) & names(b)
    isl = islands(a) & islands(b)
    knobs = set(a.knobs) & set(b.knobs)
    assert not (shared or isl or knobs), (
        f"{ref}: two instances share names {sorted(shared)}, islands {sorted(isl)}, knobs {sorted(knobs)}"
    )


@models
def test_knob_ranges(ref):
    _need(ref)
    bad = {}
    for k, rng in _fragment(ref, "junction").knobs.items():
        try:
            lo, hi = (float(x) for x in rng)
        except (TypeError, ValueError):
            bad[k] = rng
            continue
        if not (math.isfinite(lo) and math.isfinite(hi) and lo <= hi):
            bad[k] = rng
    assert not bad, f"{ref}: knob ranges must be finite (lo, hi) with lo <= hi: {bad}"
