import pytest
from kqcircuits.pya_resolver import pya

from quantcore_circuits import layouts
from quantcore_circuits.layouts.registry import element_ports, list_components, resolve_cell


def test_registered_in_kqc_libraries():
    for cls in layouts.pcell_classes():
        lib = pya.Library.library_by_name(cls.LIBRARY_NAME)
        assert lib is not None
        from kqcircuits.util.library_helper import to_library_name

        assert to_library_name(cls.__name__) in lib.layout().pcell_names(), cls


def test_resolve_cell_names():
    assert resolve_cell("Xmon") is layouts.Xmon
    assert resolve_cell("quantcore_circuits.layouts.Xmon") is layouts.Xmon
    assert resolve_cell("Swissmon").__name__ == "Swissmon"
    assert resolve_cell("FingerCapacitorSquare").__name__ == "FingerCapacitorSquare"  # KQC library lookup
    with pytest.raises(ValueError):
        resolve_cell("NoSuchCell")
    assert "Xmon" in list_components()


def test_xmon_ports_have_corners_and_widths():
    ports = element_ports(layouts.Xmon, claws=["n", "w", "e"], flux_port=True, junction_type="No Squid")
    assert set(ports) == {"claw_n", "claw_w", "claw_e", "flux"}
    assert ports["claw_n"].pos == pya.DPoint(0, 254) and ports["claw_n"].angle == pytest.approx(90)
    assert ports["claw_w"].angle == pytest.approx(180) and ports["claw_e"].angle == pytest.approx(0)
    assert ports["flux"].angle == pytest.approx(-90)
    assert ports["claw_n"].a == 10  # claw tail width


@pytest.mark.parametrize("junction", ["Trilayer Junction", "Trilayer Squid", "Sim", "Manhattan"])
def test_xmon_accepts_kqc_and_qcc_junction_types(junction):
    layout = pya.Layout()
    cell = layouts.Xmon.create(layout, junction_type=junction)
    from quantcore_circuits.layouts.ports import check_cell

    check_cell(cell)
    names = {c.name.split("$")[0] for c in [layout.cell(i) for i in cell.called_cells()]}
    if junction.startswith("Trilayer"):
        assert any(n.startswith(junction) for n in names)


def test_sim_junction_exposes_squid_refpoints():
    ports = element_ports(layouts.Xmon, junction_type="Sim")
    assert {"squid_a", "squid_b"} <= set(ports)
    assert ports["squid_a"].pos.y > ports["squid_b"].pos.y  # island side above ground side


def test_bond_pad_port_and_edge():
    ports = element_ports(layouts.BondPad)
    assert ports["a"].pos == pya.DPoint(0, 0) and ports["a"].angle == pytest.approx(90)


def test_kqc_qubit_takes_qcc_junction():
    """Quantcore junctions are valid junction types for KQC's own qubits."""
    layout = pya.Layout()
    cell = layouts.Swissmon.create(layout, junction_type="Trilayer Junction", fluxline_type="none")
    from quantcore_circuits.layouts.ports import check_cell

    check_cell(cell)
