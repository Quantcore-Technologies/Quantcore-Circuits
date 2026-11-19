"""Read an AEDT project file (``.aedt``) without AEDT: designs, materials, parts, boundaries, nets, setups, sweeps.

The ``.aedt`` format is a tree of ``$begin 'Name'`` … ``$end 'Name'`` blocks holding ``Key=Value`` lines and
``Name(args)`` calls (e.g. ``Objects(6, 84)``, ``VariableProp('Lj_1', 'UD', '', '1.2e-08H')``). :func:`parse_aedt`
builds that tree; :func:`project_info` extracts what a qcc render must contain; :func:`check_settings` compares a
job's solver settings (``job.json`` ``settings``) with the setup that landed in the project.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_BEGIN = re.compile(r"^\s*\$begin '(.*)'\s*$")
_END = re.compile(r"^\s*\$end '(.*)'\s*$")
_CALL = re.compile(r"^\s*([A-Za-z_][\w ]*)\((.*)\)\s*$")
_KV = re.compile(r"^\s*('[^']*'|[^=\s'(\[]+)=(.*)$")
_NUM = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")


@dataclass
class Block:
    name: str
    attrs: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)  # (name, raw args)
    children: list = field(default_factory=list)

    def child(self, name: str) -> Block | None:
        return next((c for c in self.children if c.name == name), None)

    def find(self, name: str) -> Block | None:
        """First descendant block called ``name`` (depth first)."""
        for c in self.children:
            if c.name == name:
                return c
            hit = c.find(name)
            if hit is not None:
                return hit
        return None

    def find_all(self, name: str) -> list[Block]:
        out = []
        for c in self.children:
            if c.name == name:
                out.append(c)
            out += c.find_all(name)
        return out

    def flat(self, prefix: str = "") -> dict:
        """attrs of this block and its children as ``{"Child.Key": value}`` (one dict, nested names joined)."""
        out = {prefix + k: v for k, v in self.attrs.items()}
        for c in self.children:
            out.update(c.flat(f"{prefix}{c.name}."))
        return out


def _value(raw: str):
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] == "'":
        return s[1:-1]
    if s in ("true", "false"):
        return s == "true"
    if _NUM.match(s):
        return float(s) if any(c in s for c in ".eE") else int(s)
    return s


def parse_aedt(source) -> Block:
    """Parse an ``.aedt`` file (path) or its text into a :class:`Block` tree (root name ``""``)."""
    text = source if isinstance(source, str) and "\n" in source else Path(source).read_text("utf-8", "replace")
    root = Block("")
    stack = [root]
    for line in text.splitlines():
        m = _BEGIN.match(line)
        if m:
            b = Block(m.group(1))
            stack[-1].children.append(b)
            stack.append(b)
            continue
        m = _END.match(line)
        if m:
            if len(stack) > 1:
                stack.pop()
            continue
        m = _CALL.match(line)
        if m and "=" not in line.split("(", 1)[0]:
            stack[-1].calls.append((m.group(1), m.group(2)))
            continue
        m = _KV.match(line)
        if m:
            key = m.group(1).strip("'")
            stack[-1].attrs[key] = _value(m.group(2))
    return root


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def _ints(raw: str) -> list[int]:
    return [int(x) for x in re.findall(r"-?\d+", raw)]


def _quoted(raw: str) -> list[str]:
    return re.findall(r"'([^']*)'", raw)


DESIGN_BLOCKS = {"HFSSModel": "HFSS", "Q3DModel": "Q3D Extractor", "2DExtractorModel": "2D Extractor"}


def _parts(design: Block) -> dict[int, dict]:
    parts: dict[int, dict] = {}
    top = design.find("ToplevelParts")
    for gp in top.children if top else []:
        if gp.name != "GeometryPart":
            continue
        attrs = gp.child("Attributes").attrs if gp.child("Attributes") else {}
        ops = gp.child("Operations")
        first = next((o for o in (ops.children if ops else []) if o.name == "Operation"), None)
        if first is None:
            continue
        pid = first.attrs.get("ParentPartID")
        info = {
            "name": attrs.get("Name"),
            "material": str(attrs.get("MaterialValue", "")).strip('"'),
            "solve_inside": attrs.get("SolveInside"),
            "operation": first.attrs.get("OperationType"),
        }
        box = first.child("BoxParameters")
        if box is not None:
            info["box"] = {k: box.attrs[k] for k in ("XPosition", "YPosition", "ZPosition", "XSize", "YSize", "ZSize")}
        parts[int(pid)] = info
    return parts


def _design_info(design: Block) -> dict:
    parts = _parts(design)
    names = {pid: p["name"] for pid, p in parts.items()}
    variables = {}
    props = design.find("Properties")
    for name, raw in props.calls if props else []:
        if name == "VariableProp":
            q = _quoted(raw)
            if q:
                variables[q[0]] = q[-1]
    bounds = {}
    bset = design.find("BoundarySetup")
    bblock = bset.child("Boundaries") if bset else None
    for b in bblock.children if bblock else []:
        objs = next((_ints(raw) for n, raw in b.calls if n == "Objects"), [])
        entry = {k: v for k, v in b.attrs.items() if k not in ("ID", "IsComponent", "ParentBndID")}
        entry["objects"] = [names.get(o, o) for o in objs]
        terminals = b.find("Terminals") or b.child("Terminals")
        if terminals is not None:
            entry["terminals"] = [t.name for t in terminals.children]
        bounds[b.name] = entry
    setups = {}
    solve = design.find("SolveSetups")
    for s in solve.children if solve else []:
        flat = s.flat()
        sweeps = {}
        for sw in s.find_all("Sweeps"):
            for x in sw.children:
                sweeps[x.name] = x.flat()
        setups[s.name] = {"settings": flat, "sweeps": sweeps}
    mesh_ops = {}
    mops = design.find("MeshOperations")
    for op in mops.children if mops else []:
        objs = next((_ints(raw) for n, raw in op.calls if n == "Objects"), [])
        mesh_ops[op.name] = {**op.attrs, "objects": [names.get(o, o) for o in objs]}
    out = {
        "name": design.attrs.get("Name"),
        "solution_type": design.attrs.get("SolutionType"),
        "variables": variables,
        "parts": list(parts.values()),
        "boundaries": bounds,
        "setups": setups,
        "mesh_operations": mesh_ops,
    }
    # Q3D: signal nets → the KQC excitation numbers of their objects (layer "1t1_signal_<n>", object "<layer>_<k>")
    nets = {}
    for bname, b in bounds.items():
        if b.get("BoundType") in ("SignalNet", "GroundNet", "FloatingNet"):
            exc = sorted({int(m.group(1)) for o in b["objects"] if (m := re.search(r"signal_(\d+)_\d+$", str(o)))})
            nets[bname] = {"type": b["BoundType"], "objects": b["objects"], "excitations": exc}
    out["nets"] = nets
    return out


def project_info(project) -> dict:
    """Designs (type, name, solution type, variables, parts, boundaries, nets, setups/sweeps) and materials."""
    root = parse_aedt(project)
    proj = root.child("AnsoftProject") or root
    mats = {}
    defs = proj.child("Definitions")
    mblock = defs.child("Materials") if defs else None
    for m in mblock.children if mblock else []:
        keys = ("permittivity", "dielectric_loss_tangent", "conductivity")
        mats[m.name] = {k: _num(m.attrs[k]) for k in keys if k in m.attrs}
    designs = []
    for b in proj.children:
        if b.name in DESIGN_BLOCKS:
            designs.append({"design_type": DESIGN_BLOCKS[b.name], **_design_info(b)})
    return {"materials": mats, "designs": designs}


def _ghz(v):
    if isinstance(v, (int, float)):
        return float(v)
    m = re.match(r"^\s*([-+0-9.eE]+)\s*([a-zA-Z]*)", str(v))
    if not m:
        return None
    scale = {"": 1.0, "ghz": 1.0, "mhz": 1e-3, "khz": 1e-6, "hz": 1e-9}.get(m.group(2).lower())
    return float(m.group(1)) * scale if scale is not None else None


# job.json setting → (path in the AEDT setup's flattened attrs, kind); "sweep:" paths are read from the first sweep
SETTING_KEYS = {
    "q3d_cmatrix": {
        "percent_error": ("Cap.PerError", "num"),
        "maximum_passes": ("Cap.MaxPass", "num"),
        "minimum_passes": ("Cap.MinPass", "num"),
        "minimum_converged_passes": ("Cap.MinConvPass", "num"),
        "percent_refinement": ("Cap.PerRefine", "num"),
        "frequency": ("AdaptiveFreq", "ghz"),
    },
    "hfss_eigenmode": {
        "n_modes": ("NumModes", "num"),
        "min_frequency": ("MinimumFrequency", "ghz"),
        "max_delta_f": ("MaxDeltaFreq", "num"),
        "maximum_passes": ("MaximumPasses", "num"),
        "minimum_passes": ("MinimumPasses", "num"),
        "minimum_converged_passes": ("MinimumConvergedPasses", "num"),
        "percent_refinement": ("PercentRefinement", "num"),
        "basis_order": ("BasisOrder", "num"),
    },
    "hfss_driven": {
        "frequency": ("Frequency", "ghz"),
        "max_delta_s": ("MaxDeltaS", "num"),
        "maximum_passes": ("MaximumPasses", "num"),
        "minimum_passes": ("MinimumPasses", "num"),
        "minimum_converged_passes": ("MinimumConvergedPasses", "num"),
        "percent_refinement": ("PercentRefinement", "num"),
        "basis_order": ("BasisOrder", "num"),
        "sweep_enabled": ("sweep:IsEnabled", "bool"),
        "sweep_start": ("sweep:RangeStart", "ghz"),
        "sweep_end": ("sweep:RangeEnd", "ghz"),
        "sweep_count": ("sweep:RangeCount", "num"),
        "sweep_type": ("sweep:Type", "str"),
    },
}
SETTING_KEYS["eigenmode_epr"] = SETTING_KEYS["hfss_eigenmode"]
# settings that are not AEDT setup fields (handled elsewhere by KQC's import)
NOT_IN_SETUP = {"integrate_energies": "KQC adds energy-integral reports instead", "pyepr": "post-process options"}


def check_settings(project, analysis: str, settings: dict, setup: str = "Setup1") -> list[dict]:
    """Rows ``{"key", "expected", "found", "ok", "where"}``: every job setting read back from the AEDT setup.

    ``ok`` is None for a setting that is not an AEDT setup field (e.g. ``integrate_energies``)."""
    info = project if isinstance(project, dict) else project_info(project)
    design = info["designs"][0]
    s = design["setups"].get(setup, {"settings": {}, "sweeps": {}})
    sweep = next(iter(s["sweeps"].values()), {})
    rows = []
    for key, expected in settings.items():
        if key == "mesh_size":  # KQC: one length-based mesh operation "mesh_size_<layer pattern>" per entry
            for layer, length in (expected or {}).items():
                op = design.get("mesh_operations", {}).get(f"mesh_size_{layer}", {})
                found = op.get("MaxLength")
                ok = found is not None and abs(float(str(found).replace("um", "")) - float(length)) < 1e-9
                ok = ok and bool(op.get("objects")) and op.get("Enabled", True) is not False
                rows.append(
                    {
                        "key": f"mesh_size.{layer}",
                        "expected": length,
                        "found": found,
                        "ok": bool(ok),
                        "where": f"MeshOperations.mesh_size_{layer} ({len(op.get('objects', []))} objects)",
                    }
                )
            continue
        spec = SETTING_KEYS.get(analysis, {}).get(key)
        if spec is None:
            rows.append({"key": key, "expected": expected, "found": None, "ok": None, "where": NOT_IN_SETUP.get(key)})
            continue
        where, kind = spec
        found = sweep.get(where[6:]) if where.startswith("sweep:") else s["settings"].get(where)
        if kind == "ghz":
            ok = found is not None and abs(_ghz(found) - float(expected)) < 1e-9 * max(1.0, abs(float(expected)))
        elif kind == "num":
            ok = found is not None and abs(float(found) - float(expected)) < 1e-12 * max(1.0, abs(float(expected)))
        elif kind == "bool":
            ok = found is not None and bool(found) == bool(expected)
        else:
            ok = found is not None and str(found).lower() == str(expected).lower()
        rows.append({"key": key, "expected": expected, "found": found, "ok": bool(ok), "where": f"{setup}.{where}"})
    return rows
