"""Load, save and hash designs."""

from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path
from typing import Any

from quantcore_circuits.design.schema import Design


def load_design(source: str | Path | dict | Design) -> Design:
    """Load a design from a ``.json`` file, a ``.py`` file, a dict or a :class:`Design`.

    A ``.py`` design file must define ``design`` (a dict or :class:`Design`) or a function ``design()`` returning one.
    """
    if isinstance(source, Design):
        return source
    if isinstance(source, dict):
        return Design.model_validate(source)
    path = Path(source)
    if path.suffix == ".py":
        namespace = runpy.run_path(str(path), run_name="__qcc_design__")
        obj = namespace.get("design")
        if obj is None:
            raise ValueError(f"{path} must define `design` (dict, Design or callable)")
        if callable(obj) and not isinstance(obj, Design):
            obj = obj()
        return load_design(obj)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("name", path.stem)
    return Design.model_validate(data)


def save_design(design: Design, path: str | Path) -> Path:
    path = Path(path)
    path.write_text(json.dumps(design.to_json_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def canonical_json(data: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, floats normalised so 1 == 1.0."""

    def norm(x):
        if isinstance(x, dict):
            return {str(k): norm(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [norm(v) for v in x]
        if isinstance(x, float) and x.is_integer():
            return int(x)
        return x

    return json.dumps(norm(data), sort_keys=True, separators=(",", ":"))


def tool_versions(pdk_name: str | None = None) -> dict[str, str]:
    """Versions that change geometry or physics: quantcore-circuits, KQC, KLayout and the PDK."""
    from importlib.metadata import PackageNotFoundError, version  # pylint: disable=import-outside-toplevel

    out = {}
    for pkg in ("quantcore-circuits", "kqcircuits", "klayout"):
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:
            out[pkg] = "unknown"
    if pdk_name is not None:
        from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

        out["pdk"] = f"{pdk_name}@{get_pdk(pdk_name).version}"
    return out


def design_hash(design: Design, extra: dict | None = None, short: bool = True) -> str:
    """sha256 over the canonical design JSON plus tool versions (the results-store key).

    ``targets`` are excluded: changing a target does not change geometry or simulation results.
    """
    data = design.to_json_dict()
    data.pop("targets", None)
    payload = {"design": data, "versions": tool_versions(design.pdk), "extra": extra or {}}
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return digest[:16] if short else digest


def group_hash(design: Design, group: str, short: bool = True) -> str:
    """:func:`design_hash` of what one sim group's jobs see: the design with only that group's spec (the others are
    left out), so adding or changing *another* sim group (a new subset) does not make this group's kept results look
    like another revision. Written to ``job.json`` as ``group_hash`` (additive; older jobs only have
    ``design_hash``)."""
    data = design.to_json_dict()
    data.pop("targets", None)
    data["sim_groups"] = {group: data.get("sim_groups", {}).get(group)}
    payload = {"design": data, "versions": tool_versions(design.pdk), "extra": {}}
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return digest[:16] if short else digest
