"""Helpers for legacy-a's notebooks in ``examples/designs/legacy/`` (chips 01–06 of the legacy QWri library).

Owned by legacy-a (legacy-b owns ``_legacy_b.py``). Three jobs:

* **Frame.** Legacy QWri chips are centred on (0, 0); the Designer frame has its origin at the lower-left corner of
  the 7.5 × 7.5 mm PDK die, so :func:`at` shifts by (+W/2, +H/2). Legacy ``Trans(rot, mirror, x, y)`` codes are
  ``rot`` × 90° with the mirror (y → −y) applied before the rotation, which is also KLayout's ``DCplxTrans`` and the
  Designer's ``rot=`` / ``mirror=`` convention, so :func:`place` only multiplies ``rot`` by 90.
* **Parameters.** The legacy PCell parameters (with the legacy defaults) → the Quantcore port's parameters:
  :func:`xmon`, :func:`coupled_resonator`, :func:`connector_pad`, :func:`cpw_segment`.
* **Legacy reference.** :class:`LegacyChip` draws the same chip with the legacy PCells and scripts,
  executed read-only through ``tests/legacy_ref`` (nothing from ``components/`` is imported), shifted into the
  Designer frame. :meth:`LegacyChip.write` saves it as GDS for a snapshot; :func:`xor_table` compares it, instance
  by instance, with the rebuilt chip's etch layer.
"""

from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

W = H = 7500.0  # PDK die (µm); every legacy-a chip is a 7.5 mm die centred on (0, 0)
ROOT = next(p for p in [Path(__file__).resolve(), *Path(__file__).resolve().parents] if (p / "pyproject.toml").exists())
PCELLS = "pymacros/QuantumPcells"


def at(x: float, y: float) -> tuple[float, float]:
    """Legacy (0, 0)-centred coordinates → Designer frame (lower-left die corner at the origin)."""
    return (x + W / 2, y + H / 2)


def place(x: float, y: float, rot: int = 0, mirror: bool = False) -> dict:
    """``d.add`` placement keywords for a legacy ``pya.Trans(rot, mirror, x, y)`` (x, y in µm)."""
    return {"at": at(x, y), "rot": 90.0 * rot, "mirror": bool(mirror)}


# ---- legacy PCell parameters → Quantcore parameters ---------------------------------------------------------------
XMON_CROSS_DEFAULTS = {
    "thickness": 25, "width": 300, "da": 2, "spacing": 25, "handle": 1, "cap_spacing": 2, "pthickness": 25,
    "fwidth": 25, "hlength": 100, "tail": True, "ground": False, "ggap": 6, "tail_l": 50,
}  # fmt: skip
HANDLE_CLAWS = {0: [], 1: ["n"], 2: ["w", "n"], 3: ["n", "w", "e"], 4: ["w", "e"]}


def xmon(**legacy) -> dict:
    """``Xmon`` parameters for a legacy ``Xmon Cross`` (``fab`` is implied; same mapping as the golden test)."""
    p = XMON_CROSS_DEFAULTS | {k: v for k, v in legacy.items() if k != "fab"}
    return {
        "claws": HANDLE_CLAWS[int(p["handle"])],
        "arm_width": p["thickness"],
        "cross_length": p["width"],
        "ground_sliver": p["da"],
        "gap": p["spacing"],
        "claw_spacing": p["cap_spacing"],
        "claw_base": p["pthickness"],
        "claw_finger_width": p["fwidth"],
        "claw_length": p["hlength"],
        "claw_tail": p["tail"],
        "claw_ground": p["ground"],
        "claw_ground_gap": p["ggap"],
        "claw_tail_length": p["tail_l"],
        "claw_tail_gap": p["cap_spacing"],  # legacy: the claw tail is cleared by cap_spacing too (components-pdk #22)
    }


COUPLED_RESONATOR_DEFAULTS = {
    "cpw_len": 4000, "width": 500, "arc_length": 300, "path_width": 10, "gap": 6, "neck_length": 400,
    "ground": True, "flip": True, "cgap": 6, "clength": 500, "tail": True, "tail_len": 0, "tail_end": False, "n": 256,
}  # fmt: skip


def coupled_resonator(**legacy) -> dict:
    """``CoupledResonator`` parameters for a legacy ``Coupled Resonator``."""
    p = COUPLED_RESONATOR_DEFAULTS | {k: v for k, v in legacy.items() if k != "fab"}
    return {
        "cpw_len": p["cpw_len"],
        "width": p["width"],
        "arc_length": p["arc_length"],
        "neck_length": p["neck_length"],
        "cgap": p["cgap"],
        "clength": p["clength"],
        "ground": p["ground"],
        "flip": p["flip"],
        "tail": p["tail"],
        "tail_len": p["tail_len"],
        "tail_end": p["tail_end"],
        "arc_points": p["n"],
        "a": p["path_width"],
        "b": p["gap"],
    }


CONNECTOR_PAD_DEFAULTS = {
    "pad_width": 275, "pad_height": 300, "conn_height": 300, "trace_width": 10, "trace_gap": 6, "round": True,
    "sim": True,
}  # fmt: skip


def connector_pad(**legacy) -> dict:
    """``ConnectorPad`` parameters for a legacy ``Connector Pad`` (always the fab geometry, see the specs)."""
    p = CONNECTOR_PAD_DEFAULTS | {k: v for k, v in legacy.items() if k != "fab"}
    return {
        "pad_width": p["pad_width"],
        "pad_height": p["pad_height"],
        "taper_length": p["conn_height"],
        "rounded": p["round"],
        "a": p["trace_width"],
        "b": p["trace_gap"],
    }


def cpw_segment(**legacy) -> dict:
    """``CpwSegment`` parameters for a legacy ``Coplanar Waveguide`` (fab, ground)."""
    p = {"length": 200, "cwidth": 10, "gap": 6, "lc_thickness": 10, "rc_thickness": 10} | {
        k: v for k, v in legacy.items() if k != "fab"
    }
    return {
        "length": p["length"],
        "a": p["cwidth"],
        "b": p["gap"],
        "lc_thickness": p["lc_thickness"],
        "rc_thickness": p["rc_thickness"],
    }


# ---- resonator tail ↔ Xmon claw, as drawn ----------------------------------------------------------------------------
def overshoot(d, claw: str, end: str) -> float:
    """How far (µm) the resonator end ``end`` lies past the claw tail tip ``claw``, along the claw axis (> 0: the
    open tail runs into the claw; < 0: it stops short and the claw tail ends open into the ground plane)."""
    import math  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.assembly import plan_design  # pylint: disable=import-outside-toplevel

    plan = plan_design(d.design)
    pc, pe = plan.port(claw), plan.port(end)
    ux, uy = math.cos(math.radians(pc.angle)), math.sin(math.radians(pc.angle))  # claw port: outward, to the tail
    return -((pe.pos.x - pc.pos.x) * ux + (pe.pos.y - pc.pos.y) * uy)


def origin(d, name: str) -> tuple[float, float]:
    """Placed origin (µm, Designer frame) of instance ``name`` — also for snapped instances."""
    from quantcore_circuits.assembly import plan_design  # pylint: disable=import-outside-toplevel

    t = plan_design(d.design).instances[name].trans.disp
    return (t.x, t.y)


def claw_join_md(d, pairs) -> str:
    """Markdown table of the corrected resonator ↔ claw joins (decision #8): ``pairs = [(qubit, resonator,
    legacy (x, y) of the Xmon centre in the legacy frame)]``. The Xmon is snapped with its claw-tail tip onto the
    resonator's uncapped end, so the claw is the λ/4's open end (galvanic, the legacy PCell's "xmon connector" mode)."""
    rows = ["| pair | legacy Xmon centre (legacy frame) | corrected Xmon centre | moved by (µm) "
            "| gap claw tip ↔ tail end |",
            "|---|---|---|---|---|"]
    for q, r, (lx, ly) in pairs:
        x, y = origin(d, q)
        x, y = x - W / 2, y - H / 2
        gap = -overshoot(d, f"{q}.claw_n", f"{r}.end")
        rows.append(f"| {q}/{r} | ({lx:g}, {ly:g}) | ({x:.1f}, {y:.1f}) | Δx {x - lx:+.1f}, Δy {y - ly:+.1f} | "
                    f"{gap:.3f} µm |")
    return "\n".join(rows)


def tail_c_fF(overshoot_um: float, tail_um: float, a: float, b: float, pdk_name: str) -> float:
    """Rough claw ↔ resonator-end capacitance (fF) for an open tail ``overshoot_um`` past the claw tip: the end face
    (``a`` wide) across its ``b`` gap cap (CPS) plus the strip running inside the claw metal beyond the claw's own
    ``tail_um`` stub (CPW C′ per µm, the claw metal acting as its ground). Placeholder for the FEM C-matrix."""
    from quantcore_circuits.lom import estimates as est  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    eps = est.substrate_eps(get_pdk(pdk_name))
    inside = max(0.0, overshoot_um - tail_um)
    return round(est.coplanar_coupling(a, a, a, b, eps) + inside * est.cpw_c_per_um(a, b, eps), 2)


# ---- junction values: the PDK trilayer rule (2026-11-03) -----------------------------------------------------
# Nb/AlOx/Nb trilayer junctions, Δ_Nb = 1.4 meV → Ambegaokar–Baratoff I_c·R_n = πΔ/2e ≈ 2.20 mV; the PDK wants the
# qubits at 4–8 GHz and expects R_n ≈ 40–50 kΩ (L_J ≈ 6.0–7.5 nH). The PDK holds the process: ``get_pdk().junction``
# (components-pdk: R_n·A 13.5 kΩ·µm² = 45 kΩ × the nominal 0.5 × 0.6 µm junction, C_J 50 fF/µm², both assumed) and
# ``circuit.bridges``. Two uses here:
# * drawn legacy fingers (chips 05, 10a, the test-pad chips, the 3X SQUID, chip_03's js fingers): valued on the PDK
#   process (:func:`jj`, :func:`junction_table`, :func:`junction_grid`);
# * qubits whose legacy junction cell is only a stand-in (``junction_creator.py`` is missing: chips 01_creator / 02;
#   chip_01's pre-HSQ SQUID V0 has no spacer; the Metal footprints of d12 / d14): drawn as the PDK cells
#   ``Quantcore Junction`` / ``Quantcore Squid`` sized by the rule. :func:`nominal` declares the legacy nominal
#   junction, which gets R_n = 45 kΩ (a SQUID: the parallel total at zero flux); other legacy sizes scale
#   R_n ∝ 1/area, so the legacy sweeps are kept (:func:`sized`, :func:`pdk_cell`, :func:`sized_table`).
RN_NOMINAL_OHM = 45e3
RN_RANGE_OHM = (40e3, 50e3)
_SIZING: dict = {}  # empty: no nominal declared (sized == PDK process)


def process():
    """The PDK junction process (``pdk.get_pdk().junction``)."""
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    return get_pdk().junction


def rn_area_ohm_um2() -> float:
    """R_n·A (Ω·µm²) of the PDK process."""
    return process().rn_area_ohm_um2


def cj_ff_per_um2() -> float:
    return process().cj_fF_per_um2


def nominal(width_um: float, second_um: float | None = None, n: int = 1, rn_ohm: float = RN_NOMINAL_OHM,
            label: str | None = None) -> float:
    """Declare the chip's legacy nominal qubit junction (``n`` in parallel) for :func:`sized`: it gets ``rn_ohm``
    (parallel total), other legacy sizes R_n ∝ 1/area. Returns the sizing R_n·A of one junction (Ω·µm²)."""
    area = width_um * (second_um or width_um)
    _SIZING.update(area_um2=area, n=n, rn_ohm=rn_ohm,
                   label=label or f"{width_um:g} × {second_um or width_um:g} µm" + (f" × {n}" if n > 1 else ""))
    return rn_ohm * n * area


def sized_rn_ohm(width_um: float, second_um: float | None = None, n: int = 1) -> float:
    """Qubit R_n (parallel total) of a legacy junction ``n × width × second`` by the sizing rule."""
    area = width_um * (second_um or width_um)
    if not _SIZING:
        return rn_area_ohm_um2() / area / n
    return _SIZING["rn_ohm"] * _SIZING["n"] * _SIZING["area_um2"] / area / n


def _values(rn_total_ohm: float, n: int) -> dict:
    from quantcore_circuits.circuit.bridges import ic_from_rn, lj_from_ic  # pylint: disable=import-outside-toplevel

    lj = lj_from_ic(ic_from_rn(rn_total_ohm, process().gap_meV))
    area_total = rn_area_ohm_um2() / rn_total_ohm  # PDK-drawn area of the n junctions together
    return {"Lj_nH": round(lj, 4), "Cj_fF": round(cj_ff_per_um2() * area_total, 3)}


def jj(width_um: float, second_um: float | None = None, n: int = 1) -> dict:
    """``Designer.add(junction=...)`` values of ``n`` parallel drawn cross junctions ``width × second`` µm² on the
    PDK process (SQUID: the parallel total at zero flux)."""
    area = width_um * (second_um or width_um)
    return _values(rn_area_ohm_um2() / area / n, n)


def sized(width_um: float, second_um: float | None = None, n: int = 1) -> dict:
    """``junction=`` values of the PDK cell that replaces a legacy junction ``n × width × second`` (sizing rule)."""
    return _values(sized_rn_ohm(width_um, second_um, n), n)


def pdk_cell(width_um: float, second_um: float | None = None, n: int = 1) -> dict:
    """Xmon / ``metal:`` keywords drawing the PDK cell sized like :func:`sized` (``Quantcore Junction`` or, n = 2,
    ``Quantcore Squid``; ``lj_nH`` = the parallel total)."""
    return {"junction_type": "Quantcore Squid" if n == 2 else "Quantcore Junction",
            "junction_params": {"lj_nH": sized(width_um, second_um, n)["Lj_nH"]}}


def lj_for_rn(rn_ohm: float = RN_NOMINAL_OHM, n: int = 1) -> dict:
    """``junction=`` values of a PDK-drawn junction of normal resistance ``rn_ohm`` (parallel total)."""
    return _values(rn_ohm, n)


def jc_ua_per_um2() -> float:
    """Critical-current density of the PDK process (µA/µm²)."""
    from quantcore_circuits.circuit.bridges import ic_from_rn  # pylint: disable=import-outside-toplevel

    return ic_from_rn(rn_area_ohm_um2(), process().gap_meV) * 1e6


def rule_md() -> str:
    """One Markdown line stating the PDK junction rule (and this chip's sizing, if declared)."""
    from quantcore_circuits.circuit.bridges import ic_from_rn, lj_from_ic  # pylint: disable=C0415

    proc = process()
    out = (f"PDK junction rule (design rule): Nb trilayer, Δ = {proc.gap_meV:g} meV → I_c·R_n = πΔ/2e = "
           f"{ic_from_rn(1.0, proc.gap_meV) * 1e3:.3f} mV; PDK process R_n·A = {rn_area_ohm_um2():.0f} Ω·µm² "
           f"(J_c = {jc_ua_per_um2():.3f} µA/µm²; nominal 0.5 × 0.6 µm → 45 kΩ, L_J "
           f"{lj_from_ic(ic_from_rn(45e3, proc.gap_meV)):.2f} nH), C_J = {cj_ff_per_um2():g} fF/µm² (R_n·A and C_J "
           "assumed by the PDK).")
    if _SIZING:
        out += (f" Qubit junctions: PDK cells sized by the rule, legacy nominal {_SIZING['label']} → "
                f"R_n = {_SIZING['rn_ohm'] / 1e3:.0f} kΩ, other legacy sizes R_n ∝ 1/area.")
    return out


def junction_table(rows) -> str:
    """Markdown table of drawn legacy junctions on the PDK process: ``rows = [(label, width µm, second µm, n)]``."""
    from quantcore_circuits.circuit.bridges import ic_from_rn  # pylint: disable=import-outside-toplevel

    out = [rule_md(), "", "Drawn junctions (legacy fingers) on the PDK process:", "",
           "| junction | fingers (µm) | n | area (µm²) | R_n (kΩ) | I_c (nA) | L_J (nH) | C_J (fF) |",
           "|---|---|---|---|---|---|---|---|"]
    for label, w, s, n in rows:
        a = w * (s or w)
        rn = rn_area_ohm_um2() / a / n
        v = _values(rn, n)
        out.append(f"| {label} | {w:g} × {s or w:g} | {n} | {a * n:.4f} | {rn / 1e3:.2f} | "
                   f"{ic_from_rn(rn, process().gap_meV) * 1e9:.1f} | {v['Lj_nH']:.3f} | {v['Cj_fF']:.2f} |")
    return "\n".join(out)


def sized_table(rows) -> str:
    """Markdown table of PDK cells sized by the rule: ``rows = [(label, legacy width, legacy second, n)]``."""
    from quantcore_circuits.circuit.bridges import fingers_for_lj, ic_from_rn  # pylint: disable=C0415

    out = [rule_md(), "", "Qubit junctions (PDK cells, sized by the rule from the legacy nominal):", "",
           "| junction | legacy fingers (µm) | n | R_n (kΩ) | I_c (nA) | L_J (nH) | drawn PDK fingers (µm) "
           "| C_J (fF) |",
           "|---|---|---|---|---|---|---|---|"]
    for label, w, s, n in rows:
        rn = sized_rn_ohm(w, s, n)
        v = _values(rn, n)
        fw, bw, _ = fingers_for_lj(v["Lj_nH"], n, process())
        out.append(f"| {label} | {w:g} × {s or w:g} | {n} | {rn / 1e3:.2f} | "
                   f"{ic_from_rn(rn, process().gap_meV) * 1e9:.1f} | {v['Lj_nH']:.3f} | {fw:g} × {bw:g} | "
                   f"{v['Cj_fF']:.2f} |")
    return "\n".join(out)


def sweep_fq_md(rows, ec_GHz: float, note: str = "", rule: str = "sized") -> str:
    """Markdown f_q estimate over a junction-size sweep: ``rows = [(label, width µm, second µm, n)]``, R_n by the
    sizing rule (``rule="sized"``) or the PDK process on the drawn fingers (``"drawn"``); transmon
    f_01 ≈ √(8 E_J E_C) − E_C with E_J/h = 163.47 GHz / L_J[nH] and the qubit's E_C (≈ −α from the LOM run)."""
    import math  # pylint: disable=import-outside-toplevel

    out = [f"f_q over the junction sweep (E_C = {ec_GHz * 1e3:.0f} MHz from the LOM run; transmon estimate "
           f"√(8 E_J E_C) − E_C). {note}".strip(), "",
           "| junction | legacy area (µm²) | R_n (kΩ) | L_J (nH) | E_J (GHz) | f_q (GHz) |",
           "|---|---|---|---|---|---|"]
    for label, w, s, n in rows:
        a = w * (s or w)
        rn = sized_rn_ohm(w, s, n) if rule == "sized" else rn_area_ohm_um2() / a / n
        lj = _values(rn, n)["Lj_nH"]
        ej = 163.47 / lj
        out.append(f"| {label} | {a * n:.4f} | {rn / 1e3:.1f} | {lj:.2f} | {ej:.1f} | "
                   f"{math.sqrt(8 * ej * ec_GHz) - ec_GHz:.2f} |")
    return "\n".join(out)


def junction_grid(cols, rows, fingers, col_label="bottom finger (µm)", row_label="top finger (µm)") -> str:
    """Markdown L_J (nH) / R_n (kΩ) grid of a junction test array: ``fingers(col, row) → (w1, w2)`` in µm."""
    from quantcore_circuits.circuit.bridges import lj_from_area, rn_from_area  # pylint: disable=C0415

    rna = rn_area_ohm_um2()
    out = [
        f"L_J (nH) / R_n (kΩ) per test pad, drawn fingers on the PDK process. {rule_md()} Area = straight × "
        "bent finger.",
        "",
        f"| {row_label} \\ {col_label} | " + " | ".join(f"{c:g}" for c in cols) + " |",
        "|---|" + "---|" * len(cols),
    ]
    for r in rows:
        cells = []
        for c in cols:
            w1, w2 = fingers(c, r)
            a = w1 * w2
            cells.append(f"{lj_from_area(a, rna):.2f} / {rn_from_area(a, rna) / 1e3:.1f}")
        out.append(f"| {r:g} | " + " | ".join(cells) + " |")
    return "\n".join(out)


# ---- the legacy reference (the legacy code, read-only, via tests/legacy_ref) ----------------------------------
# legacy library display name → (macro relative to components/, class); None = the harness's base QWri library
LEGACY_PCELLS = {
    "Xmon Cross": None,
    "Marker": (f"{PCELLS}/Marker.lym", "Marker"),
    "Coplanar Waveguide": (f"{PCELLS}/CPW.lym", "CPW"),
    "Connector Pad": (f"{PCELLS}/connector_pad.lym", "ConnectorPad"),
    "Coupled Resonator": (f"{PCELLS}/CPW_Coupled_Resonator.lym", "CoupledResonator"),
}
LAYERS = ((1, 0), (2, 0), (4, 0))  # legacy etch, straight junction finger, bent junction finger


def _harness():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tests.legacy_ref import legacy, scripts  # pylint: disable=import-outside-toplevel

    return legacy, scripts


def legacy_available() -> bool:
    try:
        legacy, _ = _harness()
    except ImportError:
        return False
    return legacy.available()


class LegacyChip:
    """A legacy chip drawn by the legacy PCells / scripts, in the Designer frame (dbu 0.001, layers 1/2/4).

    ``pcell(name, display, params, x, y, rot, mirror)`` places a legacy PCell at its legacy transform;
    ``cell_from(name, layout, cell_name, x, y, rot, mirror)`` places a cell of a GDS written by a legacy script;
    ``cut(boxes)`` replays the legacy "CLEARER" step (boxes removed from 1/0 and 3/0).
    """

    def __init__(self, name: str):
        import klayout.db as pya  # pylint: disable=import-outside-toplevel

        self.pya = pya
        self.layout = pya.Layout()
        self.layout.dbu = 0.001
        self.top = self.layout.create_cell(f"LEGACY_{name}")
        self.boxes: dict[str, pya.DBox] = {}  # instance → bbox (Designer frame, µm)

    def _trans(self, x, y, rot, mirror):
        pya = self.pya
        return pya.DCplxTrans(1, 90.0 * rot, bool(mirror), *at(x, y))

    def _insert(self, name, regions: dict, trans):
        pya = self.pya
        itrans = trans.to_itrans(self.layout.dbu)
        box = pya.DBox()
        for layer, region in regions.items():
            r = region.transformed(itrans)
            self.top.shapes(self.layout.layer(*layer)).insert(r)
            if not r.is_empty():
                box += r.bbox().to_dtype(self.layout.dbu)
        self.boxes[name] = box

    def pcell(self, name, display, params, x=0.0, y=0.0, rot=0, mirror=False):
        legacy, _ = _harness()
        spec = LEGACY_PCELLS[display]
        with contextlib.redirect_stdout(io.StringIO()):  # the legacy macros print their internals
            if spec is None:
                regions = {li: legacy.legacy_region(display, li, **params) for li in LAYERS[:1]}
            else:
                regions = legacy.legacy_pcell_regions(spec[0], spec[1], display, layers=LAYERS[:1], **params)
        self._insert(name, regions, self._trans(x, y, rot, mirror))

    def cell_from(self, name, layout, cell_name, x=0.0, y=0.0, rot=0, mirror=False):
        pya = self.pya
        cell = layout.cell(cell_name)
        assert cell is not None, f"no cell {cell_name!r} in {[c.name for c in layout.top_cells()]}"
        scale = layout.dbu / self.layout.dbu
        regions = {}
        for li in LAYERS:
            idx = layout.find_layer(pya.LayerInfo(*li))
            if idx is not None:
                regions[li] = pya.Region(cell.begin_shapes_rec(idx)).merged().transformed(pya.ICplxTrans(scale))
        self._insert(name, regions, self._trans(x, y, rot, mirror))

    def etch(self, name, boxes_um):
        """Legacy boxes drawn straight onto 1/0 (flux holes, ground cuts): ``(x0, y0, x1, y1)``, legacy frame."""
        pya = self.pya
        region = pya.Region()
        for x0, y0, x1, y1 in boxes_um:
            (a, b), (c, d) = at(x0, y0), at(x1, y1)
            region.insert(pya.DBox(a, b, c, d).to_itype(self.layout.dbu))
        self.top.shapes(self.layout.layer(1, 0)).insert(region)
        self.boxes[name] = region.bbox().to_dtype(self.layout.dbu)

    def etch_region(self, name, region):
        """A legacy-frame ``pya.Region`` (dbu 0.001) drawn onto 1/0 — shapes a chip script draws itself."""
        pya = self.pya
        (dx, dy) = at(0, 0)
        r = region.transformed(pya.Trans(round(dx / self.layout.dbu), round(dy / self.layout.dbu)))
        self.top.shapes(self.layout.layer(1, 0)).insert(r)
        self.boxes[name] = r.bbox().to_dtype(self.layout.dbu)

    def cut(self, boxes_um):
        """Legacy CLEARER: remove legacy-frame boxes ``(x0, y0, x1, y1)`` from the etch layer."""
        pya = self.pya
        idx = self.layout.layer(1, 0)
        region = pya.Region(self.top.shapes(idx))
        for x0, y0, x1, y1 in boxes_um:
            (a, b), (c, d) = at(x0, y0), at(x1, y1)
            region -= pya.Region(pya.DBox(a, b, c, d).to_itype(self.layout.dbu))
        self.top.shapes(idx).clear()
        self.top.shapes(idx).insert(region)

    def region(self, layer=(1, 0)):
        pya = self.pya
        return pya.Region(self.top.begin_shapes_rec(self.layout.layer(*layer))).merged()

    def write(self, path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.layout.write(str(path))
        return path


def legacy_script_cell(script: str, func: str, cell: str, *args, tmp=None):
    """Run a legacy junction / test-pad script (read-only, ``tests/legacy_ref/scripts.py``) into ``tmp`` and return
    ``(layout, cell name)``. ``func`` writing to a module-level ``path`` (``testPad*.py``, ``junction_creator_sq``)
    or taking ``path=`` (``junction_creator_HSQ``, ``squid_creator_HSQ``) are both handled."""
    import tempfile  # pylint: disable=import-outside-toplevel

    _, scripts = _harness()
    tmp = Path(tmp or tempfile.mkdtemp(prefix="qcc_legacy_"))
    tmp.mkdir(parents=True, exist_ok=True)
    with contextlib.redirect_stdout(io.StringIO()):
        if script in ("junction_creator_HSQ.py", "squid_creator_HSQ.py"):
            layout = scripts.creator_layout(script, func, tmp, *args)
        else:
            layout = scripts.module_path_layout(script, func, tmp, *args)
    return layout, cell


def xmon_feedline_reference(name, *, feed, pads, resonators, xmons, junctions=(), testpads=(), cutters=(), etches=(),
                            regions=()):
    """Legacy reference of the chip-01 family (one feedline, Coupled Resonators, Xmon Crosses), from tables in the
    legacy frame. ``feed`` = Coplanar Waveguide params; ``pads`` = [(params, x, y, rot)]; ``resonators`` /
    ``xmons`` = [(name, params, x, y, rot, mirror)]; ``junctions`` / ``testpads`` = [(name, (layout, cell), x, y,
    rot, mirror)]; ``cutters`` = CLEARER boxes (x0, y0, x1, y1)."""
    ref = LegacyChip(name)
    ref.pcell("FL", "Coplanar Waveguide", {"fab": True, **feed})
    for i, (params, x, y, rot) in enumerate(pads):
        ref.pcell(f"P{i + 1}", "Connector Pad", {"fab": True, **params}, x, y, rot)
    for n, params, x, y, rot, mirror in resonators:
        ref.pcell(n, "Coupled Resonator", {"fab": True, **params}, x, y, rot, mirror)
    for n, params, x, y, rot, mirror in xmons:
        ref.pcell(n, "Xmon Cross", {"fab": True, **params}, x, y, rot, mirror)
    for n, (layout, cell), x, y, rot, mirror in [*junctions, *testpads]:
        ref.cell_from(n, layout, cell, x, y, rot, mirror)
    for n, boxes in etches:
        ref.etch(n, boxes)
    for n, region in regions:
        ref.etch_region(n, region)
    if cutters:
        ref.cut(cutters)
    return ref


def rebuilt_region(d, layer: str = "1t1_base_metal_gap_wo_grid"):
    """The rebuilt chip's etch (KQC ``1t1_base_metal_gap_wo_grid``) as a merged Region in dbu 0.001."""
    import klayout.db as pya  # pylint: disable=import-outside-toplevel
    from kqcircuits.defaults import default_layers  # pylint: disable=import-outside-toplevel

    if d.result is None:
        d.show()
    ly, cell = d.result.layout, d.result.cell
    region = pya.Region(cell.begin_shapes_rec(ly.layer(default_layers[layer])))
    # the fab etch (layouts/wafers/fab_export.py, M1): gap − base_metal_addition
    region = (region - pya.Region(cell.begin_shapes_rec(ly.layer(default_layers["1t1_base_metal_addition"])))).merged()
    if abs(ly.dbu - 0.001) > 1e-12:
        region = region.transformed(pya.ICplxTrans(ly.dbu / 0.001))
    return region


def xor_table(d, ref: LegacyChip, names=None, tol_um: float = 0.002) -> tuple[str, dict]:
    """Per legacy instance: etch area of the legacy reference and of the rebuild inside the instance's bbox, and the
    XOR area (slivers up to ``tol_um`` ignored). Returns ``(markdown, {name: xor µm²})``."""
    pya = ref.pya
    new = rebuilt_region(d)
    old = ref.region()
    s = max(1, round(tol_um / 0.001))
    rows = ["| instance | legacy etch (µm²) | rebuilt etch (µm²) | XOR (µm²) | XOR / legacy |", "|---|---|---|---|---|"]
    out = {}
    for name in names or ref.boxes:
        box = pya.Region(ref.boxes[name].to_itype(0.001))
        a, b = old & box, new & box
        x = (a ^ b).sized(-s).sized(s)
        ua, ub, ux = a.area() * 1e-6, b.area() * 1e-6, x.area() * 1e-6
        out[name] = ux
        rows.append(f"| {name} | {ua:.0f} | {ub:.0f} | {ux:.1f} | {ux / ua if ua else 0:.2%} |")
    return "\n".join(rows), out


def xor_png(d, ref: LegacyChip, png, box=None, size=(1600, 1600)) -> Path:
    """GDS + PNG of legacy (1/0), rebuild (130/1 → 2/0 here) and their XOR (3/0) for a visual diff."""
    import klayout.db as pya  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.live.snapshot import snapshot  # pylint: disable=import-outside-toplevel

    ly = pya.Layout()
    ly.dbu = 0.001
    top = ly.create_cell("XOR")
    old, new = ref.region(), rebuilt_region(d)
    top.shapes(ly.layer(pya.LayerInfo(1, 0, "legacy"))).insert(old)
    top.shapes(ly.layer(pya.LayerInfo(2, 0, "rebuilt"))).insert(new)
    top.shapes(ly.layer(pya.LayerInfo(3, 0, "xor"))).insert((old ^ new).sized(-2).sized(2))
    gds = Path(png).with_suffix(".oas")  # OASIS: legacy arcs exceed the GDS polygon size limit
    gds.parent.mkdir(parents=True, exist_ok=True)
    ly.write(str(gds))
    return snapshot(gds, png, size=size, box=box)


# ---- the educative notebooks (notebooks-legacy, 2026-11-03) ----------------------------------------------------------
# The step-by-step walk-through of the design notebooks: the PDK facts a chip uses, a snapshot after each
# step (into ``build/legacy_steps/``, not the examples folder), the pads' distance from the die edge, the FEM "send
# the job" and "bring it back" steps, a before/after table for the iterate step, the fab export, and the legacy
# reference moved by the PDK placement (centring) so the XOR still compares like with like.
STEPS = ROOT / "build" / "legacy_steps"


def pdk_facts_md(cheese: str = "") -> str:
    """Markdown table of the Quantcore PDK facts a legacy rebuild uses (``get_pdk()``), with this chip's cheese
    decision (``cheese``, one sentence) in the cheese row."""
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    pdk = get_pdk()
    s, f, j, ch, ko = pdk.stack, pdk.frame, pdk.junction, pdk.cheese, pdk.keepout
    rows = [
        ("PDK", f"`{pdk.name}` (version {pdk.version})"),
        ("stack", f"{s.substrate_material}, {s.substrate_height:g} µm, ε_r {s.substrate_permittivity:g}; Nb film "
                  f"(sheet metal in the FEM exports, {s.metal_thickness_um:g} µm for the analytic CPW formulas)"),
        ("CPW default", f"{pdk.cpw_a:g} µm centre, {pdk.cpw_b:g} µm gap, bends r = {pdk.turn_radius:g} µm"),
        ("die frame", f"L-shaped dicing markers {f.dicing_width:g} µm wide ({f.dicing_leg:g} µm legs, 1000/0), "
                      f"3 × 3 alignment grids (1001/0) in {f.marker_area:g} µm corner squares, design area "
                      f"{f.margin:g} µm inside the die edge, device ID optional (bottom centre, or beside the pads)"),
        ("pad rule", f"bond pads / launchers: outer etch edge **{f.pad_edge:g} µm** (the design-area margin) from "
                     "the die edge, whatever the original did (`edge=\"auto\"`, DRC design warning `pad_edge`)"),
        ("junction rule", f"{j.material}, Δ = {j.gap_meV:g} meV (I_c·R_n = πΔ/2e), R_n "
                          f"{j.rn_target_kohm[0]:g}–{j.rn_target_kohm[1]:g} kΩ (nominal {j.rn_nominal_kohm:g}), qubits "
                          f"{j.f_q_range_GHz[0]:g}–{j.f_q_range_GHz[1]:g} GHz; R_n·A {j.rn_area_ohm_um2:g} Ω·µm² and "
                          f"C_J {j.cj_fF_per_um2:g} fF/µm² assumed; cells `Quantcore Junction` / `Quantcore Squid` "
                          "(DRC design warnings `pdk_rn`, `pdk_fq`: flagged, never retuned)"),
        ("3/0 keep-out", f"second-metal etch: routes + {ko.route_margin:g} µm, components' etch bbox + "
                         f"{ko.component_margin:g} µm, other 1/0 shapes + {ko.other_margin:g} µm (filled)"),
        ("cheese rule", f"{ch.size:g} µm squares, {ch.gap:g} µm gaps, at least {ch.clearance:g} µm from the 3/0 "
                        f"keep-outs: a band of {ch.rows} rows around them, or the whole die (chip `cheese`: "
                        "`\"auto\"` / `\"pdk\"` / `\"chip\"` / `\"original\"`); holes drawn in the original "
                        "layout stay" + (f". This chip: {cheese}" if cheese else "")),
    ]
    return "\n".join(["| PDK item | value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows])


def step_snapshot(d, step: str, box=None, size=(900, 900), width: int = 420) -> Path:
    """Headless snapshot of the design so far (rebuilt) to ``build/legacy_steps/<design>_<step>.png``, shown
    inline. The step snapshots are teaching aids; the chip's reference PNGs stay next to the notebook."""
    from IPython.display import Image, display  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.live.snapshot import snapshot  # pylint: disable=import-outside-toplevel

    d.show()  # rebuild: the cumulative design after this step
    x0, y0, x1, y1 = d.design.chip.box
    STEPS.mkdir(parents=True, exist_ok=True)
    png = snapshot(d.out, STEPS / f"{d.design.name}_{step}.png", size=size, box=box or (x0, y0, x1, y1))
    display(Image(filename=str(png), width=width))
    return png


def edge_gaps(d, names=None) -> dict:
    """Distance (µm) of each instance's etch from the nearest die edge (the PDK pad rule wants
    ``frame.pad_edge``, 100 µm, for bond pads / launchers). ``names`` default to the design's bond pads."""
    from quantcore_circuits.assembly import build  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.assembly.drc import _bond_pad  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.assembly.sidecar import sidecar_dict  # pylint: disable=import-outside-toplevel

    x0, y0, x1, y1 = d.design.chip.box
    side = sidecar_dict(build(d.design), overlays=False)["instances"]
    names = names or [n for n, s in d.data["instances"].items() if _bond_pad(s["cell"])]
    out = {}
    for n in names:
        b = side[n]["bbox"]
        out[n] = round(min(b[0] - x0, b[1] - y0, x1 - b[2], y1 - b[3]), 3)
    return out


def shift_reference(ref: LegacyChip, dx: float, dy: float) -> LegacyChip:
    """Move a legacy reference by the rebuild's centring shift (in place), so the per-instance XOR compares the
    same cells at the same place; the pads the PDK pad rule moved stay at their legacy place in the reference."""
    pya = ref.pya
    if dx or dy:
        ref.top.transform(pya.DTrans(pya.DVector(dx, dy)))
        ref.boxes = {k: b.moved(pya.DVector(dx, dy)) for k, b in ref.boxes.items()}
    return ref


def fem_send(jobs: dict, run: bool = False, timeout: float | None = None) -> str:
    """The "send the job" step: report the AEDT found (2024 R1 = v241 or newer) and, with ``run=True``, solve each
    exported Ansys job in a **new batch, non-graphical** AEDT (``sim_tools.hfss.solve_job``; never an AEDT window
    the user has open). Returns Markdown."""
    from quantcore_circuits.sim_tools.ansys import aedt_version, find_ansys_executable  # pylint: disable=C0415

    exe = find_ansys_executable()
    ver = aedt_version(exe) if exe else None
    out = [f"AEDT on this machine: `{exe}` (v{ver})" if exe else "AEDT on this machine: not found"]
    if not jobs:
        return "\n\n".join(out + ["No FEM jobs: this chip has no sim groups (nothing to excite)."])
    if not run:
        out.append(f"`RUN_FEM = False`: {len(jobs)} job(s) exported, none solved. Set `RUN_FEM = True` to solve them "
                   "here (batch, non-graphical), or run `qcc sim run <job>` on a machine with AEDT 2024 R1+.")
        return "\n\n".join(out)
    if exe is None or (ver is not None and ver < 241):
        return "\n\n".join(out + ["`RUN_FEM = True` but no AEDT 2024 R1 (v241) or newer: nothing solved."])
    from quantcore_circuits.sim_tools.hfss import solve_job  # pylint: disable=import-outside-toplevel

    rows = ["| group | job | status | solve time (s) |", "|---|---|---|---|"]
    for group, (job, _) in jobs.items():
        r = solve_job(job, executable=exe, graphical=False, timeout=timeout)
        status = "solved" if r.ok and r.results else ("failed: " + ", ".join(r.status[-2:]) if r.status else "failed")
        rows.append(f"| {group} | `{Path(job).as_posix()}` | {status} | {r.seconds:.0f} |")
    return "\n\n".join(out + ["\n".join(rows)])


def fem_bring_back(d, design_path, jobs: dict, groups: dict | None = None, max_modes: int = 2) -> str:
    """The "bring it back" step: for every job with ``results/results.json``, fill the LOM of its group with the
    FEM C-matrix (``fill(model, design, job)``, matched by net name) and show estimate vs extracted, then the LOM
    simulation with the extracted values. Jobs without results are listed with what would appear."""
    from quantcore_circuits.circuit.fill import fill  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom.simulate import simulate  # pylint: disable=import-outside-toplevel

    missing, out = [], []
    for group, (job, _) in jobs.items():
        if not (Path(job) / "results" / "results.json").exists():
            missing.append(f"`{Path(job).as_posix()}`")
            continue
        sel = (groups or {}).get(group) or list(d.data["sim_groups"][group]["instances"])
        model = d.lom(select=sel).model
        est, fem = fill(model, design_path), fill(model, design_path, job)
        rows = [f"**{group}** (`{Path(job).as_posix()}`)", "",
                "| branch | type | estimate | FEM | Δ (%) |", "|---|---|---|---|---|"]
        base = {x["branch"]: x["estimate"] for x in est.branch_table()}
        for r in fem.branch_table():
            if r["extracted"] is None:
                continue
            e = base.get(r["branch"])
            delta = "–" if not e else f"{100 * (r['extracted'] - e) / abs(e):+.1f}"
            rows.append(f"| `{r['branch']}` | {r['type']} | {'–' if e is None else f'{e:.4g}'} {r['unit']} | "
                        f"{r['extracted']:.4g} {r['unit']} | {delta} |")
        a, b = simulate(est, max_modes=max_modes).params, simulate(fem, max_modes=max_modes).params
        rows += ["", "| parameter | LOM (estimates) | LOM (FEM C-matrix) |", "|---|---|---|"]
        rows += [f"| `{k}` | {a[k]:.5g} | {b.get(k, float('nan')):.5g} |" for k in a]
        out.append("\n".join(rows))
    if missing:
        out.append(f"No FEM results yet for {len(missing)} job(s) ({', '.join(missing[:4])}"
                   f"{', …' if len(missing) > 4 else ''}). After a solve each job holds `results/results.json`; "
                   "this cell then fills the LOM with the extracted C-matrix (`fill(model, DESIGN, job)`) and shows "
                   "the estimate next to the FEM value per capacitance, and f_q / α / f_r / χ re-simulated with them.")
    return "\n\n".join(out) or "No FEM jobs."


def compare_md(before, after, keys=None, label=("before", "after")) -> str:
    """Before/after table of two LOM results (``LomResult.params``) for the iterate step."""
    a, b = before.params, after.params
    keys = keys or [k for k in a if k in b]
    out = [f"| parameter | {label[0]} | {label[1]} | Δ |", "|---|---|---|---|"]
    for k in keys:
        x, y = a.get(k), b.get(k)
        if x is None or y is None:
            continue
        out.append(f"| `{k}` | {x:.5g} | {y:.5g} | {y - x:+.4g} |")
    return "\n".join(out)


def fab_md(d, cheese: bool = True, path=None) -> str:
    """Write the fab mask (``export_fab``: PDK fab layers, corner rounding, the build's cheese) to
    ``build/<design>_fab.oas`` and return a Markdown report (layers, polygon counts, cheese source and holes).
    ``cheese=False`` for chips whose original cheese is drawn as 1/0 holes in the design (``cheese: "original"``):
    the holes stay on 1/0 and no PDK band is added at export."""
    from quantcore_circuits.layouts.wafers.fab_export import export_fab  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

    if d.result is None:
        d.show()
    rep = {}
    path = export_fab(d.result, path or Path("build") / f"{d.design.name}_fab.oas", report=rep, cheese=cheese)
    layers = get_pdk(d.design.pdk).fab_layers
    rows = [f"Fab mask: `{Path(path).as_posix()}` · cheese source **{rep['cheese_source']}** "
            f"({rep['cheese_holes']} PDK-band holes) · corner rounding on", "",
            "| fab layer | PDK name | polygons |", "|---|---|---|"]
    rows += [f"| {layers[k].layer}/{layers[k].datatype} | {k} | {n} |"
             for k, n in sorted(rep["written"].items(), key=lambda kv: (layers[kv[0]].layer, layers[kv[0]].datatype))]
    if rep.get("dropped"):
        rows += ["", "**Not in the mask (no PDK fab layer):** "
                 + ", ".join(f"{k} ({n})" for k, n in rep["dropped"].items())]
    return "\n".join(rows)


def circuit_box(d, skip=("TextLabel",)):
    """``_common.content_box`` without the ``skip`` cells (free text labels: annotations the source places relative
    to the die edge, e.g. resonator_chip_01's "RES" near the top): instances and routes of the circuit (µm)."""
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.assembly import build  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.assembly.sidecar import sidecar_dict  # pylint: disable=import-outside-toplevel

    side = sidecar_dict(build(d.design), overlays=False)
    box = pya.DBox()
    for name, inst in side["instances"].items():
        if inst.get("bbox") and d.data["instances"][name]["cell"] not in skip:
            box += pya.DBox(*inst["bbox"])
    for route in side["routes"].values():
        for x, y in route.get("polyline") or []:
            box += pya.DPoint(x, y)
    return box


def center_circuit(d, skip=("TextLabel",), tol: float = 50.0) -> tuple[float, float]:
    """PDK placement rule: centre the circuit (:func:`circuit_box`) in the die. Each axis is shifted only when it is
    more than ``tol`` µm off, so a symmetric legacy chip keeps its exact legacy x; everything moves (the labels
    too, so they stay where the source put them relative to the circuit). Pads placed with ``edge`` slide back to
    the edge rule along their own axis. Returns the shift (dx, dy) applied (µm)."""
    import _common as C  # pylint: disable=import-outside-toplevel

    x0, y0, x1, y1 = d.design.chip.box
    box = circuit_box(d, skip)
    dx = round((x0 + x1) / 2 - box.center().x, 1)
    dy = round((y0 + y1) / 2 - box.center().y, 1)
    dx, dy = (dx if abs(dx) > tol else 0.0), (dy if abs(dy) > tol else 0.0)
    if dx or dy:
        C.translate_design(d, dx, dy)
    return (dx, dy)


def clip_holes(x: float, n: int, lo: float, hi: float, pitch: float = 20.0, hole: float = 5.0) -> tuple[float, int]:
    """A legacy flux-hole row (``n`` hole centres at ``x + i·pitch``, ``hole`` µm squares) cut to the holes whose
    square lies inside [lo, hi] (e.g. the feedline span, when the PDK pad rule moved the pads over the row's ends).
    Returns (first centre, count); the kept holes stay on the legacy grid."""
    keep = [i for i in range(int(n)) if x + i * pitch - hole / 2 >= lo - 1e-9 and x + i * pitch + hole / 2 <= hi + 1e-9]
    return (x + keep[0] * pitch, len(keep)) if keep else (x, 0)
