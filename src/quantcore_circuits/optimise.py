"""Closed-loop design feedback: tune geometry knobs in ``design.json`` until extracted parameters hit targets.

Knobs are dotted paths into the design: ``"Q1.cross_length"`` (instance parameter), ``"R1.length"`` (route field),
``"R1.to.length"`` (nested route field, e.g. a hanger coupler length), ``"Q1.junction.Lj_nH"`` (an instance field).
Parameter paths may go deeper (:func:`get_knob`): ``"Q2.cpl_length.1"`` (an element of a list parameter),
``"Q2.arm_length.*"`` (every element of a list, scaled together; the knob value is their mean) and
``"Q11.connection_pads.readout.pad_width"`` (a nested option, e.g. a Metal connection pad; unset options take the
cell's default). Lengths with a unit (Metal ``"30um"``, ``"0.1mm"``) read as µm and are written back in their unit.
Targets are ``"<instance>.<quantity>"``, e.g. ``"Q1.f_q_GHz"``. The evaluator maps a design to extracted parameters
(``{"Q1": {"f_q_GHz": ...}}``); the default :func:`pipeline_evaluator` runs build → simulation job → solver → parse →
extract.

Few, expensive evaluations: 1 knob uses a bounded secant method, n knobs a finite-difference Gauss-Newton step.
"""

from __future__ import annotations

import ast
import copy
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from quantcore_circuits import track as _track
from quantcore_circuits.design import Design, design_hash, load_design

Evaluator = Callable[[Design], dict]


INSTANCE_FIELDS = ("cell", "params", "place", "ports", "junction")
_UNIT_UM = {"um": 1.0, "µm": 1.0, "nm": 1e-3, "mm": 1e3}
_NUMBER = re.compile(r"^\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(um|µm|nm|mm)?\s*$")


def knob_number(value) -> float:
    """A knob value as a float: a number, a numeric string or a length with a unit (``"30um"``, ``"0.1mm"`` → µm);
    a list: the mean of its elements (the value of a ``"<param>.*"`` knob)."""
    if isinstance(value, bool):
        raise ValueError(f"not a number: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = _NUMBER.match(value)
        if m:
            return float(m.group(1)) * _UNIT_UM.get(m.group(2) or "um", 1.0)
    if isinstance(value, (list, tuple)) and value:
        return float(np.mean([knob_number(v) for v in value]))
    raise ValueError(f"not a number: {value!r}")


def get_knob(design: Design, knob: str):
    """The value of ``knob`` (module docstring): the design's own value, else the cell default (Metal: the class's
    default options, and for a nested option such as ``connection_pads.<pad>.<option>`` its ``_default_*`` template).
    Numbers come back as they are stored; lengths with a unit and ``*`` (list) knobs as floats (µm)."""
    data = design.to_json_dict()
    head, *rest = knob.split(".")
    if not rest:
        raise KeyError(f"knob {knob!r}: no parameter after {head!r}")
    if head in data["instances"]:
        inst = data["instances"][head]
        flux_or_asym = rest[0] == "junction" and rest[1:] in (["flux_phi0"], ["asym"])
        if flux_or_asym and rest[1] not in (inst.get("junction") or {}):
            value = 0.0  # unset flux / asymmetry: the default (a symmetric SQUID at its sweet spot)
        elif len(rest) > 1 and rest[0] in INSTANCE_FIELDS:  # an instance field, e.g. junction.Lj_nH
            value = _walk(inst, rest, knob)
        else:
            value = _param_value(inst, rest, knob)
    elif head in data["routes"]:
        value = _walk(data["routes"][head], rest, knob)
    else:
        raise KeyError(f"knob {knob!r}: no instance or route {head!r}")
    return knob_number(value) if rest[-1] == "*" else _leaf(value)


def set_knob(design: Design, knob: str, value) -> Design:
    """``design`` with ``knob`` set to ``value`` (a copy). A length stored with a unit keeps its unit; ``*`` scales
    every element of the list so that their mean is ``value``; an unset parameter or option is created."""
    data = copy.deepcopy(design.to_json_dict())
    head, *rest = knob.split(".")
    if not rest:
        raise KeyError(f"knob {knob!r}: no parameter after {head!r}")
    if head in data["instances"]:
        inst = data["instances"][head]
        if len(rest) > 1 and rest[0] in INSTANCE_FIELDS:
            _put(inst, rest, value, knob)
        else:
            _param_put(inst, rest, value, knob)
    elif head in data["routes"]:
        _put(data["routes"][head], rest, value, knob)
    else:
        raise KeyError(f"knob {knob!r}: no instance or route {head!r}")
    return Design.model_validate(data)


def knob_path(design: Design, knob: str) -> tuple:
    """Where ``knob`` lives in ``design.to_json_dict()`` (list indices as ints, without a trailing ``*``): the leaf
    changes a proposal makes to the knob are under this path."""
    data = design.to_json_dict()
    head, *rest = knob.split(".")
    parts = [int(p) if p.isdigit() else p for p in rest if p != "*"]
    if head in data["instances"]:
        if len(rest) > 1 and rest[0] in INSTANCE_FIELDS:
            return ("instances", head, *parts)
        inst = data["instances"][head]
        flat = inst.get("params") or {}
        if rest[0] not in flat and rest[0] in _options(flat):
            return ("instances", head, "params", "options")
        return ("instances", head, "params", *parts)
    return ("routes", head, *parts)


def _leaf(v):
    """A stored value as a knob value: numeric / unit strings as floats (µm), anything else as it is."""
    if isinstance(v, str):
        try:
            return knob_number(v)
        except ValueError:
            return v
    return v


def _as_dict(v):
    """A dict, or the JSON / Python-literal text of one (KLayout PCell forms store dict parameters as text); None for
    anything else."""
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v.strip().startswith("{"):
        try:
            out = json.loads(v)
        except ValueError:
            try:
                out = ast.literal_eval(v.strip())
            except (ValueError, SyntaxError):
                return None
        if isinstance(out, dict):
            return out
    return None


def _step(node, part: str, knob: str):
    if isinstance(node, (list, tuple)):
        return node[int(part)]
    d = _as_dict(node)
    if d is None or part not in d:
        raise KeyError(f"knob {knob!r}: {part!r} is not set")
    return d[part]


def _walk(node, parts, knob: str):
    for i, part in enumerate(parts):
        if part == "*":
            if i != len(parts) - 1 or not isinstance(node, (list, tuple)):
                raise KeyError(f"knob {knob!r}: '*' must be the last part, on a list")
            return list(node)
        node = _step(node, part, knob)
    return node


def _options(flat: dict) -> dict:
    """A wrapper cell's ``options`` (dict or JSON text, e.g. what the plugin's parameter table writes)."""
    return _as_dict(flat.get("options")) or {}


def _cell_defaults(cell: str) -> dict:
    """Default parameters of a cell: Metal ``metal:<Class>`` its default options, else the PCell schema defaults."""
    if cell.startswith("metal:"):
        from quantcore_circuits.layouts.metal.geometry import template_options  # pylint: disable=C0415

        return template_options(cell.split(":", 1)[1])
    from quantcore_circuits.layouts.registry import resolve_cell  # pylint: disable=import-outside-toplevel

    return {k: v.default for k, v in resolve_cell(cell).get_schema().items()}


def _entry_defaults(cell: str, top: str) -> dict:
    """Defaults of one entry of a dict parameter (``connection_pads.<pad>``): Metal's ``_default_<top>`` template, or
    the cell module's ``DEFAULT_CONNECTION_PAD`` (the SQDMetal re-implementations)."""
    if cell.startswith("metal:"):
        return dict(_cell_defaults(cell).get(f"_default_{top}") or {})
    if top == "connection_pads":
        import importlib  # pylint: disable=import-outside-toplevel

        from quantcore_circuits.layouts.registry import resolve_cell  # pylint: disable=import-outside-toplevel

        mod = importlib.import_module(resolve_cell(cell).__module__)
        return dict(getattr(mod, "DEFAULT_CONNECTION_PAD", {}) or {})
    return {}


def _param_value(inst: dict, rest, knob: str):
    flat = dict(inst.get("params") or {})
    opts = _options(flat)
    top = rest[0]
    if top in flat and top != "options":
        node = flat[top]
    elif top in opts:
        node = opts[top]
    else:
        defaults = _cell_defaults(inst["cell"])
        if top not in defaults:
            raise KeyError(f"knob {knob!r}: {inst['cell']} has no parameter {top!r}")
        node = defaults[top]
    if len(rest) >= 3 and _as_dict(node) is not None:  # <top>.<entry>.<option>: the option's default when unset
        entry = _step(node, rest[1], knob)
        d = {**_entry_defaults(inst["cell"], top), **(_as_dict(entry) or {})}
        if rest[2] not in d:
            raise KeyError(f"knob {knob!r}: {rest[2]!r} is not an option of {top}.{rest[1]}")
        return _walk(d[rest[2]], rest[3:], knob)
    return _walk(node, rest[1:], knob)


def _like(old, value):
    """``value`` in the form ``old`` was stored: a unit string keeps its unit, other numbers become floats;
    non-numeric values are stored as they are."""
    if isinstance(value, bool) or not isinstance(value, (int, float, np.floating, np.integer)):
        return value
    if isinstance(old, str):
        m = _NUMBER.match(old)
        if m and m.group(2):
            return f"{float(value) / _UNIT_UM[m.group(2)]:.6g}{m.group(2)}"
    return float(value) if isinstance(value, (np.floating, np.integer)) else value


def _put(node, parts, value, knob: str) -> None:
    """Set ``parts`` under ``node`` (dicts, lists, dict-valued JSON text), creating missing dict keys."""
    *path, last = parts
    if last == "*":
        lst = _walk(node, path, knob) if path else node
        if not isinstance(lst, list):
            raise KeyError(f"knob {knob!r}: '*' needs a list")
        mean = knob_number(lst)
        for i, el in enumerate(lst):
            lst[i] = _like(el, round(knob_number(el) * value / mean, 4) if mean else value)
        return
    for i, part in enumerate(path):
        if isinstance(node, list):
            node = node[int(part)]
            continue
        child = node.get(part)
        if isinstance(child, str):  # a dict kept as JSON text: change it there and write the text back
            sub = _as_dict(child)
            if sub is None:
                raise KeyError(f"knob {knob!r}: {part!r} is {child!r}, not a dict")
            _put(sub, [*path[i + 1 :], last], value, knob)
            node[part] = json.dumps(sub)
            return
        if child is None:  # e.g. a junction that is not set yet
            child = node[part] = {}
        node = child
    if isinstance(node, list):
        node[int(last)] = _like(node[int(last)], value)
    else:
        node[last] = _like(node.get(last), value)


def _param_put(inst: dict, rest, value, knob: str) -> None:
    flat = inst.setdefault("params", {})
    top = rest[0]
    if top not in flat and top in _options(flat):  # stored in the wrapper's options: change it there
        opts = _options(flat)
        _put(opts, rest, value, knob)
        flat["options"] = json.dumps(opts) if isinstance(flat.get("options"), str) else opts
        return
    if top not in flat and len(rest) > 1:  # a list / dict parameter left at its default: start from the default
        flat[top] = copy.deepcopy(_param_value(inst, [top], knob))
    if len(rest) >= 3 and isinstance(flat.get(top), (dict, str)):
        entry_parent = flat[top]
        parsed = _as_dict(entry_parent)
        if parsed is not None:
            _put(parsed, rest[1:], value, knob)
            flat[top] = json.dumps(parsed) if isinstance(entry_parent, str) else parsed
            return
    _put(flat, rest, value, knob)


def _resolve(data: dict, knob: str):
    head, *rest = knob.split(".")
    if head in data["instances"]:
        node = data["instances"][head]
        if len(rest) == 1:
            return node["params"], rest[0]
        base = node
    elif head in data["routes"]:
        base = data["routes"][head]
    else:
        raise KeyError(f"knob {knob!r}: no instance or route {head!r}")
    for part in rest[:-1]:
        base = base[part]
    return base, rest[-1]


@dataclass
class Iteration:
    knobs: dict
    metrics: dict
    error: dict
    design_hash: str


@dataclass
class OptimiseResult:
    design: Design
    converged: bool
    history: list[Iteration] = field(default_factory=list)


def _target_values(metrics: dict, targets: dict) -> np.ndarray:
    out = []
    for key in targets:
        inst, qty = key.split(".", 1)
        v = metrics.get(inst, {}).get(qty)
        if v is None:
            v = metrics.get(inst, {}).get(qty.replace("_GHz", "_eig_GHz"))
        if v is None:
            raise KeyError(f"evaluator did not return {key}")
        out.append(float(v))
    return np.asarray(out)


def optimise(
    source,
    knobs: dict[str, tuple[float, float]],
    targets: dict[str, float],
    evaluate: Evaluator,
    tolerance: dict[str, float] | None = None,
    max_iter: int = 6,
    step: float = 0.02,
    log=print,
) -> OptimiseResult:
    """Tune ``knobs`` (with bounds) so that ``targets`` are met within ``tolerance`` (absolute, per target)."""
    design = load_design(source)
    names = list(knobs)
    lo = np.array([knobs[k][0] for k in names], dtype=float)
    hi = np.array([knobs[k][1] for k in names], dtype=float)
    want = np.array([targets[k] for k in targets], dtype=float)
    tol = np.array([(tolerance or {}).get(k, 1e-3 * max(abs(targets[k]), 1)) for k in targets])
    x = np.array([float(get_knob(design, k)) for k in names])
    history: list[Iteration] = []

    def run(xv) -> np.ndarray:
        d = design
        for k, v in zip(names, xv):
            d = set_knob(d, k, float(v))
        metrics = evaluate(d)
        y = _target_values(metrics, targets)
        err = dict(zip(targets, (y - want).tolist()))
        history.append(Iteration(dict(zip(names, xv.tolist())), metrics, err, design_hash(d)))
        log(f"[optimise] {dict(zip(names, np.round(xv, 4)))} -> {dict(zip(targets, np.round(y, 4)))}")
        _track.emit(
            "optimise",
            index=len(history) - 1,
            knobs=dict(zip(names, xv.tolist())),
            metrics=metrics,
            error=err,
            tol=dict(zip(targets, tol.tolist())),
            design=d,
        )
        return y

    try:
        y = run(x)
        prev = None
        for _ in range(max_iter - 1):
            r = y - want
            if np.all(np.abs(r) <= tol):
                break
            if len(names) == 1 and len(want) == 1:
                if prev is None:  # first step: finite-difference slope
                    dx = step * max(abs(x[0]), 1.0)
                    x1 = np.clip(x + dx, lo, hi)
                    y1 = run(x1)
                    slope = (y1[0] - y[0]) / (x1[0] - x[0])
                    prev, x, y = (x1, y1), x1, y1
                else:
                    (xp, yp) = prev
                    slope = (y[0] - yp[0]) / (x[0] - xp[0]) if x[0] != xp[0] else 0.0
                if slope == 0:
                    break
                x_new = np.clip(x - (y - want) / slope, lo, hi)
                prev = (x, y)
                x, y = x_new, run(x_new)
            else:
                jac = np.zeros((len(want), len(names)))
                for i in range(len(names)):
                    dx = np.zeros_like(x)
                    dx[i] = step * max(abs(x[i]), 1.0)
                    jac[:, i] = (run(np.clip(x + dx, lo, hi)) - y) / dx[i]
                delta = np.linalg.lstsq(jac, -(y - want), rcond=None)[0]
                x = np.clip(x + delta, lo, hi)
                y = run(x)
    except BaseException as e:
        _track.emit("optimise_end", converged=False, error=f"{type(e).__name__}: {e}", evaluations=len(history),
                    design=design)
        raise
    best = min(history, key=lambda it: float(np.sum((np.array(list(it.error.values())) / tol) ** 2)))
    final = design
    for k, v in best.knobs.items():
        final = set_knob(final, k, v)
    converged = all(abs(best.error[k]) <= t for k, t in zip(targets, tol))
    _track.emit("optimise_end", converged=converged, evaluations=len(history), design=final)
    return OptimiseResult(final, converged, history)


def pipeline_evaluator(group: str, analysis: str, job_root: str | Path = "build/jobs", **settings) -> Evaluator:
    """build → sim job → run (local solver) → parse → extract, for use with :func:`optimise`."""
    from quantcore_circuits.analysis.extract import extract  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.analysis.results import collect_results  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools import build_simulation, export_job  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools.runner import run_job  # pylint: disable=import-outside-toplevel

    def evaluate(design: Design) -> dict:
        job_dir = Path(job_root) / f"{design.name}_{group}_{analysis}_{design_hash(design)}"
        if not (job_dir / "results" / "results.json").exists():
            setup = build_simulation(design, group, analysis)
            export_job(setup, job_dir, overwrite=True, **settings)
            run_job(job_dir)
        return extract(design, collect_results(job_dir))

    return evaluate
