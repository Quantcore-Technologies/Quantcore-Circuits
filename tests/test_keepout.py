"""3/0 keep-out hooks (``qcc_keepout``, design rule 2026-11-03) vs. the legacy PCells' / scripts' own 3/0 (``fab_l``)
geometry, 1-dbu tolerance, on the parameter sets of the legacy golden tests."""

from __future__ import annotations

import contextlib
import io

import pytest
from kqcircuits.pya_resolver import pya

from quantcore_circuits import layouts
from quantcore_circuits.layouts.others import connector_pads, cpw_segment, markers
from quantcore_circuits.layouts.others.legacy_resonators import (
    CoupledConnector,
    CoupledResonator,
    CpwResonator,
    QubitResonator,
)
from quantcore_circuits.layouts.others.test_pads import JunctionGroundPad, JunctionTestPads, legacy_test_pad_params
from tests.legacy_ref import legacy, scripts
from tests.test_golden_legacy_resonators import CONNECTOR, COUPLED, CPW_RES, QUBIT_RES, RENAME

pytestmark = pytest.mark.skipif(not legacy.available(), reason="legacy components/ folder not present")

QC = "pymacros/QuantumPcells"
M3 = (3, 0)


def keepout(cls, **params) -> pya.Region:
    shapes = cls.qcc_keepout(params)
    assert shapes and all(isinstance(s, (pya.DBox, pya.DPolygon)) for s in shapes)
    out = pya.Region()
    for s in shapes:
        out.insert((pya.DPolygon(s) if isinstance(s, pya.DBox) else s).to_itype(0.001))
    return out.merged()


def assert_xor_empty(a: pya.Region, b: pya.Region, what: str):
    diff = (a.merged() ^ b.merged()).sized(-1)  # ignore slivers up to 2 dbu
    assert diff.is_empty(), f"{what}: XOR not empty, area {diff.area()} dbu², bbox {diff.bbox()}"
    assert a.area() > 0, f"{what}: empty"


_LAYOUTS = []  # legacy layouts stay alive: a region built from a shape iterator still refers to its layout


def legacy_m3(rel, cls, display, params, **extra):
    """The legacy PCell's 3/0 (as ``legacy.legacy_pcell_regions``, keeping the layout alive: a one-box 3/0 region
    is not materialised by ``merged()``)."""
    lib_name = legacy.legacy_pcell_library(f"{QC}/{rel}", {cls: display})
    layout = pya.Layout()
    layout.dbu = 0.001
    _LAYOUTS.append(layout)
    with contextlib.redirect_stdout(io.StringIO()):  # several legacy cells print
        cell = layout.create_cell(display, lib_name, {**extra, **params})
        return pya.Region(cell.begin_shapes_rec(layout.layer(*M3))).merged()


# ---- Xmon ---------------------------------------------------------------------------------------------------------
_XMON = {
    "thickness": "arm_width",
    "width": "cross_length",
    "da": "ground_sliver",
    "spacing": "gap",
    "cap_spacing": "claw_spacing",
    "pthickness": "claw_base",
    "fwidth": "claw_finger_width",
    "hlength": "claw_length",
    "ggap": "claw_ground_gap",
    "tail_l": "claw_tail_length",
}


@pytest.mark.parametrize(
    "legacy_params",
    [{}, {"handle": 3}, {"width": 400, "thickness": 50, "pthickness": 35, "fwidth": 35, "spacing": 20, "da": 1}],
)
def test_xmon_keepout_matches_legacy(legacy_params):
    """Legacy ``Xmon Cross`` 3/0 = the cross grown by 2·pthickness + 10 + fwidth (here 85 µm by default)."""
    with contextlib.redirect_stdout(io.StringIO()):
        ref = legacy.legacy_region("Xmon Cross", layer=M3, fab=True, **legacy_params)
    ours = {_XMON[k]: v for k, v in legacy_params.items() if k in _XMON}
    assert_xor_empty(keepout(layouts.Xmon, **ours), ref, f"Xmon 3/0 {legacy_params}")


def test_xmon_keepout_extent():
    """Default Xmon: cross tip 150 µm + 85 µm; the claw tail tip (254 µm) is left to the route's keep-out."""
    assert keepout(layouts.Xmon).bbox() == pya.Box(-235000, -235000, 235000, 235000)


# ---- resonators -----------------------------------------------------------------------------------------------------
def _ours(params):
    return {RENAME.get(k, k): v for k, v in params.items()}


@pytest.mark.parametrize("params", COUPLED, ids=[f"coupled{i}" for i in range(len(COUPLED))])
def test_coupled_resonator_keepout(params):
    ref = legacy_m3("CPW_Coupled_Resonator.lym", "CoupledResonator", "Coupled Resonator", params, fab=True)
    assert_xor_empty(keepout(CoupledResonator, **_ours(params)), ref, f"CoupledResonator 3/0 {params}")


@pytest.mark.parametrize("params", CPW_RES, ids=[f"cpwres{i}" for i in range(len(CPW_RES))])
def test_cpw_resonator_keepout(params):
    ref = legacy_m3("CPWResonator.lym", "CPWResonator", "CPW Resonator", params, fab=True)
    assert_xor_empty(keepout(CpwResonator, **_ours(params)), ref, f"CpwResonator 3/0 {params}")


@pytest.mark.parametrize("params", QUBIT_RES, ids=[f"qubitres{i}" for i in range(len(QUBIT_RES))])
def test_qubit_resonator_keepout(params):
    ref = legacy_m3("Qubit_Resonator.lym", "QubitResonator", "Qubit Resonator", params, fab=True)
    assert_xor_empty(keepout(QubitResonator, **_ours(params)), ref, f"QubitResonator 3/0 {params}")


@pytest.mark.parametrize("params", CONNECTOR, ids=[f"connector{i}" for i in range(len(CONNECTOR))])
def test_coupled_connector_keepout(params):
    ref = legacy_m3("CoupledConnector.lym", "CoupledConnector", "Coupled Connector", params, fab=True)
    assert_xor_empty(keepout(CoupledConnector, **_ours(params)), ref, f"CoupledConnector 3/0 {params}")


# ---- CPW segment, pads, marker --------------------------------------------------------------------------------------
@pytest.mark.parametrize("length, c_gap", [(5950, 0), (5460, 0), (200, 4)])
def test_cpw_segment_keepout(length, c_gap):
    ref = legacy_m3(
        "CPW.lym",
        "CPW",
        "Coplanar Waveguide",
        {"length": length, "lc_thickness": 2, "rc_thickness": 2, "c_gap": c_gap},
        fab=True,
    )
    ours = keepout(cpw_segment.CpwSegment, length=length, lc_thickness=2, rc_thickness=2, keepout_gap=c_gap)
    assert_xor_empty(ours, ref, f"CpwSegment 3/0 {length}")


@pytest.mark.parametrize(
    "params",
    [
        {"trace_width": 10, "pad_height": 300, "pad_width": 275, "conn_height": 300, "round": False},  # chip_01/02
        {"trace_width": 10, "pad_height": 200, "pad_width": 600, "conn_height": 500, "round": True},  # chip_03
    ],
)
def test_connector_pad_keepout(params):
    ref = legacy_m3("connector_pad.lym", "ConnectorPad", "Connector Pad", params, fab=True, sim=False, trace_gap=6)
    ours = keepout(
        connector_pads.ConnectorPad,
        pad_width=params["pad_width"],
        pad_height=params["pad_height"],
        taper_length=params["conn_height"],
        a=params["trace_width"],
        b=6,
        rounded=params["round"],
    )
    assert_xor_empty(ours, ref, f"ConnectorPad 3/0 {params}")


@pytest.mark.parametrize("rounded", [False, True])
def test_bond_pad_keepout(rounded):
    params = {"pad_width": 400, "pad_gap": 225, "pad_height": 450, "conn_height": 450, "trace_width": 10}
    with contextlib.redirect_stdout(io.StringIO()):
        ref = legacy.legacy_region(
            "Connector Pad 2", layer=M3, fab=True, sim=False, round=rounded, trace_gap=6, **params
        )
    ours = keepout(
        layouts.BondPad, pad_width=400, pad_gap=225, pad_height=450, taper_length=450, a=10, b=6, rounded=rounded
    )
    assert_xor_empty(ours, ref, f"BondPad 3/0 rounded={rounded}")


@pytest.mark.parametrize("thickness, width", [(50, 500), (20, 150)])
def test_corner_marker_keepout(thickness, width):
    ref = legacy_m3("Marker.lym", "Marker", "Marker", {"thickness": thickness, "width": width})
    assert_xor_empty(keepout(markers.CornerMarker, thickness=thickness, width=width), ref, "CornerMarker 3/0")
    assert markers.CornerMarker.qcc_keepout({"hsq": True}) == []  # chip_05's HSQ markers put fab_l on 150/0


# ---- junction test pads (legacy scripts) ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "script, ref_cell, size, second",
    [("testPad_AVAQUS.py", "TESTAVA", 1.0, None), ("testPad_Nb_TL_HSQ.py", "TEST_TL", 2.5, 0.6)],
)
def test_junction_test_pads_keepout(tmp_path, script, ref_cell, size, second):
    args = (size,) if second is None else (size, second)
    ref = scripts.module_path_layout(script, "create_testPad", tmp_path, *args)
    params = legacy_test_pad_params(script[:-3], size, second or 0)
    assert_xor_empty(keepout(JunctionTestPads, **params), scripts.top_region(ref, ref_cell, M3), f"{script} 3/0")


def test_junction_ground_pad_keepout(tmp_path):
    ref = scripts.module_path_layout("testPad.py", "create_testPad", tmp_path, 1.0)
    ours = keepout(JunctionGroundPad, finger_width=0.26)
    assert_xor_empty(ours, scripts.top_region(ref, "TEST", M3), "testPad 3/0")


def test_keepout_hook_in_the_fab_export():
    """``fab_export.keepout_region`` uses the hook (not bbox + margin) for a placed cell that has one."""
    from quantcore_circuits.layouts.wafers.fab_export import keepout_region
    from quantcore_circuits.pdk import get_pdk

    layout = pya.Layout()
    top = layout.create_cell("TOP")
    xmon = layouts.Xmon.create(layout, junction_type="No Squid")
    top.insert(pya.DCellInstArray(xmon.cell_index(), pya.DTrans(pya.DVector(1000, 2000))))
    region = keepout_region(top, get_pdk())
    hook = keepout(layouts.Xmon).moved(1000000, 2000000)
    assert (hook - region).is_empty()  # the legacy 3/0 shape is in the keep-out
    assert not (region - hook).is_empty() or region.bbox() == hook.bbox()


# ---- chip_11m probe-pad pair (the script's commented-out pads, uncommented in the executed copy) --------------------
def _chip_11m_with_pads(tmp_path, size=1.0, second=0.6):
    from pathlib import Path

    from tests.legacy_ref.scripts import _exec, _read

    on = {
        "#  cell.shapes(l1).insert(pya.Region(padBox)-pya.Region(pad1)-pya.Region(t1)-cutout)": (
            "  cell.shapes(l1).insert(pya.Region(padBox)-pya.Region(pad1)-pya.Region(t1)-cutout)"
        ),
        "#  cell.shapes(l3).insert(pya.Region(padBox)-pya.Region(pad2)-pya.Region(t2)-cutout)": (
            "  cell.shapes(l3).insert(pya.Region(padBox)-pya.Region(pad2)-pya.Region(t2)-cutout)"
        ),
    }
    namespace = _exec("chip_11m_TestJJ16x_pads.py", on)
    namespace["path"] = str(tmp_path / "chip_11m_")
    namespace["create_testPad"](size, second)
    (gds,) = sorted(Path(tmp_path).glob("chip_11m_*.gds"))
    return _read(gds)


def test_probe_pad_pair_matches_legacy(tmp_path):
    """``ProbePadPair`` 1/0 and 3/0 keep-out = chip_11m's pads with its two commented-out lines enabled; with
    ``junction_type="Trilayer Junction Compact"`` the JX_500 fingers sit in the cut-out as in the script."""
    from kqcircuits.defaults import default_layers

    from quantcore_circuits.layouts.others.test_pads import ProbePadPair

    ref = _chip_11m_with_pads(tmp_path)
    layout = pya.Layout()
    cell = ProbePadPair.create(layout)
    ours = pya.Region(cell.begin_shapes_rec(layout.layer(default_layers["1t1_base_metal_gap_wo_grid"]))).merged()
    assert_xor_empty(ours, scripts.top_region(ref, "JX_500", (1, 0)), "ProbePadPair 1/0")
    assert_xor_empty(keepout(ProbePadPair), scripts.top_region(ref, "JX_500", (3, 0)), "ProbePadPair 3/0")
    with_jj = ProbePadPair.create(
        layout,
        junction_type="Trilayer Junction Compact",
        junction_params='{"finger_width": 0.2, "second_finger_width": 0.6}',
    )
    for ours_layer, legacy_layer in (("1t1_SIS_junction", (2, 0)), ("1t1_SIS_junction_2", (4, 0))):
        got = pya.Region(with_jj.begin_shapes_rec(layout.layer(default_layers[ours_layer]))).merged()
        assert_xor_empty(got, scripts.top_region(ref, "JX_500", legacy_layer), f"ProbePadPair junction {legacy_layer}")
