"""3/0 keep-out hooks (design rule, 2026-11-03): "3/0 comes from the bounding box extended … we are etching out the
features built in 1/0 + a little extra so they don't get shorted".

:func:`quantcore_circuits.layouts.wafers.fab_export.keepout_region` asks each placed cell for
``cls.qcc_keepout(pcell_params) -> [pya.DBox | pya.DPolygon]`` (local frame, µm); cells without the hook get the
bbox of their etch + a margin, routes their full CPW footprint + a margin. The cells below return the **legacy 3/0
shape** their QWri PCell drew (``fab_l`` = 3/0, ``components/pymacros/QuantumPcells``), golden-tested against the
legacy code (``tests/test_keepout.py``):

=========================  ===========================================================================================
cell                       legacy 3/0
=========================  ===========================================================================================
Xmon                       the cross grown by 2·claw_base + 10 + claw_finger_width (``xmon_cross.lym``)
CoupledResonator           centre line (width a) grown by b + cgap (``CPW_Coupled_Resonator.lym``)
QubitResonator             centre line grown by 5 + b + 2 + cgap (``Qubit_Resonator.lym``)
CoupledConnector           centre line grown by 10 + b + 20 + cgap (``CoupledConnector.lym``)
CpwResonator               bbox of the CPW (+ coupling ring, start box) grown by a/2 + b + 15 in x, 35 in y
                           (``CPWResonator.lym``)
CpwSegment                 bbox of conductor + drawn ground strips grown by ``keepout_gap`` across the line
                           (legacy ``c_gap``, 0 on the chips; ``CPW.lym``)
ConnectorPad, BondPad      the 1/0 etch grown by 50 µm in x (``connector_pad.lym``, ``connector_pad_v2.lym``)
CornerMarker               the marker itself (``Marker.lym``)
JunctionTestPads,          the scripts' own 3/0 pattern (pad structure, the other pad kept in the second metal;
JunctionGroundPad          ``testPad*.py``, ``xtp_testpads_TL_small.py``)
=========================  ===========================================================================================

Metal / KQC cells and the Quantcore cells without a legacy 3/0 (TwoPadTransmon, PadCoupler: the legacy PCells draw
none) use the bbox rule — a rectangle around the etch, as the user describes for the two-pad transmons.
"""

from __future__ import annotations

from types import FunctionType, MethodType, SimpleNamespace

from kqcircuits.pya_resolver import pya

DBU = 0.001  # every quantcore layout uses 1 nm; the legacy geometry is computed in this grid


def full_params(cls, params: dict | None) -> dict:
    """Schema defaults updated with ``params`` (the hook may get a full PCell parameter set or a partial one)."""
    return {**{k: v.default for k, v in cls.get_schema().items()}, **dict(params or {})}


class _StandIn:
    """A stand-in ``self`` for a cell's geometry helpers: parameters as attributes, ``layout.dbu``, and the class's
    own attributes / methods (bound to the stand-in) for everything else."""

    def __init__(self, cls, params: dict):
        self.__dict__.update(params)
        self.layout = SimpleNamespace(dbu=DBU)
        self._cls = cls

    def __getattr__(self, name):
        value = getattr(self.__dict__["_cls"], name)
        return MethodType(value, self) if isinstance(value, FunctionType) else value


def as_cell(cls, params: dict | None) -> _StandIn:
    """A stand-in ``self`` (attributes = parameters, ``layout.dbu``) for calling a cell's geometry helpers."""
    return _StandIn(cls, full_params(cls, params))


def dpolygons(region: pya.Region, dbu: float = DBU) -> list:
    """A dbu region → µm ``DPolygon`` objects (merged)."""
    return [poly.to_dtype(dbu) for poly in region.merged().each()]
