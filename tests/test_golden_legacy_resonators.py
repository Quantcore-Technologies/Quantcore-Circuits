"""Golden XOR tests: ported QWri resonators, transmon and coupler vs. the legacy PCells (fab mode), 1 dbu tolerance.

Parameter sets are the ones the legacy chips use (``components/python/chip_*.py``) plus defaults and variants.
"""

import contextlib
import io

import pytest
from kqcircuits.defaults import default_layers
from kqcircuits.pya_resolver import pya

from quantcore_circuits.layouts.others.couplers import PadCoupler
from quantcore_circuits.layouts.others.legacy_resonators import (
    CoupledConnector,
    CoupledResonator,
    CpwResonator,
    QubitResonator,
)
from quantcore_circuits.layouts.qubits.legacy_transmon import TwoPadTransmon
from tests.legacy_ref import legacy

pytestmark = pytest.mark.skipif(not legacy.available(), reason="legacy components/ folder not present")

GAP = default_layers["1t1_base_metal_gap_wo_grid"]
ADD = default_layers["1t1_base_metal_addition"]
PCELLS = "pymacros/QuantumPcells"
# legacy parameter → ported parameter (trace width / gap are the element's a / b)
RENAME = {"path_width": "a", "gap": "b", "n": "arc_points"}


def region(cell, info):
    return pya.Region(cell.begin_shapes_rec(cell.layout().layer(info))).merged()


def assert_xor_empty(a: pya.Region, b: pya.Region, what: str):
    diff = (a.merged() ^ b.merged()).sized(-1)  # ignore slivers up to 2 dbu
    assert diff.is_empty(), f"{what}: XOR not empty, area {diff.area()} dbu², bbox {diff.bbox()}"
    assert a.area() > 0


def legacy_gaps(rel, cls, display, params, layer=(1, 0), fab=True):
    with contextlib.redirect_stdout(io.StringIO()):  # the legacy cells print their lengths
        extra = {"fab": True} if fab else {}
        return legacy.legacy_pcell_regions(f"{PCELLS}/{rel}", cls, display, layers=(layer,), **extra, **params)[layer]


_LAYOUTS = []  # keep the layouts of the ported cells alive while their cells are used


def ours(cls, params, rename=RENAME):
    layout = pya.Layout()
    _LAYOUTS.append(layout)
    return cls.create(layout, **{rename.get(k, k): v for k, v in params.items()})


def _merge(common, *variants):
    return [{**common, **v} for v in ({},) + variants]


# chip_01 / resonator_chip_01, chip_02, chip_03, chip_05, chip_07, chip_09, chip_10a (common set + per-resonator)
COUPLED = (
    _merge(
        {"cpw_len": 5000, "clength": 300, "cgap": 2, "width": 300, "flip": False, "neck_length": 500},
        {"neck_length": 600},
        {"neck_length": 300},
    )
    + _merge(
        {"cpw_len": 4660, "clength": 300, "cgap": 2, "width": 300, "flip": False, "neck_length": 500},
        {"cpw_len": 5050},
        {"cpw_len": 4000},
    )
    + _merge(
        {
            "cpw_len": 4660,
            "gap": 10,
            "clength": 200,
            "cgap": 7,
            "width": 250,
            "flip": False,
            "neck_length": 400,
            "ground": True,
        },
        {"cpw_len": 4410, "flip": True},
        {"cpw_len": 6790, "flip": True},
    )
    + _merge(
        {
            "cpw_len": 4660,
            "gap": 10,
            "clength": 200,
            "cgap": 7,
            "width": 300,
            "flip": False,
            "neck_length": 400,
            "ground": False,
        },
        {"cpw_len": 5590, "flip": True, "clength": 400},
        {"cpw_len": 6200, "width": 400},
    )
    + _merge(
        {
            "cpw_len": 4660,
            "gap": 6,
            "clength": 300,
            "cgap": 4,
            "width": 300,
            "flip": False,
            "neck_length": 400,
            "ground": True,
        },
        {"cpw_len": 6200, "clength": 200, "neck_length": 500},
        {"cpw_len": 4740, "flip": True, "clength": 600, "cgap": 6},
    )
    + _merge(
        {
            "cpw_len": 4660,
            "gap": 6,
            "clength": 299.5,
            "cgap": 4,
            "width": 300,
            "flip": False,
            "neck_length": 150,
            "ground": True,
        },
        {"cpw_len": 4410, "cgap": 6},
    )
    + _merge(
        {
            "cpw_len": 4660,
            "gap": 6,
            "clength": 300,
            "cgap": 4,
            "width": 304,
            "flip": False,
            "neck_length": 400,
            "ground": False,
        },
        {"cpw_len": 4500, "flip": True, "ground": True},
    )
    + [{}, {"tail_end": True}, {"tail": False}, {"tail_len": 80, "flip": False}, {"clength": 200, "width": 500}]
)


@pytest.mark.parametrize("params", COUPLED, ids=[f"coupled{i}" for i in range(len(COUPLED))])
def test_coupled_resonator_matches_legacy(params):
    ref = legacy_gaps("CPW_Coupled_Resonator.lym", "CoupledResonator", "Coupled Resonator", params)
    assert_xor_empty(region(ours(CoupledResonator, params), GAP), ref, f"CoupledResonator {params}")


CPW_RES = [
    {},
    {"cpw_len": 3000, "width": 300, "arc_length": 150},
    {"tail": True},
    {"tail": True, "tail_length": 250, "neck_length": 300},
    {"tail": True, "mid_tail": True},
    {"cpw_len": 5000, "gap": 10, "path_width": 12, "cgap": 4},
]


@pytest.mark.parametrize("params", CPW_RES, ids=[f"cpwres{i}" for i in range(len(CPW_RES))])
def test_cpw_resonator_matches_legacy(params):
    ref = legacy_gaps("CPWResonator.lym", "CPWResonator", "CPW Resonator", params)
    assert_xor_empty(region(ours(CpwResonator, params), GAP), ref, f"CpwResonator {params}")


def _port_ends_drawn_cpw(cell, port_name, a, b):
    """The drawn CPW ends at the port: gaps beside the conductor 0.5 µm inside, none 0.5 µm outside, centre metal."""
    from quantcore_circuits.layouts.ports import cell_ports

    gap = region(cell, GAP)
    p = cell_ports(cell, a, b)[port_name]
    t = pya.DVector(-p.dir.y, p.dir.x)
    dbu = cell.layout().dbu

    def etched(pt):
        ip = pt.to_itype(dbu)
        return not gap.interacting(pya.Region(pya.Box(ip.x - 1, ip.y - 1, ip.x + 1, ip.y + 1))).is_empty()

    side = t * (a / 2 + b / 2)
    for d, expect in ((-0.5, True), (0.5, False)):
        q = p.pos + p.dir * d
        assert etched(q + side) is expect and etched(q - side) is expect, f"{port_name} at {d:+} µm"
        assert not etched(q), f"{port_name}: centre etched at {d:+} µm"


@pytest.mark.parametrize("params", CPW_RES, ids=[f"cpwres{i}" for i in range(len(CPW_RES))])
def test_cpw_resonator_ports_at_the_drawn_ends(params):
    """Audit issue 3: ``end`` sat a/2 + b (11 µm) past the drawn CPW, in plain ground; both ports now sit where the
    drawn gaps stop (both ends are shorted to ground when nothing is joined)."""
    a, b = params.get("path_width", 10), params.get("gap", 6)
    cell = ours(CpwResonator, params)
    for name in ("start", "end"):
        _port_ends_drawn_cpw(cell, name, a, b)


QUBIT_RES = [
    {},
    {"flip": False},
    {"ground": False},
    {"tail_end": False},
    {"coupler_flat": True},
    {"coupler_direction": True},
    {"cpw_len": 5200, "clength": 300, "cgap": 4, "width": 300, "gap": 10, "tail_conn_length": 200},
]


@pytest.mark.parametrize("params", QUBIT_RES, ids=[f"qubitres{i}" for i in range(len(QUBIT_RES))])
def test_qubit_resonator_matches_legacy(params):
    ref = legacy_gaps("Qubit_Resonator.lym", "QubitResonator", "Qubit Resonator", params)
    assert_xor_empty(region(ours(QubitResonator, params), GAP), ref, f"QubitResonator {params}")


CONNECTOR = [{}, {"ground": True}, {"flip": False}, {"cpw_len": 3000, "neck_length": 200, "width": 300}]


@pytest.mark.parametrize("params", CONNECTOR, ids=[f"connector{i}" for i in range(len(CONNECTOR))])
def test_coupled_connector_matches_legacy(params):
    ref = legacy_gaps("CoupledConnector.lym", "CoupledConnector", "Coupled Connector", params)
    assert_xor_empty(region(ours(CoupledConnector, params), GAP), ref, f"CoupledConnector {params}")


@pytest.mark.parametrize(
    "cls, rel, legacy_cls, display",
    [(TwoPadTransmon, "Transmon.lym", "Transmon", "Transmon"), (PadCoupler, "coupler.lym", "Coupler", "Coupler")],
)
@pytest.mark.parametrize("params", [{}, {"pad_thickness": 40, "pad_height": 120, "gap": 20}])
def test_two_pad_metal_matches_legacy(cls, rel, legacy_cls, display, params):
    """The legacy cells are positive drawings: their 1/0 metal is our ``base_metal_addition``."""
    ref = legacy_gaps(rel, legacy_cls, display, params, fab=False)
    cell = ours(cls, params, rename={})  # here ``gap`` is the pad gap, not a CPW gap
    assert_xor_empty(region(cell, ADD), ref, f"{cls.__name__} {params}")
    pocket = region(cell, GAP)
    assert (pocket & ref).is_empty() and pocket.area() > 0  # own pocket around (not over) the metal


def _ports(cls, **params):
    from quantcore_circuits.layouts.registry import element_ports  # pylint: disable=import-outside-toplevel

    return element_ports(cls, **params)


def test_resonator_ports():
    ports = _ports(CoupledResonator)
    assert set(ports) == {"end"} and ports["end"].dir.y == -1 and (ports["end"].a, ports["end"].b) == (10, 6)
    ports = _ports(CpwResonator, b=6, cgap=6)
    assert (ports["start"].pos.x, ports["start"].pos.y, ports["start"].angle) == (-12.0, 0.0, 180.0)
    assert ports["end"].dir is not None
    ports = _ports(CoupledConnector)
    assert ports["start"].angle == 90.0 and ports["end"].angle == -90.0
    ports = _ports(TwoPadTransmon)
    assert {n: (p.pos.x, p.angle) for n, p in ports.items() if n in ("left", "right")} == {
        "left": (-35.0, 180.0),
        "right": (35.0, 0.0),
    }
    assert {"squid_a", "squid_b"} <= set(ports) and not {"squid_a"} & set(_ports(PadCoupler))


@pytest.mark.parametrize(
    "cell", ["CoupledResonator", "CpwResonator", "QubitResonator", "CoupledConnector", "TwoPadTransmon", "PadCoupler"]
)
def test_ported_cell_plans_with_defaults(cell):
    from quantcore_circuits.assembly import plan_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

    probe = {"schema": "qcc/0.1", "name": "probe", "instances": {"X": {"cell": cell, "place": {"at": [0, 0]}}}}
    placed = plan_design(load_design(probe)).instances["X"]
    assert placed.local_ports and all(p.dir is not None for n, p in placed.local_ports.items() if "squid" not in n)
