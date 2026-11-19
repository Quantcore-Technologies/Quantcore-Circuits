"""design.json edits behind the Edit menu's rename / chip settings / junction / coupling / pad-edge actions.

Plain Python (no pya), so they are unit-tested outside KLayout; ``edits.py`` holds the dialogs and menu actions.
Every function changes the design dict in place (and returns it, or a description) and raises ``ValueError`` with a
message fit for the status bar.
"""

from __future__ import annotations

RESERVED = ("chip",)  # quantcore_circuits.design.schema.CHIP: the chip itself is addressable under this name


def _swap_ref(value, old: str, new: str):
    """``old`` / ``old.port`` → ``new`` / ``new.port`` (anything else is returned as it is)."""
    if isinstance(value, str):
        if value == old:
            return new
        if value.startswith(old + "."):
            return new + value[len(old):]
    return value


def _check_name(design: dict, old: str, new: str, what: str) -> str:
    new = (new or "").strip()
    if not new:
        raise ValueError("the name is empty")
    if new == old:
        return new
    if "." in new or any(c.isspace() for c in new):
        raise ValueError(f"{new!r}: a name has no dots or spaces (a dot separates the port in 'Q1.claw_n')")
    taken = set(design.get("instances", {})) | set(design.get("routes", {})) | set(RESERVED)
    if new in taken:
        raise ValueError(f"{new!r} is already used by another {what} or route")
    return new


def _rekey(mapping: dict, old: str, new: str) -> dict:
    """The dict with key ``old`` renamed to ``new`` at the same position."""
    return {(new if k == old else k): v for k, v in mapping.items()}


def _swap_couplings_groups(design: dict, old: str, new: str, kind: str) -> None:
    for c in (design.get("couplings") or {}).values():
        c["between"] = [_swap_ref(e, old, new) for e in c.get("between", [])]
    for g in (design.get("sim_groups") or {}).values():
        g["select"] = [new if e == old else e for e in g.get("select", [])]
        if kind == "route" and old in g.get("ports", {}):
            g["ports"] = _rekey(g["ports"], old, new)
    if old in (design.get("targets") or {}):
        design["targets"] = _rekey(design["targets"], old, new)


def rename_instance(design: dict, old: str, new: str) -> dict:
    """Rename instance ``old`` to ``new`` everywhere the design refers to it: routes' ends, snap placements, targets,
    sim groups, couplings. Order of ``instances`` is kept."""
    if old not in design.get("instances", {}):
        raise ValueError(f"no instance {old!r}")
    new = _check_name(design, old, new, "instance")
    if new == old:
        return design
    design["instances"] = _rekey(design["instances"], old, new)
    for entry in design["instances"].values():
        place = entry.get("place", {})
        for k in ("snap", "to"):
            if k in place:
                place[k] = _swap_ref(place[k], old, new)
    for route in design.get("routes", {}).values():
        for k in ("from", "to"):
            route[k] = _swap_ref(route.get(k), old, new)
    _swap_couplings_groups(design, old, new, "instance")
    return design


def rename_route(design: dict, old: str, new: str) -> dict:
    """Rename route ``old``: hanger ends that hang off it, targets, sim groups, couplings follow."""
    if old not in design.get("routes", {}):
        raise ValueError(f"no route {old!r}")
    new = _check_name(design, old, new, "instance")
    if new == old:
        return design
    design["routes"] = _rekey(design["routes"], old, new)
    for route in design["routes"].values():
        end = route.get("to")
        if isinstance(end, dict) and end.get("hanger") == old:
            end["hanger"] = new
    _swap_couplings_groups(design, old, new, "route")
    return design


def set_chip(design: dict, name_chip: str | None = None, with_grid: bool | None = None, size=None) -> list[str]:
    """Chip settings: the label written on the die (``chip.params.name_chip``), the ground-plane grid
    (``with_grid``), the die ``size`` = (width, height) µm (its lower left corner stays where it is). Returns what
    changed."""
    chip = design.setdefault("chip", {})
    params = chip.setdefault("params", {})
    done = []
    if name_chip is not None and params.get("name_chip") != name_chip:
        params["name_chip"] = name_chip
        done.append(f"label {name_chip!r}")
    if with_grid is not None and bool(params.get("with_grid", False)) != bool(with_grid):
        if with_grid:
            params["with_grid"] = True
        else:
            params.pop("with_grid", None)  # absent = no KQC ground grid (the PDK band is used)
        done.append(f"with_grid {bool(with_grid)}")
    if size is not None:
        w, h = float(size[0]), float(size[1])
        if w < 1000 or h < 1000:
            raise ValueError("the die must be at least 1000 µm in each direction")
        box = chip.get("box") or [0.0, 0.0, 7500.0, 7500.0]
        new = [box[0], box[1], box[0] + w, box[1] + h]
        if [float(v) for v in box] != new:
            chip["box"] = new
            done.append(f"die {w:g} x {h:g} µm")
    return done


SUBSTRATE_KEYS = ("h", "eps_r", "tan_d")  # quantcore_circuits.pdk.SUBSTRATE_KEYS: thickness µm, εr, loss tangent


def substrate_of(sidecar_pdk: dict) -> dict:
    """{"h", "eps_r", "tan_d"} the design uses now (from the sidecar's ``pdk``), PDK defaults when it has none."""
    return {"h": float(sidecar_pdk.get("substrate_height_um", 650.0)),
            "eps_r": float(sidecar_pdk.get("substrate_eps_r", 10.25)),
            "tan_d": float(sidecar_pdk.get("substrate_tan_d", 1e-6))}


def set_substrate(design: dict, base_substrate: dict, h: float, eps_r: float, tan_d: float) -> str | None:
    """The design's own substrate: ``design["pdk"]`` becomes ``"<pdk>+substrate(h=…,eps_r=…,tan_d=…)"`` with the
    values that differ from the PDK's ``base_substrate`` (all equal: the plain PDK name). Returns what changed, or
    None."""
    if h <= 0 or eps_r < 1 or tan_d < 0:
        raise ValueError("the substrate needs a thickness > 0 µm, εr ≥ 1 and a loss tangent ≥ 0")
    base = str(design.get("pdk", "quantcore_nb_sapphire_v1")).split("+substrate(", 1)[0]
    parts = [f"{k}={float(v):g}" for k, v in (("h", h), ("eps_r", eps_r), ("tan_d", tan_d))
             if abs(float(v) - float(base_substrate.get(k, v))) > 1e-15]
    name = f"{base}+substrate({','.join(parts)})" if parts else base
    if design.get("pdk") == name:
        return None
    design["pdk"] = name
    return f"substrate {h:g} µm, εr {eps_r:g}, tan δ {tan_d:g}" + ("" if parts else " (the PDK's)")


KEEP = object()  # set_junction: leave this key as it is


def set_junction(design: dict, inst: str, lj_nh: float | None, cj_ff: float | None, flux_phi0=KEEP, asym=KEEP) -> bool:
    """The lumped junction values (LOM and simulation only, not fab values) of ``inst``, **merged into** its existing
    ``junction`` dict: ``Lj_nH`` (L_J0) and ``Cj_fF`` (None removes the key), and for a SQUID ``flux_phi0`` (Φ/Φ0) and
    ``asym`` (d), which are written only when non-zero (zero removes the key; ``KEEP`` leaves the stored value). Keys
    this function does not know stay as they are. The ``junction`` entry goes when nothing is left in it.
    Returns True when design.json changed."""
    entry = design["instances"][inst]
    old = entry.get("junction")
    if lj_nh is not None and lj_nh <= 0:
        raise ValueError("Lj must be positive")
    if isinstance(old, list):
        raise ValueError(f"{inst} has several junctions (a list): edit them in design.json")
    new = dict(old) if isinstance(old, dict) else {}
    for key, value in (("Lj_nH", lj_nh), ("Cj_fF", cj_ff)):
        if value is None:
            new.pop(key, None)
        else:
            new[key] = float(value)
    for key, value in (("flux_phi0", flux_phi0), ("asym", asym)):
        if value is KEEP:
            continue
        if value is None or abs(float(value)) < 1e-15:
            new.pop(key, None)
        else:
            new[key] = float(value)
    if not new:
        entry.pop("junction", None)
        return old is not None
    entry["junction"] = new
    return new != old


def fix_junction_at_placement(design: dict, inst: str, values: dict | None) -> str | None:
    """A component placed with a junction gets its simulation / LOM values fixed in design.json
    (``junction = {Lj_nH, Cj_fF}``, from ``values``: ``guiflow.placement_junction``). An instance that has a
    ``junction`` already (a duplicate keeps its source's) is left alone. Returns the status-bar note, or None."""
    entry = design["instances"][inst]
    if not values or entry.get("junction") is not None or values.get("Lj_nH") is None:
        return None
    entry["junction"] = {"Lj_nH": float(values["Lj_nH"]), "Cj_fF": float(values.get("Cj_fF") or 0.0)}
    return (f"{inst}: junction L_J {float(values['Lj_nH']):.3g} nH ({values.get('source', 'PDK')}; simulation value, "
            "edit in the component dialog)")


def set_coupling(design: dict, name: str, a: str, b: str, kind: str = "C", value: float | None = None,
                 note: str = "") -> dict:
    """A lumped element between two instances / routes the layout implies (``couplings``). ``kind`` C (fF), L (nH) or
    wire (ports ``inst.port``, no value)."""
    if kind not in ("C", "L", "wire"):
        raise ValueError("type is C, L or wire")
    if a == b:
        raise ValueError("a coupling needs two different ends")
    known = set(design.get("instances", {})) | set(design.get("routes", {}))
    for end in (a, b):
        if end.split(".", 1)[0] not in known:
            raise ValueError(f"{end!r}: no such instance or route")
    if kind == "wire" and (value is not None or "." not in a or "." not in b):
        raise ValueError("a wire coupling joins two ports (inst.port) and takes no value")
    entry = {"between": [a, b], "type": kind}
    if value is not None:
        entry["value"] = float(value)
    if note:
        entry["note"] = note
    design.setdefault("couplings", {})[name] = entry
    return design


def pad_edge_instances(drc: list[dict]) -> list[str]:
    """Instances named by the sidecar's ``pad_edge`` design warnings (a pad that is not at the PDK edge distance)."""
    names = []
    for issue in drc or []:
        if issue.get("rule") != "pad_edge":
            continue
        objs = issue.get("objects") or [str(issue.get("message", "")).split(":", 1)[0]]
        names += [o for o in objs if o and o not in names]
    return names


def apply_pad_edge(design: dict, names: list[str]) -> list[str]:
    """``place.edge = "auto"`` on these instances (absolute placements): the build slides each pad perpendicular to its
    nearest die edge so its outer edge sits the PDK distance (100 µm) from it. Returns the names changed."""
    done = []
    for n in names:
        place = design.get("instances", {}).get(n, {}).get("place")
        if place is None or "snap" in place or place.get("edge") == "auto":
            continue
        place["edge"] = "auto"
        done.append(n)
    return done
