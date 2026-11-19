"""Quantcore trilayer junction rule (design decisions #1 / #21 / #6, components-pdk): the PDK ``JunctionProcess``, the
``circuit.bridges`` junction functions (hand-computed values), the PDK-sized trilayer cells and the trilayer option
on Xmon, KQC qubits and ``metal:<Class>`` qubits."""

from __future__ import annotations

import importlib.util
import math

import pytest
from kqcircuits.defaults import default_layers
from kqcircuits.pya_resolver import pya

from quantcore_circuits import layouts
from quantcore_circuits.circuit import bridges
from quantcore_circuits.layouts.junctions.trilayer import (
    QuantcoreJunction,
    QuantcoreSquid,
    TrilayerJunction,
    TrilayerSquid,
    trilayer_junction_values,
)
from quantcore_circuits.pdk import QCC_LAYERS, get_pdk

SIS1, SIS2 = default_layers["1t1_SIS_junction"], default_layers["1t1_SIS_junction_2"]
ADD, GAP = default_layers["1t1_base_metal_addition"], default_layers["1t1_base_metal_gap_wo_grid"]
HSQ = QCC_LAYERS["hsq"]
_KEEP = []


def region(cell, info) -> pya.Region:
    return pya.Region(cell.begin_shapes_rec(cell.layout().layer(info))).merged()


def build(cls, **params):
    layout = pya.Layout()
    _KEEP.append(layout)
    return cls.create(layout, **params)


# ---- PDK rule and bridges (hand-computed) ------------------------------------------------------------------------
def test_hand_computed_junction_values():
    """Δ = 1.4 meV, R_n = 45 kΩ: I_c = πΔ/(2e R_n) = π·1.4e-3 V / 90 kΩ = 48.87 nA; L_J = Φ0/(2π I_c) = 6.734 nH;
    E_J/h = (Φ0/2π)²/(L_J h) = 24.27 GHz; E_C/h at 1 fF = e²/(2·1 fF·h) = 19.37 GHz."""
    ic = bridges.ic_from_rn(45e3, 1.4)
    assert ic * 1e9 == pytest.approx(48.869, abs=1e-3)
    assert bridges.lj_from_ic(ic) == pytest.approx(6.7344, abs=1e-4)
    assert bridges.lj_from_rn(45e3) == pytest.approx(6.7344, abs=1e-4)
    assert bridges.rn_from_lj(6.7344) == pytest.approx(45e3, rel=1e-4)
    assert bridges.ej_from_lj(6.7344) == pytest.approx(24.2725, abs=1e-3)
    assert bridges.lj_from_ej(bridges.ej_from_lj(8.0)) == pytest.approx(8.0)
    assert bridges.ec_from_c(1.0) == pytest.approx(19.3702, abs=1e-3)
    assert bridges.c_from_ec(bridges.ec_from_c(85.0)) == pytest.approx(85.0)
    ej, ec = 20.0, 0.25
    assert bridges.transmon_f01(ej, ec) == pytest.approx(math.sqrt(8 * ej * ec) - ec)
    assert bridges.ej_for_f01(bridges.transmon_f01(ej, ec), ec) == pytest.approx(ej)
    assert bridges.area_from_rn(45e3, 13500.0) == pytest.approx(0.3)


def test_pdk_junction_process():
    """The PDK junction rule: Nb Δ 1.4 meV, R_n window 40–50 kΩ, f_q 4–8 GHz; the assumed R_n·A gives the trilayer
    chips' nominal 0.5 × 0.6 µm junction 45 kΩ (J_c ≈ 0.163 µA/µm²)."""
    proc = get_pdk().junction
    assert proc.gap_meV == 1.4 and proc.rn_target_kohm == (40.0, 50.0) and proc.f_q_range_GHz == (4.0, 8.0)
    assert proc.rn_area_ohm_um2 / proc.nominal_area_um2 == pytest.approx(proc.rn_nominal_kohm * 1e3)
    assert proc.jc_uA_per_um2 == pytest.approx(0.1629, abs=1e-4)
    assert get_pdk("quantcore_nb_si_v1").junction == proc
    nominal = bridges.junction_from_fingers(*proc.nominal_fingers_um)
    assert nominal.rn_kohm == pytest.approx(45.0) and nominal.rn_in_window
    assert nominal.ic_each_nA == pytest.approx(48.869, abs=1e-3) and nominal.lj_nH == pytest.approx(6.7344, abs=1e-4)
    assert nominal.cj_fF == pytest.approx(15.0)
    squid = bridges.junction_from_fingers(0.5, 0.6, n=2)
    assert squid.rn_kohm == pytest.approx(22.5) and squid.lj_nH == pytest.approx(6.7344 / 2, abs=1e-4)
    assert not squid.rn_in_window  # a nominal SQUID's parallel R_n is below the single-junction window

    # 2026-11-13: the window is for the whole SQUID → the PDK SQUID's junctions are 90 kΩ each, parallel 45 kΩ
    from quantcore_circuits.layouts.junctions.trilayer import QuantcoreSquid
    from quantcore_circuits.layouts.registry import trilayer_junction

    sq = QuantcoreSquid.get_schema()
    pdk_squid = bridges.junction_from_fingers(sq["finger_width"].default, sq["second_finger_width"].default, n=2)
    assert pdk_squid.rn_kohm == pytest.approx(45.0, rel=0.02) and pdk_squid.rn_in_window
    assert pdk_squid.rn_each_kohm == pytest.approx(90.0, rel=0.02)
    params, junction = trilayer_junction("Swissmon", squid=True)
    assert params["junction_type"] == "Quantcore Squid" and junction["Lj_nH"] == pytest.approx(6.73, rel=0.02)


def test_size_junction_for_a_target_frequency():
    """6 GHz at C_Σ = 90 fF: E_C 0.215 GHz, E_J (f+E_C)²/8E_C = 22.4 GHz, L_J 7.29 nH, R_n 48.7 kΩ (in the window),
    straight finger 13500/48685/0.6 = 0.462 → 0.46 µm on the 0.01 µm grid; drawn f_q within 15 MHz."""
    s = bridges.size_junction(6.0, 90.0)
    assert s.ec_GHz == pytest.approx(19.3702 / 90, rel=1e-4)
    assert s.ej_GHz == pytest.approx((6.0 + s.ec_GHz) ** 2 / (8 * s.ec_GHz))
    assert s.lj_nH == pytest.approx(7.2859, abs=1e-3) and s.rn_kohm == pytest.approx(48.685, abs=1e-2)
    assert s.rn_in_window and s.f_in_window and not s.notes
    assert (s.finger_width, s.second_finger_width) == (0.46, 0.6)
    assert s.f_q_drawn_GHz == pytest.approx(6.0, abs=0.015)
    assert s.junction_params() == {"finger_width": 0.46, "second_finger_width": 0.6}
    assert s.design_junction() == {"Lj_nH": round(s.drawn.lj_nH, 4), "Cj_fF": 13.8}
    # outside the R_n window: an 8 GHz qubit on 120 fF needs E_J ≈ 52 GHz → L_J 3.2 nH → R_n ≈ 21 kΩ
    hot = bridges.size_junction(8.0, 120.0)
    assert hot.rn_kohm == pytest.approx(21.1, abs=0.2)
    assert not hot.rn_in_window and any("outside the process window" in n for n in hot.notes)
    # C_Σ without the junction: C_J of the sized area is added (fixed point)
    bare = bridges.size_junction(5.0, 80.0, c_includes_junction=False)
    assert bare.c_sigma_fF == pytest.approx(80.0 + 50.0 * bridges.area_from_rn(bare.rn_kohm * 1e3, 13500.0), rel=1e-6)
    # SQUID: each junction gets twice the total L_J
    sq = bridges.size_junction(6.0, 90.0, n=2)
    assert sq.drawn.n == 2 and sq.drawn.lj_nH == pytest.approx(sq.lj_nH, rel=0.05)


def test_fingers_for_lj_limits():
    straight, bent, notes = bridges.fingers_for_lj(6.7344)
    assert (straight, bent, notes) == (0.5, 0.6, [])
    straight, bent, notes = bridges.fingers_for_lj(400.0)  # tiny junction: straight at the minimum, bent shrinks
    assert straight == 0.1 and bent < 0.6 and notes
    straight, bent, notes = bridges.fingers_for_lj(0.5)  # huge junction: clipped
    assert straight == 2.0 and notes


# ---- trilayer cells sized by the rule ----------------------------------------------------------------------------
@pytest.mark.parametrize("cls, n", [(TrilayerJunction, 1), (TrilayerSquid, 2)])
def test_lj_sizing_draws_the_rule_fingers(cls, n):
    """``lj_nH`` → the fingers of :func:`fingers_for_lj` (bent kept at 0.6 µm): same 2/0, 4/0, 50/0 as the cell
    built with those widths; KQC's ``junction_width`` (≥ 0.1 µm) sets the straight finger the same way."""
    lj = 6.7344 / n
    straight, bent, _ = bridges.fingers_for_lj(lj, n)
    ref = build(cls, finger_width=straight, second_finger_width=bent)
    for params in ({"lj_nH": lj}, {"junction_width": straight, "second_finger_width": bent}):
        cell = build(cls, **params)
        for layer in (SIS1, SIS2, HSQ):
            assert (region(cell, layer) ^ region(ref, layer)).is_empty(), (params, layer)
    # KQC's default junction_width (0.02 µm) is ignored
    assert (region(build(cls, junction_width=0.02), SIS1) ^ region(build(cls), SIS1)).is_empty()


@pytest.mark.parametrize("cls, n", [(QuantcoreJunction, 1), (QuantcoreSquid, 2)])
def test_quantcore_junction_cells(cls, n):
    """PDK junctions: nominal fingers (0.5 × 0.6 µm; SQUID 2 × 0.25 × 0.6 µm), fingers on 2/0 + 4/0, spacer + gradient, and the CLEARER box
    (window − 1 µm each side × window height) on base_metal_addition; drawn values on the rule."""
    cell = build(cls, window_height=20)
    assert not region(cell, SIS1).is_empty() and not region(cell, SIS2).is_empty() and not region(cell, HSQ).is_empty()
    assert all(not region(cell, QCC_LAYERS[f"spacer_{k}"]).is_empty() for k in (1, 2, 3))
    assert region(cell, ADD).bbox() == pya.Box(-15000, 0, 15000, 20000)
    straight = 0.5 if n == 1 else 0.25  # the window is for the whole SQUID (2026-11-13): 90 kΩ junctions
    plain = build(
        {QuantcoreJunction: TrilayerJunction, QuantcoreSquid: TrilayerSquid}[cls],
        finger_width=straight,
        second_finger_width=0.6,
        window_height=20,
    )
    assert (region(cell, SIS1) ^ region(plain, SIS1)).is_empty() and region(plain, ADD).is_empty()
    v = trilayer_junction_values(f"Quantcore {'Squid' if n == 2 else 'Junction'}")
    assert v.n == n and v.rn_kohm == pytest.approx(45.0) and v.lj_nH == pytest.approx(6.7344, abs=1e-4)
    assert trilayer_junction_values("Quantcore Junction", {"lj_nH": 8.0}).lj_nH == pytest.approx(8.0, rel=0.03)
    assert trilayer_junction_values("Manhattan") is None


def test_kqc_qubit_with_quantcore_junction():
    """A KQC Swissmon with ``junction_type="Quantcore Junction"``: trilayer fingers + spacer in its junction gap,
    the CLEARER inside the qubit's etch (so the fab 1/0 keeps metal there), and ``junction_width`` sizes the finger."""
    cell = build(layouts.Swissmon, junction_type="Quantcore Junction", fluxline_type="none", junction_width=0.34)
    add, gap = region(cell, ADD), region(cell, GAP)
    sis = region(cell, SIS1)
    assert not sis.is_empty() and not region(cell, SIS2).is_empty() and not region(cell, HSQ).is_empty()
    assert not add.is_empty() and (add - gap).is_empty()  # the clearer lies in the qubit's gap
    ref = build(QuantcoreJunction, finger_width=0.34)
    assert abs(sis.area() - region(ref, SIS1).area()) < 10  # same straight-finger window (moved into place)


def test_registry_trilayer_junction_helper():
    from quantcore_circuits.layouts.registry import trilayer_junction

    params, junction = trilayer_junction("Xmon", lj_nH=10.0)
    assert params == {"junction_type": "Quantcore Junction", "junction_params": {"lj_nH": 10.0}}
    straight, bent, _ = bridges.fingers_for_lj(10.0)
    assert junction == {
        "Lj_nH": round(bridges.junction_from_fingers(straight, bent).lj_nH, 4),
        "Cj_fF": round(50 * straight * bent, 3),
    }
    params, _ = trilayer_junction("Swissmon", lj_nH=10.0)
    assert params == {"junction_type": "Quantcore Junction", "junction_width": straight}
    params, junction = trilayer_junction("DoublePads", squid=True)
    # the PDK SQUID is the nominal device (45 kΩ parallel, 2026-11-13), not two nominal junctions (was 3.3672)
    assert params == {"junction_type": "Quantcore Squid"} and junction["Lj_nH"] == pytest.approx(6.7344, abs=1e-4)
    with pytest.raises(ValueError, match="no junction_type"):
        trilayer_junction("BondPad")


def test_xmon_lom_uses_the_drawn_trilayer_junction():
    """No design ``junction.Lj_nH``: the Xmon's LOM takes the drawn Quantcore junction (PDK rule); with one, the
    design value wins."""
    from quantcore_circuits.design.schema import Instance
    from quantcore_circuits.lom.fragment import lom_model

    def j(params, junction=None):
        data = {"cell": "Xmon", "params": params, "place": {"at": [0, 0]}}
        if junction:
            data["junction"] = junction
        frag = lom_model("Xmon")("Q", Instance.model_validate(data), get_pdk())
        return next(e for e in frag.elements if e.name == "J_Q")

    e = j({"junction_type": "Quantcore Junction"})
    assert e.type == "JJ" and e.value["Lj_nH"] == pytest.approx(6.7344, abs=1e-4) and "drawn" in e.value["source"]
    e = j({"junction_type": "Quantcore Squid", "junction_params": {"lj_nH": 4.0}})
    assert e.type == "SQUID" and e.value["Lj_nH"] == pytest.approx(4.0, rel=0.05)
    e = j({"junction_type": "Quantcore Junction"}, {"Lj_nH": 9.0, "Cj_fF": 2.0})
    assert e.value["Lj_nH"] == 9.0 and e.value["source"] == "design"


# ---- metal:<Class> with trilayer junctions -------------------------------------------------------------------------
metal = pytest.mark.skipif(importlib.util.find_spec("qiskit_metal") is None, reason="qiskit_metal not installed")


def _metal(name, **params):
    from quantcore_circuits.layouts.registry import resolve_cell

    cls = resolve_cell(f"metal:{name}")
    return build(cls, **params)


@metal
def test_metal_transmon_cross_trilayer_spans_its_junction_gap():
    """TransmonCross: Metal's junction line (cross arm end → ground, 20 µm) → a Quantcore junction whose window is
    exactly that gap (origin on the ground edge, port_common on the arm end), 32 µm wide; the Metal footprint is
    gone, the CLEARER lies inside the etch; ``Metal`` and ``Sim`` keep the footprint, ``No Squid`` draws none."""
    footprint = _metal("TransmonCross")
    tri = _metal("TransmonCross", junction_type="Quantcore Junction")
    fp, sis = region(footprint, SIS1), region(tri, SIS1)
    assert fp.bbox() == pya.Box(-10000, -220000, 10000, -200000)  # Metal: 20 µm wide footprint over the gap
    assert sis.bbox() == pya.Box(-16000, -220000, 16000, -200000)  # trilayer window: the same gap, 32 µm wide
    assert not region(tri, SIS2).is_empty() and not region(tri, HSQ).is_empty()
    add, gap = region(tri, ADD), region(tri, GAP)
    assert not add.is_empty() and (add - gap).is_empty()
    assert (fp ^ region(_metal("TransmonCross", junction_type="Sim"), SIS1)).is_empty()
    assert region(_metal("TransmonCross", junction_type="No Squid"), SIS1).is_empty()
    sized = _metal("TransmonCross", junction_type="Quantcore Junction", junction_params={"lj_nH": 12.0})
    assert not (region(sized, SIS1) ^ sis).is_empty()  # the L_J sizing changes the fingers


@metal
def test_metal_pocket_trilayer_squid_and_validation():
    pocket = _metal("TransmonPocket", junction_type="Quantcore Squid")
    assert region(pocket, SIS1).bbox() == pya.Box(-16000, -15000, 16000, 15000)  # the 30 µm pad gap
    assert len(list(region(pocket, HSQ).each())) == 4  # two junctions × two HSQ boxes
    from quantcore_circuits.layouts.registry import resolve_cell

    with pytest.raises(ValueError, match="not a trilayer junction cell"):
        resolve_cell("metal:TransmonPocket").qcc_params({"junction_type": "Manhattan"})


@metal
def test_metal_lom_uses_the_drawn_trilayer_junction():
    from quantcore_circuits.design.schema import Instance
    from quantcore_circuits.lom.fragment import lom_model

    def j(params, junction=None):
        data = {"cell": "metal:TransmonCross", "params": params, "place": {"at": [0, 0]}}
        if junction:
            data["junction"] = junction
        frag = lom_model(data["cell"])("Q", Instance.model_validate(data), get_pdk())
        return [e for e in frag.elements if e.name == "J_Q"]

    (e,) = j({"junction_type": "Quantcore Junction"})
    assert e.type == "JJ" and e.value["Lj_nH"] == pytest.approx(6.7344, abs=1e-4) and "drawn" in e.value["source"]
    (e,) = j({"junction_type": "Quantcore Squid"}, {"Lj_nH": 5.0, "Cj_fF": 2.0})
    assert e.type == "SQUID" and e.value["Lj_nH"] == 5.0
    assert j({"junction_type": "No Squid"}) == []


# ---- TwoPadTransmon (metal/tut443) ---------------------------------------------------------------------------------
def test_two_pad_transmon_trilayer_junction():
    """``junction_type`` on TwoPadTransmon: none by default (legacy), a Quantcore junction across the pad gap
    (window = the gap between the pad faces, 32 µm wide, CLEARER touching both pads), sized by ``junction_params``;
    tut443's 200 µm gap between 1000 µm pads with no own pocket works the same; PadCoupler has none."""
    from quantcore_circuits.layouts.others.couplers import PadCoupler
    from quantcore_circuits.layouts.qubits.legacy_transmon import TwoPadTransmon

    assert region(build(TwoPadTransmon), SIS1).is_empty()
    assert region(build(TwoPadTransmon, junction_type="Sim"), SIS1).is_empty()
    cell = build(TwoPadTransmon, junction_type="Quantcore Junction")
    assert region(cell, SIS1).bbox() == pya.Box(-5000, -16000, 5000, 16000)  # the 10 µm gap
    clearer = region(cell, ADD) - region(build(TwoPadTransmon), ADD)
    assert clearer.bbox() == pya.Box(-5000, -15000, 5000, 15000)
    assert not region(cell, HSQ).is_empty()
    sized = build(
        TwoPadTransmon,
        **TwoPadTransmon.qcc_params({"junction_type": "Quantcore Junction", "junction_params": {"lj_nH": 12.0}}),
    )
    assert not (region(sized, SIS1) ^ region(cell, SIS1)).is_empty()
    tut = {"pad_thickness": 500, "pad_height": 1000, "gap": 200, "a": 0, "lead_length": 0, "pocket_margin": 0}
    big = build(TwoPadTransmon, junction_type="Quantcore Junction", **tut)
    assert region(big, SIS1).bbox() == pya.Box(-100000, -16000, 100000, 16000)
    assert region(build(PadCoupler, junction_type="Quantcore Junction"), SIS1).is_empty()  # a coupler never draws one


def test_two_pad_transmon_lom_junction():
    from quantcore_circuits.design.schema import Instance
    from quantcore_circuits.lom.fragment import lom_model

    def j(params, junction=None):
        data = {"cell": "TwoPadTransmon", "params": params, "place": {"at": [0, 0]}}
        if junction:
            data["junction"] = junction
        frag = lom_model("TwoPadTransmon")("Q", Instance.model_validate(data), get_pdk())
        return next(e for e in frag.elements if e.name == "J_Q")

    assert j({}).type == "JJ" and j({}).value["Lj_nH"] is None  # legacy: junction assumed, value from the design
    e = j({"junction_type": "Quantcore Junction", "junction_params": {"lj_nH": 5.3448}})
    assert e.type == "JJ" and e.value["Lj_nH"] == pytest.approx(5.3448, rel=0.03) and "drawn" in e.value["source"]
    assert j({"junction_type": "Quantcore Squid"}).type == "SQUID"
    assert j({"junction_type": "Quantcore Junction"}, {"Lj_nH": 5.0, "Cj_fF": 2.0}).value["Lj_nH"] == 5.0


@metal
@pytest.mark.parametrize("tile", ["jj_manhattan", "jj_dolan"])
def test_metal_junction_tiles_get_a_trilayer_stand_in(tile):
    """Metal junction tiles: ``"Metal"`` draws Metal's junction metal on 2/0; a trilayer ``junction_type`` replaces it
    by the trilayer cell spanning the tile's bounding box (≤ 32 µm wide), with refpoints for the junction port."""
    plain = _metal(tile)
    tri = _metal(tile, junction_type="Quantcore Junction")
    box = region(plain, SIS1).bbox()
    sis = region(tri, SIS1)
    assert sis.bbox().bottom == box.bottom and sis.bbox().top == box.top
    assert sis.bbox().width() <= min(32000, box.width()) and not region(tri, HSQ).is_empty()
    assert not (sis ^ region(plain, SIS1)).is_empty()
    assert region(_metal(tile, junction_type="No Squid"), SIS1).is_empty()
