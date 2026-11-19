"""Extract the component inventory (KQCircuits, Quantum Metal, Quantcore, legacy QWri) and the design list.

Run from the repo root in the qcd env:  python scripts/extract_inventory.py
Writes docs/components/inventory.json and docs/components/INVENTORY.md — the shared reference for porting
components, writing LOM models and rebuilding designs.
"""

from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "components"

KQC_CATEGORY = {
    "qubits": "qubit",
    "junctions": "junction",
    "test_structures": "test_structure",
    "chips": "chip",
}
KQC_ELEMENT_CATEGORY = [
    (r"capacitor|x_coupler", "capacitor"),
    (r"resonator", "resonator"),
    (r"launcher", "launcher"),
    (r"waveguide|meander", "waveguide"),
    (r"airbridge", "airbridge"),
    (r"chip_frame|marker", "marker"),
    (r"flip_chip|f2f|tsv|bump", "flip_chip"),
]
METAL_CATEGORY = {
    "qubits": "qubit",
    "couplers": "coupler",
    "lumped": "capacitor",
    "resonators": "resonator",
    "terminations": "launcher",
    "tlines": "route",
    "sample_shapes": "shape",
    "user_components": "other",
}


def kqc_components() -> list[dict]:
    from kqcircuits.elements.element import Element

    import kqcircuits

    out = []
    base = Path(kqcircuits.__file__).parent
    for pkg in ("elements", "qubits", "junctions", "test_structures", "chips"):
        for info in pkgutil.walk_packages([str(base / pkg)], prefix=f"kqcircuits.{pkg}."):
            try:
                mod = importlib.import_module(info.name)
            except Exception as e:  # noqa: BLE001
                out.append({"source": "kqc", "module": info.name, "error": f"{type(e).__name__}: {e}"})
                continue
            for name, cls in inspect.getmembers(mod, inspect.isclass):
                if cls.__module__ != mod.__name__ or not issubclass(cls, Element) or inspect.isabstract(cls):
                    continue
                if cls.build is Element.build and pkg != "chips":
                    continue
                cat = KQC_CATEGORY.get(pkg)
                if cat is None:
                    stem = info.name.rsplit(".", 1)[-1] + " " + name.lower()
                    cat = next((c for pat, c in KQC_ELEMENT_CATEGORY if re.search(pat, stem)), "element")
                doc = (inspect.getdoc(cls) or "").split("\n")[0][:140]
                out.append({"source": "kqc", "name": name, "ref": name, "module": info.name, "category": cat,
                            "description": doc})
    return out


def metal_components() -> list[dict]:
    import qiskit_metal.qlibrary as ql
    from qiskit_metal.qlibrary.core import QComponent

    out = []
    for info in pkgutil.walk_packages(ql.__path__, prefix="qiskit_metal.qlibrary."):
        if ".core" in info.name or info.name.endswith("_template"):
            continue
        try:
            mod = importlib.import_module(info.name)
        except Exception as e:  # noqa: BLE001
            out.append({"source": "metal", "module": info.name, "error": f"{type(e).__name__}: {e}"})
            continue
        for name, cls in inspect.getmembers(mod, inspect.isclass):
            if cls.__module__ != mod.__name__ or not issubclass(cls, QComponent) or cls is QComponent:
                continue
            sub = info.name.split(".")[2]
            cat = METAL_CATEGORY.get(sub, "other")
            if sub == "qubits" and re.search(r"JJ|SQUID|SNAIL|BridgeFree", name):
                cat = "junction"
            doc = (inspect.getdoc(cls) or "").split("\n")[0][:140]
            opts = getattr(cls, "default_options", {}) or {}
            out.append({"source": "metal", "name": name, "ref": f"metal:{name}", "module": info.name,
                        "category": cat, "description": doc, "default_options": sorted(opts)[:40]})
    return out


def quantcore_components() -> list[dict]:
    import quantcore_circuits.layouts as L

    out = []
    for cls in L.pcell_classes():
        doc = (inspect.getdoc(cls) or "").split("\n")[0][:140]
        mod = cls.__module__
        folder = mod.split(".")[2] if mod.count(".") >= 3 else "layouts"
        cat = {"qubits": "qubit", "junctions": "junction", "chips": "chip", "wafers": "wafer"}.get(folder, "other")
        if cls.__name__ == "BondPad":
            cat = "launcher"
        out.append({"source": "quantcore", "name": cls.__name__, "ref": cls.__name__, "module": mod, "category": cat,
                    "description": doc, "has_lom": hasattr(cls, "qcc_lom")})
    return out


def legacy_components() -> list[dict]:
    out = []
    legacy = ROOT / "components"
    for path in sorted((legacy / "pymacros").rglob("*.lym")) + sorted((legacy / "pymacros").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        classes = re.findall(r"^\s*class\s+(\w+)\s*\(\s*pya\.PCellDeclarationHelper", text, re.M)
        names = re.findall(r'layout\(\)\.register_pcell\(\s*"([^"]+)"\s*,\s*(\w+)\(', text)
        out.append({"source": "legacy", "file": str(path.relative_to(ROOT)), "pcells": classes,
                    "registered": [{"display": d, "class": c} for d, c in names]})
    for path in sorted((legacy / "python").glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        funcs = re.findall(r"^def\s+(\w+)\s*\(", text, re.M)
        head = " ".join(ln.strip("# ").strip() for ln in text.splitlines()[:6] if ln.strip().startswith("#"))[:160]
        out.append({"source": "legacy_script", "file": str(path.relative_to(ROOT)), "functions": funcs[:30],
                    "header": head, "lines": len(text.splitlines())})
    return out


def designs() -> list[dict]:
    out = []
    for path in sorted((ROOT / "components" / "python").glob("chip_*.py")):
        out.append({"id": path.stem, "group": "legacy", "source": str(path.relative_to(ROOT))})
    for path in sorted((ROOT / "components" / "python").glob("*.ipynb")):
        out.append({"id": path.stem, "group": "legacy_notebook", "source": str(path.relative_to(ROOT))})
    md = (ROOT / "components" / "Open Superconducting Device Layouts.md").read_text(encoding="utf-8")
    for line in md.splitlines():
        if line.startswith("| ") and not line.startswith("| Design") and not line.startswith("| ---"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            name = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cells[0])
            link = re.findall(r"\((https?://[^)]+)\)", line)
            out.append({"id": re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:60], "group": "open",
                        "name": name, "row": cells[1:4], "links": link[:3]})
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    inv = {"quantcore": quantcore_components(), "kqc": kqc_components(), "metal": metal_components(),
           "legacy": legacy_components(), "designs": designs()}
    (OUT / "inventory.json").write_text(json.dumps(inv, indent=1), encoding="utf-8")
    lines = ["# Component inventory", "",
             "Generated by `scripts/extract_inventory.py`. Sources: Quantcore cells, KQCircuits (main), Quantum Metal "
             "`qlibrary`, the legacy QWri macros/scripts in `components/`, and the design list (legacy chips, design "
             "notebooks, `components/Open Superconducting Device Layouts.md`).", ""]
    for src in ("quantcore", "kqc", "metal"):
        rows = [r for r in inv[src] if "name" in r]
        lines += [f"## {src} ({len(rows)})", "", "| category | name | ref | description |", "|---|---|---|---|"]
        for r in sorted(rows, key=lambda r: (r["category"], r["name"])):
            lines.append(f"| {r['category']} | {r['name']} | `{r['ref']}` | {r['description'].replace('|', '/')} |")
        errs = [r for r in inv[src] if "error" in r]
        for r in errs:
            lines.append(f"| (import error) | {r['module']} | | {r['error'][:100]} |")
        lines.append("")
    lines += ["## legacy QWri", "", "| file | PCell classes / functions |", "|---|---|"]
    for r in inv["legacy"]:
        what = ", ".join(r.get("pcells") or r.get("functions") or [])
        lines.append(f"| `{r['file']}` | {what[:200]} |")
    lines += ["", "## designs", "", "| id | group | name / source |", "|---|---|---|"]
    for d in inv["designs"]:
        lines.append(f"| {d['id']} | {d['group']} | {d.get('name') or d.get('source')} |")
    (OUT / "INVENTORY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    counts = {k: len([r for r in v if "name" in r or k in ("legacy", "designs")]) for k, v in inv.items()}
    print("wrote", OUT, counts)


if __name__ == "__main__":
    main()
