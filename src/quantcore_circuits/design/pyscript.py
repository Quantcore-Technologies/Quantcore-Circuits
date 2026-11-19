"""design.json → a readable Python script that rebuilds the same design with the :class:`Designer` API.

``qcc design to-python DESIGN -o design.py`` (the KLayout plugin's *Design ▸ Save as Python script*) writes the script;
running it writes the design.json again (``python design.py`` or ``%run design.py``) and leaves the live
:class:`~quantcore_circuits.designer.Designer` as ``d`` so the chip can be continued as code.

The script is checked before it is returned: it is executed here and the design it builds must have the same
``design_hash`` as the source. What the Designer calls cannot say (a static cell's ports, explicit ``nets``, another
chip cell, a coupling's ``fem`` flag, a waypoint's corner radius, …) is written for that one entry as a plain
``d.data[...] = {...}`` assignment with a comment, so the round trip never silently drops anything.
"""

from __future__ import annotations

import json
import keyword
import re
from pathlib import Path

from quantcore_circuits.design import canonical_json, design_hash, load_design
from quantcore_circuits.designer import Designer

_ADD_ARGS = {"name", "cell", "at", "rot", "mirror", "snap", "to", "snap_gap", "junction", "edge", "self"}
_SECTIONS = ("instances", "routes", "couplings", "targets", "sim_groups")
_WIDTH = 100


class RoundTripError(RuntimeError):
    """The generated script did not rebuild the same design."""


def _is_ident(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_]\w*", name)) and not keyword.iskeyword(name)


def _num(x) -> str:
    if isinstance(x, float) and x.is_integer() and abs(x) < 1e15:
        return f"{x:.1f}"
    return repr(x)


def lit(value, indent: int = 0, width: int = _WIDTH) -> str:
    """A Python literal for JSON-like ``value``: one line when it fits, else one entry per line."""
    one = _one_line(value)
    if len(one) + indent <= width or not isinstance(value, (dict, list)) or not value:
        return one
    pad = " " * (indent + 4)
    if isinstance(value, dict):
        body = [f"{pad}{json.dumps(str(k))}: {lit(v, indent + 4, width)}," for k, v in value.items()]
        return "{\n" + "\n".join(body) + "\n" + " " * indent + "}"
    body = [f"{pad}{lit(v, indent + 4, width)}," for v in value]
    return "[\n" + "\n".join(body) + "\n" + " " * indent + "]"


def _one_line(value) -> str:
    if isinstance(value, dict):
        return "{" + ", ".join(f"{json.dumps(str(k))}: {_one_line(v)}" for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_one_line(v) for v in value) + "]"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if value is None or isinstance(value, bool):
        return repr(value)
    if isinstance(value, (int, float)):
        return _num(value)
    return repr(value)


def _point(p) -> str:
    return f"({_num(p[0])}, {_num(p[1])})"


def _call(head: str, args: list[str], indent: int = 0) -> str:
    """``head(a, b, k=v)`` on one line, or one argument per line when it is too long."""
    one = f"{head}({', '.join(args)})"
    if len(one) + indent <= _WIDTH:
        return one
    pad = " " * (indent + 4)
    return f"{head}(\n" + "\n".join(f"{pad}{a}," for a in args) + f"\n{' ' * indent})"


def _kw(args: list[str], key: str, value, default=None) -> None:
    if value is not None and value != default:
        args.append(f"{key}={lit(value, 8)}")


# ---- one statement per design entry ---------------------------------------------------------------------------------
def _instance_stmt(name: str, spec: dict) -> str | None:
    """``d.add(...)`` for an instance, or None when the Designer call cannot say it."""
    params = spec.get("params") or {}
    if spec.get("ports") or any(k in _ADD_ARGS or not _is_ident(k) for k in params):
        return None
    place = spec["place"]
    args = [json.dumps(name), json.dumps(spec["cell"], ensure_ascii=False)]
    if place.get("snap") is not None:
        args += [f"snap={json.dumps(place['snap'])}", f"to={json.dumps(place['to'])}"]
        _kw(args, "snap_gap", place.get("gap"), 0.0)
    else:
        args.append(f"at={_point(place['at'])}")
        _kw(args, "rot", place.get("rot"), 0.0)
        _kw(args, "edge", place.get("edge"))
    _kw(args, "mirror", place.get("mirror") or None)
    j = spec.get("junction")
    if j:
        jun = {k: v for k, v in j.items() if v is not None}
        for key in ("Cj_fF", "flux_phi0", "asym"):  # defaults stay out of the script
            if jun.get(key) == 0.0:
                jun.pop(key)
        args.append(f"junction={lit(jun, 8)}")
    args += [f"{k}={lit(v, 8)}" for k, v in params.items()]
    return _call("d.add", args)


def _end_expr(end) -> str:
    if isinstance(end, str):
        return json.dumps(end)
    if "hanger" in end:
        near = end.get("near")
        args = [f"s={_num(end['s'])}"] if end.get("s") is not None else [f"near={_point(near)}"]
        args.append(f"length={_num(end['length'])}")
        for key, default in (("side", "left"), ("ground_gap", 6.0), ("direction", "forward"), ("end", "short"),
                             ("open_gap", 6.0), ("bend", True), ("coupler_gap", None), ("line_gap", None)):
            if end.get(key, default) != default:
                args.append(f"{key}={lit(end[key])}")
        return _call(f"d[{json.dumps(end['hanger'])}].hanger", args, 8)
    args = [_point(end["at"])]
    if end.get("dir") is not None:
        args.append(f"dir={_num(end['dir'])}")
    if end.get("term", 0.0) != 0.0:
        args.append(f"term={_num(end['term'])}")
    return _call("d.free_end", args, 8)


def _node_expr(node) -> str:
    if not isinstance(node, dict):
        return _point(node)
    extra = {k: v for k, v in node.items() if k not in ("at", "airbridge", "a", "b", "params") and v is not None}
    if extra or not all(_is_ident(k) for k in node.get("params") or {}):
        return lit({k: v for k, v in node.items() if v not in (None, False, {})} | {"at": list(node["at"])}, 8)
    args = [_point(node["at"])]
    _kw(args, "a", node.get("a"))
    _kw(args, "b", node.get("b"))
    if node.get("airbridge"):
        args.append("airbridge=True")
    args += [f"{k}={lit(v)}" for k, v in (node.get("params") or {}).items()]
    return _call("d.waypoint", args, 8)


def _route_stmt(name: str, spec: dict) -> str | None:
    args = [json.dumps(name), _end_expr(spec["from"]), _end_expr(spec["to"])]
    after = []  # options Designer.route cannot take: RouteHandle.set(...)
    if spec.get("type") == "meander":
        args.append(f"meander={_num(spec['length'])}")
    elif spec.get("length") is not None:
        after.append(f"length={_num(spec['length'])}")
    if spec.get("nodes"):
        nodes = [_node_expr(n) for n in spec["nodes"]]
        one = "[" + ", ".join(nodes) + "]"
        args.append(f"nodes={one}" if len(one) < 70 and "\n" not in one else
                    "nodes=[\n" + "".join(f"        {n},\n" for n in nodes) + "    ]")
    for key in ("a", "b", "r"):
        _kw(args, key, spec.get(key))
    _kw(args, "airbridges", spec.get("airbridges"), "none")
    _kw(args, "meander_direction", spec.get("meander_direction"), 1)
    for key in ("meander_segment", "meanders"):
        if spec.get(key) is not None and not (key == "meanders" and spec[key] == -1):
            after.append(f"{key}={lit(spec[key])}")
    if spec.get("params"):
        after.append(f"params={lit(spec['params'], 8)}")
    text = _call("d.route", args)
    if after:
        text += "." + _call("set", after)
    return text


def _coupling_stmt(name: str, spec: dict) -> str | None:
    if spec.get("fem", True) is not True:
        return None
    args = [json.dumps(name), json.dumps(spec["between"][0]), json.dumps(spec["between"][1])]
    kind, value = spec.get("type", "C"), spec.get("value")
    if kind == "wire":
        args.append("wire=True")
    elif kind == "L":
        args.append(f"L_nH={_num(value)}")
    elif value is not None:
        args.append(f"C_fF={_num(value)}")
    if spec.get("note"):
        args.append(f"note={json.dumps(spec['note'], ensure_ascii=False)}")
    return _call("d.couple", args)


def _group_stmt(name: str, spec: dict) -> str | None:
    args = [json.dumps(name), lit(spec["select"], 8)]
    _kw(args, "margin_um", spec.get("margin_um"), 300.0)
    _kw(args, "analyses", spec.get("analyses"), ["eigenmode_epr", "q3d_cmatrix"])
    _kw(args, "ports", spec.get("ports") or None)
    _kw(args, "settings", spec.get("settings") or None)
    return _call("d.sim_group", args)


def _targets_stmt(targets: dict) -> str | None:
    if not targets or not all(_is_ident(k) for k in targets):
        return None
    body = "".join(f"    {k}={lit(v, 4)},\n" for k, v in targets.items())
    return "d.targets(\n" + body + ")"


def _raw_stmt(section: str, name: str, spec) -> str:
    return f"d.data[{json.dumps(section)}][{json.dumps(name)}] = {lit(spec)}"


# ---- ordering -------------------------------------------------------------------------------------------------------
def _instance_order(instances: dict) -> list[str]:
    """Snap-placed instances after the instance they snap to (the Designer checks each ``add`` at once)."""
    out, seen = [], set()

    def visit(name, stack=()):
        if name in seen or name in stack:
            return
        to = (instances[name]["place"].get("to") or "").split(".", 1)[0]
        if to in instances and to != name:
            visit(to, (*stack, name))
        seen.add(name)
        out.append(name)

    for n in instances:
        visit(n)
    return out


def _route_order(routes: dict) -> list[str]:
    """Routes that hang off another route after it."""
    out, seen = [], set()

    def visit(name, stack=()):
        if name in seen or name in stack:
            return
        for end in (routes[name]["from"], routes[name]["to"]):
            if isinstance(end, dict) and end.get("hanger") in routes:
                visit(end["hanger"], (*stack, name))
        seen.add(name)
        out.append(name)

    for n in routes:
        visit(n)
    return out


# ---- the script -----------------------------------------------------------------------------------------------------
def _header(data: dict) -> str:
    chip = data["chip"]
    args = [json.dumps(data["name"]), f"box=({', '.join(_num(v) for v in chip['box'])})"]
    if data["pdk"] != Designer("x").data["pdk"]:
        args.append(f"pdk={json.dumps(data['pdk'])}")
    if chip.get("launchers") is not None:
        args.append(f"launchers={lit(chip['launchers'], 4)}")
    params = {k: v for k, v in (chip.get("params") or {}).items() if not (k == "with_grid" and v is False)}
    if params:
        args.append(f"chip={lit(params, 4)}")
    return _call("d = Designer", args)


def _statements(data: dict, raw: set) -> list[tuple[str, str | None, str]]:
    """(section, entry name, statement) in build order; ``raw`` entries are written as ``d.data[...]`` assignments."""
    out = []

    def one(section, name, fn):
        spec = data[section][name]
        stmt = None if (section, name) in raw else fn(name, spec)
        out.append((section, name, stmt if stmt is not None else _raw_stmt(section, name, spec)))

    for n in _instance_order(data["instances"]):
        one("instances", n, _instance_stmt)
    for n in _route_order(data["routes"]):
        one("routes", n, _route_stmt)
    for n in data.get("couplings") or {}:
        one("couplings", n, _coupling_stmt)
    if data.get("targets"):
        stmt = None if "targets" in raw else _targets_stmt(data["targets"])
        out.append(("targets", None, stmt or "d.data[\"targets\"] = " + lit(data["targets"])))
    for n in data.get("sim_groups") or {}:
        one("sim_groups", n, _group_stmt)
    return out


def _fixes(data: dict, raw: set) -> list[str]:
    """What the Designer arguments do not cover: another chip cell, explicit ``nets``."""
    out = []
    chip = data["chip"]
    if chip.get("cell") != "quantcore_circuits.assembly.DesignChip" or "chip" in raw:
        out.append("d.data[\"chip\"] = " + lit(chip))
    elif "with_grid" not in (chip.get("params") or {}):
        out.append("d.data[\"chip\"][\"params\"].pop(\"with_grid\")  # the Designer adds with_grid=False by default")
    if data.get("nets", "derived") != "derived":
        out.append("d.data[\"nets\"] = " + lit(data["nets"]))
    return out


_PRELUDE = "from pathlib import Path\n\nfrom quantcore_circuits.designer import Designer\n"


def _compose(data: dict, raw: set, label: str) -> tuple[str, list]:
    """(script text, its statements)."""
    stmts = _statements(data, raw)
    lines = [
        f'"""Rebuilds the design "{data["name"]}" with the Quantcore Designer API.',
        "",
        f"Generated by `qcc design to-python` from {label}. Run it (`python design.py`) to write the design.json",
        "again, or `%run` it in a notebook to carry on drawing as code: `d` is the live Designer.",
        '"""',
        "",
        *_PRELUDE.rstrip("\n").split("\n"),
        "",
        _header(data),
    ]
    last = None
    for section, _name, stmt in stmts:
        if section != last:
            lines += ["", f"# {section.replace('_', ' ')}"]
            last = section
        if stmt.startswith("d.data["):
            stmt = "# (plain data: the Designer call cannot say every field of this entry)\n" + stmt
        lines.append(stmt)
    fixes = _fixes(data, raw)
    if fixes:
        lines += ["", "# chip and net settings the Designer arguments do not cover", *fixes]
    lines += ["", 'if __name__ == "__main__":', f"    d.save(Path(__file__).with_name({json.dumps(data['name'] + '.json')}))", ""]
    return "\n".join(lines), stmts


def _run(data: dict, stmts: list, raw: set):
    """Execute the header and statements; (Designer, None), or (None, entry that failed, error text)."""
    ns: dict = {}
    exec(_PRELUDE, ns)  # noqa: S102
    exec(_header(data), ns)  # noqa: S102
    for section, name, stmt in stmts:
        try:
            exec(stmt, ns)  # noqa: S102
        except Exception as e:  # noqa: BLE001
            return None, (section, name) if name else section, f"{type(e).__name__}: {e}"
    for fix in _fixes(data, raw):
        exec(fix, ns)  # noqa: S102
    return ns["d"], None, ""


def _diff(want: dict, got: dict) -> set:
    """Entries ``(section, name)`` (or ``"targets"`` / ``"chip"``) where the rebuilt design differs from the source."""
    bad = set()
    for section in ("instances", "routes", "couplings", "sim_groups"):
        w, g = want.get(section) or {}, got.get(section) or {}
        bad |= {(section, n) for n in set(w) | set(g) if canonical_json(w.get(n)) != canonical_json(g.get(n))}
    if canonical_json(want.get("targets") or {}) != canonical_json(got.get("targets") or {}):
        bad.add("targets")
    if canonical_json(want["chip"]) != canonical_json(got["chip"]):
        bad.add("chip")
    return bad


def design_to_python(source, check: bool = True) -> str:
    """The script text for ``source`` (a design file, dict or :class:`Design`). With ``check`` (default) the script is
    executed and must rebuild a design with the same ``design_hash`` (else :class:`RoundTripError`); an entry the
    Designer rejects or rebuilds differently is written as plain data."""
    design = load_design(source)
    data = design.to_json_dict()
    label = Path(source).name if isinstance(source, (str, Path)) else f"the design {design.name}"
    raw: set = set()
    script, stmts = _compose(data, raw, label)
    if not check:
        return script
    for _ in range(6):
        built, failed, error = _run(data, stmts, raw)
        if built is None:
            if failed in raw or failed is None:
                raise RoundTripError(f"{design.name}: the generated script fails at {failed}: {error}")
            raw.add(failed)
        else:
            rebuilt = built.design
            if design_hash(rebuilt) == design_hash(design) and canonical_json(rebuilt.to_json_dict()) == canonical_json(data):
                return script
            bad = _diff(data, rebuilt.to_json_dict()) - raw
            if not bad:
                raise RoundTripError(f"{design.name}: the rebuilt design differs from the source in an unexpected place")
            raw |= bad
        script, stmts = _compose(data, raw, label)
    raise RoundTripError(f"{design.name}: the generated script does not rebuild the same design")


def write_python(source, out: str | Path, check: bool = True) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(design_to_python(source, check=check), encoding="utf-8")
    return out


__all__ = ["RoundTripError", "design_to_python", "lit", "write_python"]
