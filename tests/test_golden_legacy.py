"""Golden XOR tests: ported cells vs. the legacy QWri PCells (fab mode), tolerance 1 dbu."""

import pytest
from kqcircuits.pya_resolver import pya

from quantcore_circuits import layouts
from quantcore_circuits.pdk import QCC_LAYERS
from tests.legacy_ref import legacy

pytestmark = pytest.mark.skipif(not legacy.available(), reason="legacy components/ folder not present")

GAP = pya.LayerInfo(130, 1)  # 1t1_base_metal_gap_wo_grid
SIS1, SIS2 = pya.LayerInfo(136, 1), pya.LayerInfo(139, 1)
HSQ = QCC_LAYERS["hsq"]  # legacy drew HSQ on 500/0; the PDK v2 spacer layer is 50/0


def region(cell, info):
    return pya.Region(cell.begin_shapes_rec(cell.layout().layer(info))).merged()


def assert_xor_empty(a: pya.Region, b: pya.Region, what: str):
    diff = (a.merged() ^ b.merged()).sized(-1)  # ignore slivers up to 2 dbu
    assert diff.is_empty(), f"{what}: XOR not empty, area {diff.area()} dbu², bbox {diff.bbox()}"
    assert a.area() > 0


@pytest.mark.parametrize(
    "legacy_params, claws",
    [
        ({"handle": 1}, ["n"]),
        ({"handle": 3}, ["n", "w", "e"]),
        ({"handle": 4, "ground": True}, ["w", "e"]),
        # chip_10a settings
        (
            {
                "width": 400,
                "handle": 1,
                "cap_spacing": 6,
                "da": 1,
                "thickness": 50,
                "pthickness": 35,
                "fwidth": 35,
                "spacing": 20,
                "ggap": 6,
                "hlength": 130,
            },
            ["n"],
        ),
    ],
)
def test_xmon_matches_legacy(legacy_params, claws):
    ref = legacy.legacy_region("Xmon Cross", fab=True, **legacy_params)
    p = {
        "thickness": 25,
        "width": 300,
        "da": 2,
        "spacing": 25,
        "cap_spacing": 2,
        "pthickness": 25,
        "fwidth": 25,
        "hlength": 100,
        "tail": True,
        "ground": False,
        "ggap": 6,
        "tail_l": 50,
        **legacy_params,
    }
    layout = pya.Layout()
    cell = layouts.Xmon.create(
        layout,
        junction_type="No Squid",
        claws=claws,
        arm_width=p["thickness"],
        cross_length=p["width"],
        ground_sliver=p["da"],
        gap=p["spacing"],
        claw_spacing=p["cap_spacing"],
        claw_base=p["pthickness"],
        claw_finger_width=p["fwidth"],
        claw_length=p["hlength"],
        claw_tail=p["tail"],
        claw_ground=p["ground"],
        claw_ground_gap=p["ggap"],
        claw_tail_length=p["tail_l"],
        claw_tail_gap=p["cap_spacing"],  # the legacy PCell clears the tail like the claw (#22: default = CPW b)
    )
    assert_xor_empty(region(cell, GAP), ref, f"Xmon {legacy_params}")


@pytest.mark.parametrize("tail_gap, b, expect", [(-1, 6, 6), (-1, 10, 10), (10, 6, 10), (2, 6, 2)])
def test_xmon_claw_tail_gap_matches_the_port(tail_gap, b, expect):
    """Decision #22: the claw tail is the start of the readout CPW, so its clearance = ``claw_tail_gap`` (−1 = the
    element's ``b``) and the claw port declares exactly that gap; the claw body keeps ``claw_spacing`` (2 µm)."""
    layout = pya.Layout()
    cell = layouts.Xmon.create(layout, junction_type="No Squid", claws=["n"], claw_tail_gap=tail_gap, b=b)
    from quantcore_circuits.layouts.registry import element_cell_ports

    ports = element_cell_ports(layouts.Xmon, cell, {"claw_tail_gap": tail_gap, "b": b})
    assert (ports["claw_n"].a, ports["claw_n"].b) == (10, expect)
    gap = region(cell, GAP)
    tip = ports["claw_n"].pos  # tail tip on the cell edge: a 10 µm conductor with `expect` µm etched on each side
    probe = pya.Region(pya.DBox(tip.x - 40, tip.y - 20, tip.x + 40, tip.y - 19).to_itype(layout.dbu))
    cut = sorted((gap & probe).each(), key=lambda q: q.bbox().left)
    inner = [q.bbox() for q in cut if abs(q.bbox().center().x) * layout.dbu < 20]
    assert len(inner) == 2 and all(abs(bb.width() * layout.dbu - expect) < 1e-6 for bb in inner), inner
    assert abs((inner[1].left - inner[0].right) * layout.dbu - 10) < 1e-6
    # the claw body clearance stays claw_spacing (2 µm) beside the claw base
    body = pya.Region(pya.DBox(-40, 177.5, 40, 178.5).to_itype(layout.dbu)) & gap  # 177–179: clearance under the base
    assert not body.is_empty()


def test_xmon_claw_ground_tail_gap_is_the_frame_gap():
    """With ``claw_ground`` the claw tail is cleared by the ground frame: the port declares ``claw_ground_gap``."""
    widths = layouts.Xmon.qcc_port_widths({"claw_ground": True, "claw_ground_gap": 15, "claw_tail_gap": 6})
    assert widths["claw_n"] == (10, 15.0)


@pytest.mark.parametrize("rounded", [False, True])
def test_bond_pad_matches_legacy(rounded):
    params = {
        "pad_width": 400,
        "pad_gap": 225,
        "pad_height": 450,
        "conn_height": 450,
        "trace_width": 10,
        "trace_gap": 6,
    }
    ref = legacy.legacy_region("Connector Pad 2", fab=True, sim=False, round=rounded, **params)
    layout = pya.Layout()
    cell = layouts.BondPad.create(
        layout, pad_width=400, pad_gap=225, pad_height=450, taper_length=450, a=10, b=6, rounded=rounded
    )
    assert_xor_empty(region(cell, GAP), ref, f"BondPad rounded={rounded}")


# chip_10a_flux_TLQubits calls xjc create_junction / create_squid(bot, top) with bot = 5 or 8 (× 0.1 µm) and
# top = 0.6 µm (squids at bot 5, junctions at 5 and 8); js = 1 with no second finger is the scripts' default
@pytest.mark.parametrize("js, second", [(1.0, 0), (5, 0.6), (8, 0.6)])
@pytest.mark.parametrize("kind, cls", [("junction", "TrilayerJunction"), ("squid", "TrilayerSquid")])
def test_trilayer_matches_legacy(tmp_path, kind, cls, js, second):
    ref = legacy.legacy_junction_layout(kind, tmp_path, js, second)
    top = [c for c in ref.top_cells() if c.name.startswith("JUNC_")][0]
    shift = pya.Trans(0, False, 0, 10000)  # legacy cell is centred on the window; KQC origin is its ground edge
    layout = pya.Layout()
    cell = getattr(layouts, cls).create(layout, finger_width=0.1 * js, second_finger_width=second)
    for legacy_layer, ours, name in (
        ((2, 0), SIS1, "straight finger"),
        ((4, 0), SIS2, "bent finger"),
        ((500, 0), HSQ, "HSQ"),
    ):
        ref_region = pya.Region(top.begin_shapes_rec(ref.layer(*legacy_layer))).transformed(shift)
        assert_xor_empty(region(cell, ours), ref_region, f"{cls} js={js} second={second} {name}")


# ---- Xmon junction options (legacy chips: junction-size sweeps, CLEARER window, junction-less reference) --------
_KEEP = []  # layouts of built cells


def _xmon(**params):
    layout = pya.Layout()
    _KEEP.append(layout)
    return layouts.Xmon.create(layout, **layouts.Xmon.qcc_params(params))


def test_xmon_forwards_junction_params():
    """``junction_params`` reach the junction cell: the Xmon's fingers = a TrilayerJunction of the same widths in the
    gap below the south arm."""
    jp = {"finger_width": 0.5, "second_finger_width": 0.6}
    cell = _xmon(junction_type="Trilayer Junction", junction_params=jp)
    ref_layout = pya.Layout()
    ref = layouts.TrilayerJunction.create(ref_layout, window_height=25, **jp)
    shift = pya.Trans(0, False, 0, int(round(-(300 / 2 + 25) / 0.001)))
    for layer, what in ((SIS1, "straight"), (SIS2, "bent"), (HSQ, "HSQ")):
        assert_xor_empty(region(cell, layer), region(ref, layer).transformed(shift), f"Xmon junction {what}")
    default = _xmon(junction_type="Trilayer Junction")
    assert not (region(default, SIS1) ^ region(cell, SIS1)).is_empty()  # the widths do change the fingers


def test_xmon_junction_params_validation_and_plan():
    params = layouts.Xmon.qcc_params({"junction_params": {"finger_width": 0.3}})
    assert params["junction_params"] == '{"finger_width": 0.3}'
    assert layouts.Xmon.qcc_params(params) == params
    with pytest.raises(ValueError, match="unknown"):
        layouts.Xmon.qcc_params({"junction_parms": {}})
    from quantcore_circuits.assembly import plan_design
    from quantcore_circuits.design import load_design

    probe = {
        "schema": "qcc/0.1",
        "name": "probe",
        "instances": {
            "Q": {
                "cell": "Xmon",
                "params": {"junction_params": {"finger_width": 0.3}, "junction_window": [30, 18]},
                "place": {"at": [0, 0]},
            }
        },
    }
    placed = plan_design(load_design(probe)).instances["Q"]
    assert "claw_n" in placed.local_ports


@pytest.mark.parametrize("window", [(30, 18), (30, 20), (30, 27)])  # chip_01, chip_01_creator/02, chip_03
def test_xmon_junction_window(window):
    """Legacy CLEARER: a w × h box centred in the junction gap is kept as metal (base_metal_addition)."""
    from kqcircuits.defaults import default_layers

    cell = _xmon(junction_window=list(window))
    add = region(cell, default_layers["1t1_base_metal_addition"])
    w, h = window
    yc = -(300 / 2 + 25) + 25 / 2
    box = pya.Region(pya.DBox(-w / 2, yc - h / 2, w / 2, yc + h / 2).to_itype(0.001))
    assert_xor_empty(add, box, f"junction window {window}")
    from quantcore_circuits.layouts.wafers.fab_export import fab_regions

    m1 = fab_regions(cell)["M1"]
    assert (m1 & box).is_empty() and not (region(_xmon(), GAP) & box).is_empty()


@pytest.mark.parametrize("window", [(30, 27, -3), (30, 45, 12.5), (30, 45, -12.5)])  # chip_03/05, chip_10a JJ/SQUID
def test_xmon_junction_window_offset(window):
    """``junction_window = [w, h, dy]``: the window centre moves dy away from the cross (legacy chip_03/05/10a
    CLEARER boxes are not centred in the gap)."""
    from kqcircuits.defaults import default_layers

    cell = _xmon(junction_window=list(window))
    w, h, dy = window
    yc = -(300 / 2 + 25) + 25 / 2 - dy
    box = pya.Region(pya.DBox(-w / 2, yc - h / 2, w / 2, yc + h / 2).to_itype(0.001))
    assert_xor_empty(region(cell, default_layers["1t1_base_metal_addition"]), box, f"junction window {window}")


def test_xmon_no_squid_lom_has_no_junction():
    from quantcore_circuits.design.schema import Instance
    from quantcore_circuits.lom.fragment import lom_model
    from quantcore_circuits.pdk import get_pdk

    def frag(jt):
        inst = Instance.model_validate({"cell": "Xmon", "params": {"junction_type": jt}, "place": {"at": [0, 0]}})
        return lom_model("Xmon")("Q3", inst, get_pdk())

    assert not [e for e in frag("No Squid").elements if e.name.startswith("J_")]
    assert [e.type for e in frag("Trilayer Junction").elements if e.name.startswith("J_")] == ["JJ"]
    assert [e.type for e in frag("Trilayer Squid").elements if e.name.startswith("J_")] == ["SQUID"]
    assert [e.type for e in frag("Manhattan").elements if e.name.startswith("J_")] == ["SQUID"]
