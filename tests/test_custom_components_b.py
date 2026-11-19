"""The custom-component examples of the "build your own component" series (part B): the spiral capacitor and the
tunable resonator with a SQUID array (``examples/custom_component/``). Fast: geometry, pins, junction layers, LOM."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))

SC = "custom_component.spiral_capacitor.TwistedSpiralCapacitor"
TR = "custom_component.tunable_resonator.TunableResonator"


@pytest.fixture(scope="module", autouse=True)
def _registered():
    from custom_component.spiral_capacitor import TwistedSpiralCapacitor
    from custom_component.tunable_resonator import TunableResonator

    from quantcore_circuits import layouts

    layouts.register_pcell_classes([TwistedSpiralCapacitor, TunableResonator])


def _cell(cls, **params):
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.layouts.registry import create_cell

    layout = pya.Layout()
    return layout, create_cell(layout, cls, **params)


def test_spiral_capacitor_pins_and_geometry():
    from custom_component.spiral_capacitor import TwistedSpiralCapacitor

    from quantcore_circuits.layouts.ports import cell_ports

    layout, cell = _cell(TwistedSpiralCapacitor)
    ports = cell_ports(cell)
    assert set(ports) == {"a", "b"}
    assert ports["a"].pos.x == pytest.approx(-ports["b"].pos.x)
    assert ports["a"].dir.x == pytest.approx(-1) and ports["b"].dir.x == pytest.approx(1)
    from kqcircuits.defaults import default_layers
    from kqcircuits.pya_resolver import pya

    region = pya.Region(cell.begin_shapes_rec(layout.layer(default_layers["1t1_base_metal_gap_wo_grid"])))
    assert not region.is_empty()


def test_spiral_arms_do_not_touch():
    from custom_component.spiral_capacitor import TwistedSpiralCapacitor

    p = {k: v.default for k, v in TwistedSpiralCapacitor.get_schema().items()}
    geo = TwistedSpiralCapacitor.geometry(p)
    # the centre lines of the two arms stay at least arm_width + arm_gap apart (so the gap is at least arm_gap)
    pts_b = geo["arm_b"]
    dmin = min(math.dist(pa, pb) for pa in geo["arm_a"][::3] for pb in pts_b[::3])
    assert dmin >= 0.9 * (p["arm_width"] + p["arm_gap"])


def test_spiral_capacitor_lom_value_grows_with_turns():
    from quantcore_circuits.designer import Designer

    values = []
    for turns in (1.0, 2.0, 3.0):
        d = Designer("p2b_test_cap", box=(0, 0, 7500, 5000), live=False, verbose=False)
        pi = d.add("PAD_IN", "BondPad", at=(1125, 3600), rot=270, edge="auto")
        cap = d.add("C1", SC, at=(2600, 3600), turns=turns)
        d.route("IN", pi.a, cap.a)
        d.route("R_CAP", cap.b, Designer.free_end((4000, 3600), dir=0, term=0), meander=4000, r=50)
        d.show()
        lb = d.lom()
        values.append(lb.model.branches["C_C1"].value["estimate"])
    assert 5 < values[0] < values[1] < values[2] < 500  # fF, a rough estimate


def test_tunable_resonator_pins_and_junctions():
    from custom_component.tunable_resonator import TunableResonator
    from kqcircuits.defaults import default_layers
    from kqcircuits.pya_resolver import pya

    from quantcore_circuits.layouts.ports import cell_ports
    from quantcore_circuits.pdk import QCC_LAYERS

    layout, cell = _cell(TunableResonator, n_squids=3)
    ports = cell_ports(cell)
    assert set(ports) == {"a", "flux"}
    assert ports["a"].dir.x == pytest.approx(-1) and ports["flux"].dir.y == pytest.approx(-1)
    for name in ("1t1_SIS_junction", "1t1_SIS_junction_2"):  # the junction fingers
        assert not pya.Region(cell.begin_shapes_rec(layout.layer(default_layers[name]))).is_empty()
    assert not pya.Region(cell.begin_shapes_rec(layout.layer(QCC_LAYERS["hsq"]))).is_empty()  # the HSQ spacer
    n = sum(1 for k in cell.each_inst() if cell.layout().cell(k.cell_index).name.lower().find("squid") >= 0)
    assert n == 3


def test_equivalent_length_grows_with_inductance():
    from custom_component.tunable_resonator import equivalent_length_um

    pdk = "quantcore_nb_sapphire_v1"
    assert equivalent_length_um(0.0, 3000, 10, 6, pdk) == 0.0
    a, b = (equivalent_length_um(x, 3000, 10, 6, pdk) for x in (1.0, 3.0))
    assert 0 < a < b


def _chip(phi: float = 0.0):
    from quantcore_circuits.designer import Designer

    d = Designer("p2b_test_tune", box=(0, 0, 7500, 5000), live=False, verbose=False)
    pw = d.add("PAD_W", "BondPad", at=(1125, 1500), rot=270, edge="auto")
    pe = d.add("PAD_E", "BondPad", at=(6375, 1500), rot=90, edge="auto")
    fl = d.route("FL", pw.a, pe.a)
    tr = d.add("TR", TR, at=(3300, 2000), junction={"flux_phi0": phi})
    d.route("R_TR", tr.a, fl.hanger(near=(2800, 1500), length=500, side="left", end="open"))
    d.show()
    return d, tr


def test_tunable_resonator_frequency_falls_with_flux():
    freqs = []
    d, tr = _chip(0.0)
    for phi in (0.0, 0.15, 0.3, 0.4):
        tr.set(junction={"flux_phi0": phi})
        d.show()
        lb = d.lom(select=["PAD_W", "PAD_E", "FL", "TR", "R_TR"])
        el = lb.model.branches["TR"]
        assert el.type == "TLres" and el.value["kind"] == "lambda/4"
        freqs.append(el.value["f_GHz"])
    assert all(a > b for a, b in zip(freqs, freqs[1:]))
    assert 2.0 < freqs[0] < 9.0


def test_tunable_resonator_lom_notes_the_array():
    d, _ = _chip(0.3)
    lb = d.lom(select=["PAD_W", "PAD_E", "FL", "TR", "R_TR"])
    assert any("SQUIDs" in n and "L_array" in n for n in lb.notes)
