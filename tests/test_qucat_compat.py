"""QuCat's component value: ``values[0]`` on its main branch, ``value`` in the 1.0.3 release on PyPI (what CI and a
pip install get). The LOM reads both."""

from types import SimpleNamespace

from quantcore_circuits.lom.simulate import _qucat_value


def test_qucat_main_branch_values_list():
    assert _qucat_value(SimpleNamespace(values=[50.0], node_minus=0, node_plus=1)) == 50.0


def test_qucat_release_value_scalar():
    assert _qucat_value(SimpleNamespace(value=1e-13, node_minus=0, node_plus=1)) == 1e-13
