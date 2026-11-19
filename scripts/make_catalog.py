"""Generate ``docs/components/CATALOG.md`` (and ``MIGRATION.md``) from the live component catalog.

Run from the repo root (venv active, ``QCC_LIVE=0``)::

    python scripts/make_catalog.py                # CATALOG.md: every component, its category, source, ports, LOM
    python scripts/make_catalog.py --migration    # + MIGRATION.md: every inventory item built and checked
    python scripts/make_catalog.py --snapshots    # + build/components/<ref>.png of every Quantcore cell

Nothing is taken on trust: every entry is built through the design-plan path (as ``design.json`` instances are), its
ports are read from the built cell, the LOM model is looked up in the registry, and (``--migration``) the golden
tests are run with pytest and their results are counted per test function. The legacy file → Quantcore cell map
(:data:`LEGACY`) is the only hand-written input.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import math
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "components"
BUILD = ROOT / "build" / "components"

# ---- legacy QWri file → Quantcore port ---------------------------------------------------------------------------
# status: "ported" (cells reproduce it; golden XOR tests), "design" (a chip/design script, not a cell: rebuilt as a
# notebook by the legacy builders; the cells it calls are listed), "not migrated" (reason in REASONS).
# cells: Quantcore refs (or "fn:<module>.<function>" for a ported helper function); golden: test function names in
# tests/test_golden_legacy*.py (results counted from the pytest run).
SUPERSEDED, OBSOLETE, NOT_A_CELL, PROCESS = (
    "superseded by the PDK die frame",
    "obsolete variant",
    "not a cell",
    "different process",
)
REASONS = (SUPERSEDED, OBSOLETE, NOT_A_CELL, PROCESS)
_W = "fn:quantcore_circuits.layouts.wafers.legacy_wafer"

LEGACY: dict[str, dict] = {
    # -- Cong (Glasgow cpwe macros) --
    "pymacros/Cong/75x75_diewafer.lym": {
        "status": "ported",
        "cells": ["WaferMap75"],
        "golden": ["test_wafer_map_75"],
        "note": "75 mm wafer map: die borders + labels → 100/0 + 501/0, wafer circle → 500/0 (macro run, output path "
        "redirected)",
    },
    "pymacros/Cong/bondpad_cpwe.lym": {
        "status": "ported",
        "cells": ["CpweBondPad"],
        "golden": ["test_cpwe_bond_pad"],
        "note": "one `cpwe.b_pad` with the macro's parameters (pads on its layer 2; Quantcore etches on 1/0)",
    },
    "pymacros/Cong/bondpad_ustrip.lym": {
        "status": "not migrated",
        "reason": PROCESS,
        "note": "microstrip bond pad (`ustrip.py`: trace / dielectric / top ground plane on 1/2/3); PDK v2 "
        "(Nb CPW on sapphire) has no dielectric or ground-plane layers",
    },
    "pymacros/Cong/coupled quarter waves cpwe v1.lym": {
        "status": "ported",
        "cells": ["CpweBondPad", "CpweQuarterWaveResonator"],
        "golden": ["test_cpwe_quarter_wave", "test_cpwe_bond_pad"],
        "note": "a 5 × 5 mm design (feedline + 6 λ/4): its cells are ported with its parameters; the feedline "
        "`cpwe.line` is a qcc route",
    },
    "pymacros/Cong/Merge_gds.lym": {
        "status": "not migrated",
        "reason": NOT_A_CELL,
        "note": "GDS merge utility (qcc `write_layout` / static cells do this)",
    },
    "pymacros/Cong/Template_0.lym": {
        "status": "not migrated",
        "reason": NOT_A_CELL,
        "note": "drawing tutorial (rect, circle, triangle, text, a ustrip and a cpwe arc)",
    },
    "pymacros/Cong/Template_1.lym": {
        "status": "ported",
        "cells": ["CpweBondPad", "CpweQuarterWaveResonator"],
        "golden": ["test_cpwe_quarter_wave", "test_cpwe_bond_pad"],
        "note": "one-resonator design template: its cells are ported with its parameters",
    },
    "pymacros/Library_QWri.lym": {
        "status": "not migrated",
        "reason": NOT_A_CELL,
        "note": "registers the QWri library; Quantcore cells register through `layouts.ensure_loaded()`",
    },
    # -- QuantumPcells --
    "pymacros/QuantumPcells/Arc.lym": {"status": "ported", "cells": ["ArcPath"], "golden": ["test_arc"]},
    "pymacros/QuantumPcells/boundaryBox.lym": {
        "status": "ported",
        "cells": ["BoundaryBox"],
        "golden": ["test_boundary_box"],
        "note": "chips use the PDK die frame (100/0); kept as an optional cell",
    },
    "pymacros/QuantumPcells/connector_pad.lym": {
        "status": "ported",
        "cells": ["ConnectorPad"],
        "golden": ["test_connector_pad_v1"],
    },
    "pymacros/QuantumPcells/connector_pad_v2.lym": {
        "status": "ported",
        "cells": ["BondPad"],
        "golden": ["test_bond_pad_matches_legacy"],
    },
    "pymacros/QuantumPcells/CoupledConnector.lym": {
        "status": "ported",
        "cells": ["CoupledConnector"],
        "golden": ["test_coupled_connector_matches_legacy"],
    },
    "pymacros/QuantumPcells/CoupledConnector.py": {
        "status": "ported",
        "cells": ["CoupledConnector"],
        "golden": ["test_coupled_connector_matches_legacy"],
        "note": "same code as `CoupledConnector.lym` (identical text)",
    },
    "pymacros/QuantumPcells/coupler.lym": {
        "status": "ported",
        "cells": ["PadCoupler"],
        "golden": ["test_two_pad_metal_matches_legacy[coupler.lym]"],
    },
    "pymacros/QuantumPcells/CPW.lym": {"status": "ported", "cells": ["CpwSegment"], "golden": ["test_cpw_segment"]},
    "pymacros/QuantumPcells/CPW_Coupled_Resonator.lym": {
        "status": "ported",
        "cells": ["CoupledResonator"],
        "golden": ["test_coupled_resonator_matches_legacy"],
    },
    "pymacros/QuantumPcells/CPWResonator.lym": {
        "status": "ported",
        "cells": ["CpwResonator"],
        "golden": ["test_cpw_resonator_matches_legacy"],
    },
    "pymacros/QuantumPcells/JJ_finger.lym": {
        "status": "not migrated",
        "reason": OBSOLETE,
        "note": "first single-finger cell (layer 5/0, no window); superseded by `JJ_finger Top/Bottom` "
        "(→ JJFingerStraight / JJFingerBent)",
    },
    "pymacros/QuantumPcells/JJ_finger_bottom.lym": {
        "status": "ported",
        "cells": ["JJFingerBent"],
        "golden": ["test_jj_finger_bent"],
        "note": "also inside every trilayer junction cell",
    },
    "pymacros/QuantumPcells/JJ_finger_bottom_old.lym": {
        "status": "not migrated",
        "reason": OBSOLETE,
        "note": "earlier `JJ_finger Bottom`; superseded by JJ_finger_bottom.lym (→ JJFingerBent)",
    },
    "pymacros/QuantumPcells/JJ_finger_negative_old.lym": {
        "status": "not migrated",
        "reason": OBSOLETE,
        "note": "earlier negative finger (layer 5/0); superseded by `JJ_finger Top` (→ JJFingerStraight)",
    },
    "pymacros/QuantumPcells/JJ_finger_top.lym": {
        "status": "ported",
        "cells": ["JJFingerStraight"],
        "golden": ["test_jj_finger_straight"],
        "note": "also inside every trilayer junction cell",
    },
    "pymacros/QuantumPcells/Marker.lym": {
        "status": "ported",
        "cells": ["CornerMarker"],
        "golden": ["test_corner_marker", "test_corner_marker_hsq"],
        "note": "chips use the PDK die frame; kept as an optional cell on marker_1 (1001/0)",
    },
    "pymacros/QuantumPcells/pad.lym": {"status": "ported", "cells": ["TaperedPad"], "golden": ["test_tapered_pad"]},
    "pymacros/QuantumPcells/pcell_sample_python.lym": {
        "status": "not migrated",
        "reason": NOT_A_CELL,
        "note": "KLayout's PCell sample (circle with a radius handle); KLayout `Basic.CIRCLE` / `metal:NGon` cover it",
    },
    "pymacros/QuantumPcells/Qubit_Resonator.lym": {
        "status": "ported",
        "cells": ["QubitResonator"],
        "golden": ["test_qubit_resonator_matches_legacy"],
    },
    "pymacros/QuantumPcells/Transmon.lym": {
        "status": "ported",
        "cells": ["TwoPadTransmon"],
        "golden": ["test_two_pad_metal_matches_legacy[Transmon.lym]"],
    },
    "pymacros/QuantumPcells/xmon_cross.lym": {
        "status": "ported",
        "cells": ["Xmon"],
        "golden": ["test_xmon_matches_legacy"],
    },
    "pymacros/QuantumPcells/xmon_handle.lym": {
        "status": "ported",
        "cells": ["Xmon"],
        "golden": ["test_xmon_matches_legacy"],
        "note": "the claws of `Xmon Cross` (Xmon `claws`)",
    },
    "pymacros/QuantumPcells/__init__.py": {"status": "not migrated", "reason": NOT_A_CELL, "note": "empty file"},
    "pymacros/spiral.lym": {"status": "ported", "cells": ["SpiralPath"], "golden": ["test_spiral"]},
    # -- python: chips and designs --
    "python/box_outline.py": {
        "status": "not migrated",
        "reason": SUPERSEDED,
        "note": "7.5 mm chip outline and four 500 µm corner pads on 10/0",
    },
    "python/chip_01.py": {
        "status": "design",
        "chip": "chip_01",
        "cells": ["ConnectorPad", "CpwSegment", "CoupledResonator", "CornerMarker", "Xmon", "TextLabel"],
    },
    "python/chip_01_4x4.py": {"status": "design", "chip": "chip_01", "note": "4 × 4 array of chip_01 dies"},
    "python/chip_01_creator.py": {
        "status": "design",
        "chip": "chip_01",
        "cells": [
            "ConnectorPad",
            "CpwSegment",
            "CoupledResonator",
            "CornerMarker",
            "Xmon",
            "JunctionGroundPad",
            "JunctionTestPads",
            "TextLabel",
        ],
        "note": "imports `junction_creator` (not in components/: closest ports SquidV0 / TrilayerJunction)",
    },
    "python/chip_02_creator.py": {
        "status": "design",
        "chip": ["chip_02_creator", "chip_02"],
        "cells": [
            "ConnectorPad",
            "CpwSegment",
            "CoupledResonator",
            "CornerMarker",
            "Xmon",
            "JunctionGroundPad",
            "JunctionTestPads",
            "TextLabel",
        ],
        "note": "imports `junction_creator` (not in components/)",
    },
    "python/chip_03_trilayer.py": {
        "status": "design",
        "chip": "chip_03_trilayer",
        "cells": [
            "ConnectorPad",
            "CpwSegment",
            "CoupledResonator",
            "CornerMarker",
            "Xmon",
            "FluxHoleArray",
            "TextLabel",
        ],
        "note": "its `flux_holes()` → FluxHoleArray; `jc.create_junction(bot, top)` from the missing "
        "`junction_creator`",
    },
    "python/chip_04_test_chip_TL.py": {
        "status": "design",
        "chip": "chip_04_test_chip_TL",
        "cells": ["CornerMarker", "JunctionTestPads", "TextLabel"],
    },
    "python/chip_05_flux_TLQubits.py": {
        "status": "design",
        "chip": "chip_05_flux_TLQubits",
        "cells": [
            "ConnectorPad",
            "CpwSegment",
            "CoupledResonator",
            "CornerMarker",
            "Xmon",
            "FluxHoleArray",
            "TrilayerJunctionHSQ",
            "TrilayerSquidHSQ",
            "JunctionTestPads",
            "TextLabel",
        ],
    },
    "python/chip_06_test_cyro_TLQ.py": {
        "status": "design",
        "chip": "chip_06_test_cyro_TLQ",
        "cells": ["CornerMarker", "JunctionTestPads", "TextLabel"],
    },
    "python/chip_07_resonators.py": {
        "status": "design",
        "chip": "chip_07_resonators",
        "cells": ["BondPad", "CpwSegment", "CoupledResonator", "CornerMarker", "FluxHoleArray", "TextLabel"],
    },
    "python/chip_08_TL_HSQ_testpads.py": {
        "status": "design",
        "chip": "chip_08_TL_HSQ_testpads",
        "cells": ["CornerMarker", "JunctionTestPads", "TextLabel"],
    },
    "python/chip_09_resonatorsExpt.py": {
        "status": "design",
        "chip": "chip_09_resonatorsExpt",
        "cells": ["BondPad", "CoupledResonator", "CornerMarker", "FluxHoleArray", "TextLabel"],
    },
    "python/chip_09_resonatorsExpt_sim.py": {
        "status": "design",
        "chip": "chip_09_resonatorsExpt_sim",
        "cells": ["BondPad", "CoupledResonator", "FluxHoleArray"],
    },
    "python/chip_10a_3X_SQUID.py": {
        "status": "design",
        "chip": "chip_10a_3X_SQUID",
        "cells": ["JJFingerStraight"],
        "note": "unfinished script: `create_squid` writes two positive straight fingers (cell `top_finger`, "
        "= JJFingerStraight(negative=False)) and an empty `JUNC_<js>` cell; the rest is commented out",
    },
    "python/chip_10a_flux_TLQubits.py": {
        "status": "design",
        "chip": "chip_10a_flux_TLQubits",
        "cells": [
            "BondPad",
            "ConnectorPad",
            "CpwSegment",
            "CoupledResonator",
            "CornerMarker",
            "Xmon",
            "TrilayerJunction",
            "TrilayerSquid",
            "JunctionTestPads",
            "TextLabel",
        ],
    },
    "python/chip_11f_JJplacer.py": {
        "status": "design",
        "chip": "chip_11f_JJplacer",
        "cells": ["TrilayerJunctionCompact"],
        "note": "places chip_11m's `JX_500` at the coordinates of a CSV that is not in components/",
    },
    "python/chip_11m_TestJJ16x_pads.py": {
        "status": "ported",
        "chip": "chip_11m_TestJJ16x_pads",
        "cells": ["TrilayerJunctionCompact"],
        "golden": ["test_trilayer_junction_compact"],
        "note": "`create_testPad(size, secondFinger)` → cell `JX_500` (its pads are commented out in the script)",
    },
    "python/chip_maker.py": {
        "status": "not migrated",
        "reason": NOT_A_CELL,
        "note": "batch driver calling `chip_01_creator.create_chip` per junction size",
    },
    "python/chip_xxx_template.py": {
        "status": "not migrated",
        "reason": NOT_A_CELL,
        "note": "empty chip template (markers + test-pad call)",
    },
    "python/resonator_chip_01.py": {
        "status": "design",
        "chip": "resonator_chip_01",
        "cells": ["ConnectorPad", "CpwSegment", "CoupledResonator", "CornerMarker", "TextLabel"],
    },
    # -- python: drawing libraries and helpers --
    "python/cpwe.py": {
        "status": "ported",
        "cells": [
            "CpweBondPad",
            "CpweQuarterWaveResonator",
            "CpweFingerCapacitor",
            "CpweGapCapacitor",
            "CpweFingerLine",
            "CpweTaper",
            "CpweOpenEnd",
            "CpweMeanderLine",
        ],
        "golden": ["test_cpwe_bond_pad", "test_cpwe_quarter_wave", "test_cpwe_cells", "test_cpwe_quarter_wave_lead"],
        "note": "`line`/`arc` → qcc routes, `tpiece` → WaveguideCoplanarSplitter, `quarter_wave` → CpweMeanderLine "
        "`lead`; `tl_L_term` not ported (no legacy caller)",
    },
    "python/die_creator.py": {
        "status": "ported",
        "cells": ["EbeamMarker", f"{_W}.die_chip_offsets"],
        "golden": ["test_ebeam_marker", "test_die_and_wafer_positions"],
        "note": "die outline and markers superseded by the PDK die frame; the e-beam marker and the 2 × 2 chip "
        "offsets are ported",
    },
    "python/draw.py": {
        "status": "ported",
        "cells": ["CrossMarker", "GlobalMarker", "DicingMarker", "AlignmentMarkers"],
        "golden": ["test_draw_markers"],
        "note": "markers kept as optional cells (chips use the PDK die frame); `exp_pts` in layouts/others/cpwe.py; "
        "`make_cell`/`rect`/`text`/`boolean`/... are drawing utilities (not cells); `spiral` (broken: undefined "
        "`y1s`) → SpiralPath",
    },
    "python/flux_holes.py": {
        "status": "ported",
        "cells": ["FluxHoleArray"],
        "golden": ["test_flux_holes_like_chip_07", "test_flux_holes_script"],
    },
    "python/importing_multiple_cells.py": {
        "status": "not migrated",
        "reason": NOT_A_CELL,
        "note": "GDS import utility",
    },
    "python/junction_creator_HSQ.py": {
        "status": "ported",
        "cells": ["TrilayerJunctionHSQ"],
        "golden": ["test_trilayer_junction_hsq"],
    },
    "python/junction_creator_old.py": {
        "status": "not migrated",
        "reason": OBSOLETE,
        "note": "class version of `junction_creator_sq` with a 16 µm bent window (its methods use `__init__` "
        "locals: NameError); the geometry is SquidV0(bent_window_height=16), see `junction_pad.py`",
    },
    "python/junction_creator_sq.py": {
        "status": "ported",
        "cells": ["SquidV0"],
        "golden": ["test_squid_v0_junction_creator_sq"],
    },
    "python/junction_pad.py": {"status": "ported", "cells": ["SquidV0"], "golden": ["test_squid_v0_junction_pad"]},
    "python/layout_reader.py": {"status": "not migrated", "reason": NOT_A_CELL, "note": "GDS reader script"},
    "python/PCell_insert_template.py": {
        "status": "not migrated",
        "reason": NOT_A_CELL,
        "note": "PCell insertion template",
    },
    "python/PCell_inserter.py": {
        "status": "not migrated",
        "reason": NOT_A_CELL,
        "note": "`Insert` helper class for QWri PCells (Designer.add does this)",
    },
    "python/play_fluxLine.py": {
        "status": "not migrated",
        "reason": NOT_A_CELL,
        "note": "scratch script: one rounded 10 µm path (a qcc route / FluxlineStandard)",
    },
    "python/PyMacro_basic_template.py": {"status": "not migrated", "reason": NOT_A_CELL, "note": "macro template"},
    "python/squid_creator_HSQ.py": {
        "status": "ported",
        "cells": ["TrilayerSquidHSQ"],
        "golden": ["test_trilayer_squid_hsq", "test_spacer_gradient_rings[TrilayerSquidHSQ]"],
        "note": "HSQ → 50/0; the shade layers it declares (52–54/0) are empty there; the PDK v2 gradient "
        "(51–53/0) is the `spacer_gradient` option",
    },
    "python/testPad.py": {
        "status": "ported",
        "cells": ["JunctionGroundPad"],
        "golden": ["test_junction_ground_pad"],
    },
    "python/testPad_AVAQUS.py": {
        "status": "ported",
        "cells": ["JunctionTestPads"],
        "golden": ["test_junction_test_pads[testPad_AVAQUS]"],
    },
    "python/testPad_Nb_TL.py": {
        "status": "ported",
        "cells": ["JunctionTestPads"],
        "golden": ["test_junction_test_pads[testPad_Nb_TL.py]"],
    },
    "python/testPad_Nb_TL_HSQ.py": {
        "status": "ported",
        "cells": ["JunctionTestPads"],
        "golden": ["test_junction_test_pads[testPad_Nb_TL_HSQ]"],
    },
    "python/ustrip.py": {
        "status": "not migrated",
        "reason": PROCESS,
        "note": "microstrip drawing library (trace / dielectric / top ground plane); PDK v2 has no dielectric or "
        "ground-plane layers (Design decision: port only with a layer assignment)",
    },
    "python/wafer_creator.py": {
        "status": "ported",
        "cells": [f"{_W}.wafer_01_die_positions"],
        "golden": ["test_die_and_wafer_positions"],
        "note": "die / resonator positions of wafer_01 (the wafer layout itself is a fab mask, `wafers/fab_export`)",
    },
    "python/xjc_junction_TL_mod.py": {
        "status": "ported",
        "cells": ["TrilayerJunction"],
        "golden": ["test_trilayer_matches_legacy[junction]"],
    },
    "python/xjc_junction_TL_mod_v0.1.py": {
        "status": "ported",
        "cells": ["TrilayerJunctionHSQ"],
        "golden": ["test_xjc_v01_is_the_hsq_generation[xjc_junction]"],
        "note": "earlier version = TrilayerJunctionHSQ(hsq_extra=0.2)",
    },
    "python/xjc_squid_TL_mod.py": {
        "status": "ported",
        "cells": ["TrilayerSquid"],
        "golden": ["test_trilayer_matches_legacy[squid]"],
    },
    "python/xjc_squid_TL_mod_v0.1.py": {
        "status": "ported",
        "cells": ["TrilayerSquidHSQ"],
        "golden": ["test_xjc_v01_is_the_hsq_generation[xjc_squid]"],
        "note": "earlier version = TrilayerSquidHSQ(hsq_extra=0.2)",
    },
    "python/xtp_testpads_TL_small.py": {
        "status": "ported",
        "cells": ["JunctionTestPads"],
        "golden": ["test_junction_test_pads[xtp_testpads]"],
    },
}

# the two legacy design notebooks (components/python/*.ipynb; Quantum Metal designs): components they use
LEGACY_NOTEBOOKS = {
    "12.0 Coupled_chip_layout.ipynb": {
        "chip": ["d12_coupled_chip"],
        "cells": [
            "metal:TransmonCrossFL",
            "metal:TransmonPocketCL",
            "metal:TransmonCross",
            "metal:LaunchpadWirebondDriven",
            "metal:LaunchpadWirebondCoupled",
            "metal:OpenToGround",
            "metal:ShortToGround",
        ],
        "note": "Metal routes (RouteMeander / RoutePathfinder / RouteStraight / anchored paths) → qcc routes",
    },
    "14.0 Two_feedline_resonator_chip.ipynb": {
        "chip": ["d14_two_feedline_resonator"],
        "cells": [
            "metal:TransmonCross",
            "metal:LaunchpadWirebondDriven",
            "metal:OpenToGround",
            "metal:ShortToGround",
            "FluxHoles",
        ],
        "note": "its own `FluxHoles` QComponent → Quantcore `FluxHoles`; Metal routes → qcc routes",
    },
}

# routing-port rule of tests/test_catalog_contract.py (kept in sync by hand; a script does not import tests)
NON_ROUTING_CATEGORIES = {"junction", "chip"}
NON_ROUTING_PORT_PREFIXES = ("common", "squid", "junction_")
GOLDEN_FILES = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_golden_legacy*.py"))
METAL_PORT_TEST = "test_component_builds_with_expected_ports"  # tests/test_metal_components.py


# ---- checks --------------------------------------------------------------------------------------------------
def _plan(ref: str):
    from quantcore_circuits.assembly import plan_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

    probe = {"schema": "qcc/0.1", "name": "catalog_probe", "instances": {"X": {"cell": ref, "place": {"at": [0, 0]}}}}
    return plan_design(load_design(probe)).instances["X"]


def _lom(ref: str) -> bool | None:
    try:
        import quantcore_circuits.lom  # noqa: F401  pylint: disable=import-outside-toplevel,unused-import
        from quantcore_circuits.lom.fragment import lom_model  # pylint: disable=import-outside-toplevel

        return lom_model(ref) is not None
    except Exception:  # noqa: BLE001  pylint: disable=broad-except
        return None


def check(ref: str, category: str, notes: dict) -> dict:
    """Build ``ref`` as a design instance; ports, routing-port problems, LOM."""
    out = {"ref": ref, "builds": False, "ports": [], "undirected": [], "problems": [], "error": "", "seconds": 0.0}
    t0 = time.perf_counter()
    try:
        placed = _plan(ref)
        out["builds"] = True
        for name, port in sorted(placed.local_ports.items()):
            out["ports"].append(name)
            pos = port.pos
            if pos is None or not (math.isfinite(pos.x) and math.isfinite(pos.y)):
                out["problems"].append(f"{name}: no finite position")
            routing = category not in NON_ROUTING_CATEGORIES and not name.startswith(NON_ROUTING_PORT_PREFIXES)
            if routing and port.dir is None:
                out["undirected"].append(name)
    except Exception as e:  # noqa: BLE001  pylint: disable=broad-except
        out["error"] = f"{type(e).__name__}: {e}".replace("\n", " ")[:240]
    out["seconds"] = round(time.perf_counter() - t0, 2)
    out["lom"] = _lom(ref)
    out["documented"] = ref in notes
    return out


def ports_ok(rec: dict) -> str:
    if not rec["builds"]:
        return "—"
    if rec["problems"]:
        return "no: " + "; ".join(rec["problems"])
    if rec["undirected"]:
        names = ", ".join(rec["undirected"])
        return f"yes (undirected, documented: {names})" if rec["documented"] else f"no: undirected {names}"
    return "yes"


def _yes(v) -> str:
    return {True: "yes", False: "no", None: "?"}[v]


def _esc(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def run_golden(paths: list[str]) -> dict[str, str]:
    """Run pytest on ``paths``; ``{test id "func[params]": "passed" | "failed" | "skipped"}``."""
    BUILD.mkdir(parents=True, exist_ok=True)
    xml = BUILD / "golden.xml"
    env = {**os.environ, "QCC_LIVE": "0", "BROWSER": "qcc-no-browser", "MPLBACKEND": "Agg"}
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml}", *paths]
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    (BUILD / "golden.log").write_text(proc.stdout[-20000:] + proc.stderr[-5000:], encoding="utf-8")
    return parse_junit(xml)


def parse_junit(xml: Path) -> dict[str, str]:
    """``{test id: outcome}`` from a pytest JUnit XML file."""
    cases: dict[str, str] = {}
    for case in ET.parse(xml).getroot().iter("testcase"):
        name = case.get("name", "")
        if case.find("failure") is not None or case.find("error") is not None:
            cases[name] = "failed"
        elif case.find("skipped") is not None:
            cases[name] = "skipped"
        else:
            cases[name] = "passed"
    return cases


def tally(cases: dict[str, str], spec: str) -> list[int]:
    """[passed, failed, skipped] of the test function ``spec`` (``"test_x"``), or of its parametrisations whose id
    contains ``sub`` (``"test_x[sub]"``)."""
    name, _, sub = spec.partition("[")
    sub = sub.rstrip("]")
    out = [0, 0, 0]
    for case, outcome in cases.items():
        func, _, params = case.partition("[")
        if func == name and (not sub or sub in params):
            out[("passed", "failed", "skipped").index(outcome)] += 1
    return out


def _golden_cell(names: list[str], cases: dict) -> str:
    parts = []
    for n in names:
        p, f, s = tally(cases, n)
        if p + f + s == 0:
            parts.append(f"`{n}` (not found)")
        else:
            parts.append(f"`{n}` {p}/{p + f + s}" + (" FAILED" if f else "") + (f" ({s} skipped)" if s else ""))
    return ", ".join(parts) or "—"


# ---- CATALOG.md ----------------------------------------------------------------------------------------------
def legacy_origins() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path, spec in LEGACY.items():
        if spec["status"] != "ported":
            continue
        for ref in spec.get("cells", []):
            out.setdefault(ref, []).append(Path(path).name)
    return out


def make_catalog(checks: dict[str, dict]) -> str:
    from quantcore_circuits.layouts.catalog import CATEGORIES, NOTES, catalog  # pylint: disable=C0415

    entries = catalog(chips=True, routes=True)
    origins = legacy_origins()
    today = _dt.date.today().isoformat()
    cells = [c for c in entries if c.cell and c.category != "chip"]
    chips = [c for c in entries if c.category == "chip"]
    routes = [c for c in entries if not c.cell]
    by_src = {s: sum(1 for c in cells if c.source == s) for s in ("quantcore", "kqc", "metal")}
    n_lom = sum(1 for c in cells if checks.get(c.ref, {}).get("lom"))
    lines = [
        "# Component catalog",
        "",
        f"Generated by `python scripts/make_catalog.py` on {today} from `quantcore_circuits.layouts.catalog.catalog()`."
        " Do not edit by hand.",
        "",
        f"**{len(cells)} components** usable as a `design.json` `cell` ({by_src['quantcore']} Quantcore, "
        f"{by_src['kqc']} KQCircuits, {by_src['metal']} Quantum Metal), {n_lom} with a LOM model; plus "
        f"{len(chips)} whole chips (reference cells) and {len(routes)} Metal routes (not cells: use a qcc route).",
        "",
        "* **ref** goes into `design.json` `cell` / `Designer.add(name, ref, ...)`; `metal:<Class>` takes the Metal "
        "options as params.",
        "* **ports**: the ports of a default instance, read from the cell built through the design-plan path "
        "(`qcc components <ref>` prints positions, directions and CPW widths). A port marked † has no direction "
        "(cannot be snapped to; see the note).",
        "* **LOM**: a lumped model is registered (`quantcore_circuits.lom.fragment.lom_model(ref)`).",
        "* **origin**: the legacy QWri file a Quantcore cell reproduces (golden XOR tests in "
        "`tests/test_golden_legacy*.py`; full map in `MIGRATION.md`).",
        "",
        "## Summary",
        "",
        "| category | Quantcore | KQC | Metal | with LOM |",
        "|---|---|---|---|---|",
    ]
    for cat in CATEGORIES:
        group = [c for c in cells if c.category == cat]
        if not group:
            continue
        counts = [sum(1 for c in group if c.source == s) for s in ("quantcore", "kqc", "metal")]
        lom = sum(1 for c in group if checks.get(c.ref, {}).get("lom"))
        lines.append(f"| {cat} | {counts[0]} | {counts[1]} | {counts[2]} | {lom} / {len(group)} |")
    for cat in CATEGORIES:
        group = [c for c in cells if c.category == cat]
        if not group:
            continue
        lines += [
            "",
            f"## {cat}",
            "",
            "| name | ref | source | ports | LOM | origin / notes |",
            "|---|---|---|---|---|---|",
        ]
        for c in group:
            rec = checks.get(c.ref, {})
            if rec.get("builds"):
                ports = ", ".join(f"{p}†" if p in rec["undirected"] else p for p in rec["ports"]) or "(none)"
            else:
                ports = f"BUILD FAILED: {rec.get('error', '?')}" if rec else "?"
            notes = []
            if c.ref in origins:
                notes.append("legacy " + ", ".join(f"`{o}`" for o in sorted(set(origins[c.ref]))))
            notes.append(_esc(NOTES[c.ref]) if c.ref in NOTES else _esc(c.note or c.description)[:160])
            lom = _yes(rec.get("lom")) if rec else "?"
            lines.append(
                f"| {c.name} | `{c.ref}` | {c.source} | {_esc(ports)} | {lom} | {'; '.join(n for n in notes if n)} |"
            )
    lines += [
        "",
        "## Whole chips (reference cells, category `chip`)",
        "",
        "| name | ref | source | description |",
        "|---|---|---|---|",
    ]
    lines += [f"| {c.name} | `{c.ref}` | {c.source} | {_esc(c.description)[:120]} |" for c in chips]
    lines += ["", "## Metal routes (not cells)", "", "| name | use instead |", "|---|---|"]
    lines += [f"| {c.name} | {_esc(c.note)} |" for c in routes]
    return "\n".join(lines) + "\n"


# ---- MIGRATION.md --------------------------------------------------------------------------------------------
# docs/components/AUDIT.md gap list → state after the components agent's fixes (second instance, 2026-11-03)
AUDIT_GAPS = [
    (
        "1",
        "Metal pins whose own etch runs past the pin (d12 9/9, d14 6/6 routes cut)",
        "closed",
        "wrapper trims the etch beyond each conductor-ending pin within the pin width (`open_pins` keeps it); "
        "`test_pins_are_not_etched_beyond_the_pin` (42 cells), `test_metal_claw_and_route_are_one_conductor`; "
        "`open_conductor` DRC clean on all example designs",
    ),
    (
        "2",
        "Xmon claw-tail `b` declared 6, drawn `claw_spacing`",
        "documented",
        "kept b = element b so routes without a/b stay the chip CPW (a gap step at the port); catalog note; "
        "design decision",
    ),
    (
        "3",
        "CpwResonator `end` 11 µm past the drawn CPW",
        "closed",
        "port at the drawn gap end; `test_cpw_resonator_ports_at_the_drawn_ends`",
    ),
    (
        "4",
        "KQC port widths (taper b, AirbridgeConnection b, FluxlineStraight flux, QuarterWaveCpwResonator "
        "resonator_b, Swissmon cplr*, circular/concentric transmon couplers)",
        "closed",
        "`registry.KQC_PORT_WIDTHS`; `test_declared_port_widths_match_the_drawing`",
    ),
    (
        "5",
        "metal:TransmonConcentricType2 / TunableCoupler02 / ResonatorLumped empty at defaults",
        "documented",
        "Metal itself adds no pocket (metal only); catalog note with the pocket recipe; "
        "`test_metal_only_cells_are_documented_and_draw_metal_only`, `test_metal_only_cell_on_a_rectangle_pocket`",
    ),
    ("6", "legacy 3/0 not reproduced", "design decision", "lead / PDK (`m3_margin_um`)"),
    (
        "7",
        "`qcc mask` drops airbridge / SIS_shadow / flip-chip / TSV layers silently",
        "closed (warning); layers: design decision",
        "`fab_export.dropped_layers`, `FabLayersDropped` warning + `report`; "
        "`test_export_fab_warns_about_dropped_layers`",
    ),
    ("8", "Metal / KQC junctions are 2/0 footprints, not trilayer", "design decision", "lead"),
    ("9", "`junction_creator` missing (chips 01–03)", "design decision", "lead"),
    (
        "10",
        "trilayer golden tests only at js = 1",
        "closed",
        "js/second (1, 0), (5, 0.6), (8, 0.6); found and fixed the missing finger coerce in TrilayerJunction / "
        "TrilayerSquid; `test_xmon_junction_size_sweep` (chip_05 / chip_10a sweeps through Xmon `junction_params`)",
    ),
    (
        "11",
        "metal:NSquareSpiral (pin, no model, empty) / metal:Airbridge (dropped layer)",
        "documented",
        "catalog note (metal only); the airbridge layer is reported by gap 7's warning",
    ),
    (
        "12",
        "docs: Xmon / BondPad origins, resonator open ends, TwoPadTransmon junction",
        "closed",
        "docstrings and catalog notes",
    ),
]


def make_migration(checks: dict[str, dict], golden: dict[str, list[int]]) -> str:
    from quantcore_circuits.layouts.catalog import NOTES, catalog, find  # pylint: disable=C0415

    inventory = json.loads((DOCS / "inventory.json").read_text(encoding="utf-8"))
    today = _dt.date.today().isoformat()
    kqc, metal, legacy = inventory["kqc"], inventory["metal"], inventory["legacy"]
    q_cells = [c for c in catalog(source="quantcore", chips=True)]
    lines = [
        "# Component migration",
        "",
        f"Generated by `python scripts/make_catalog.py --migration` on {today}. Do not edit by hand: the checks are "
        "re-run each time. Every inventory item (`docs/components/inventory.json`: "
        f"{len(kqc)} KQC, {len(metal)} Metal, {len(legacy)} legacy files) is built as a `design.json` instance "
        "(`plan_design` of a one-instance probe, default parameters):",
        "",
        "* **builds**: the probe plans and the cell builds (KLayout error cells raise);",
        "* **ports**: every port has a finite position and every routing port a direction (junction and chip "
        "categories and `common`/`squid*`/`junction_*` ports exempt, as in `tests/test_catalog_contract.py`); "
        "documented exceptions are named;",
        "* **LOM**: `lom_model(ref)` is registered (electrical categories need one);",
        "* **golden**: legacy XOR tests (`tests/test_golden_legacy*.py`) run now, passed / run per test function; "
        "for Metal the port test of `tests/test_metal_components.py`.",
        "",
        "Evidence: the pytest log of this run is `build/components/golden.log` (JUnit XML `golden.xml`); the per-ref "
        "checks are in `build/components/checks.json`.",
    ]

    def row(item_ref, category):
        rec = checks[item_ref]
        build = "yes" if rec["builds"] else f"NO: {_esc(rec['error'])}"
        return rec, build

    # summary numbers
    def count(refs_cats):
        recs = [checks[r] for r, _ in refs_cats if r in checks]
        built = sum(1 for r in recs if r["builds"])
        ok = sum(1 for r in recs if ports_ok(r).startswith("yes"))
        lom = sum(1 for r in recs if r.get("lom"))
        return len(recs), built, ok, lom

    kqc_rc = [(e["ref"], e["category"]) for e in kqc]
    metal_cells = [(e["ref"], e["category"]) for e in metal if e["ref"] in checks]
    statuses = {}
    for spec in LEGACY.values():
        key = spec["status"] if spec["status"] != "not migrated" else f"not migrated: {spec['reason']}"
        statuses[key] = statuses.get(key, 0) + 1
    lines += ["", "## Summary", "", "| group | items | builds | ports OK | LOM model |", "|---|---|---|---|---|"]
    for label, rc in (
        ("KQC", kqc_rc),
        ("Metal (cells)", metal_cells),
        ("Quantcore cells", [(c.ref, c.category) for c in q_cells]),
    ):
        n, b, ok, lom = count(rc)
        lines.append(f"| {label} | {n} | {b} | {ok} | {lom} |")
    n_routes = len(metal) - len(metal_cells)
    lines += [
        "",
        f"Metal: {n_routes} more inventory entries are routes (not cells; mapped to qcc routes).",
        "",
        "Legacy files: " + ", ".join(f"{v} {k}" for k, v in sorted(statuses.items())) + f" (of {len(LEGACY)}).",
    ]
    g_total = [sum(1 for v in golden.values() if v == k) for k in ("passed", "failed", "skipped")]
    lines.append(
        f"Golden / port tests run: {g_total[0]} passed, {g_total[1]} failed, {g_total[2]} skipped "
        f"({', '.join(GOLDEN_FILES)}, tests/test_metal_components.py)."
    )

    lines += [
        "",
        "## Audit gaps (`docs/components/AUDIT.md`)",
        "",
        "State of the independent audit's gap list after the components fixes. Also added since the audit: the "
        "lumped-port refpoints `lumped_signal` / `lumped_ground` on ConnectorPad, CpweBondPad and the Metal launch "
        "pads (as BondPad), and the Xmon `junction_window` offset for the legacy CLEARER boxes.",
        "",
        "| # | gap | state | evidence |",
        "|---|---|---|---|",
    ]
    lines += [f"| {n} | {_esc(gap)} | {state} | {_esc(ev)} |" for n, gap, state, ev in AUDIT_GAPS]

    # KQC
    lines += [
        "",
        f"## KQCircuits ({len(kqc)})",
        "",
        "| ref | category | builds | ports OK | LOM | golden | notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in kqc:
        rec, build = row(e["ref"], e["category"])
        note = NOTES.get(e["ref"], "")
        cat = find(e["ref"]).category if find(e["ref"]) else e["category"]
        lines.append(
            f"| `{e['ref']}` | {cat} | {build} | {_esc(ports_ok(rec))} | {_yes(rec.get('lom'))} | upstream | "
            f"{_esc(note)} |"
        )

    # Metal
    from quantcore_circuits.layouts.metal import ROUTE_MAPPING  # pylint: disable=import-outside-toplevel

    metal_tested = _metal_port_cases()
    lines += [
        "",
        f"## Quantum Metal ({len(metal)})",
        "",
        "| ref | category | builds | ports OK | LOM | golden | notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in metal:
        if e["ref"] in checks:
            rec, build = row(e["ref"], e["category"])
            g = metal_tested.get(e["name"])
            if g is not None:
                p, f, s = tally(golden, f"{METAL_PORT_TEST}[{g}]")
                gtxt = f"`{METAL_PORT_TEST}[{g}]` " + ("FAILED" if f else "passed" if p else "not run")
            else:
                gtxt = "build only"
            lines.append(
                f"| `{e['ref']}` | {e['category']} | {build} | {_esc(ports_ok(rec))} | {_yes(rec.get('lom'))} | "
                f"{gtxt} | |"
            )
        else:
            mapped = ROUTE_MAPPING.get(e["name"], "route")
            lines.append(f"| `{e['ref']}` | route | not a cell | — | — | — | Metal route → qcc `{mapped}` |")

    # Legacy
    lines += [
        "",
        f"## Legacy QWri ({len(legacy)} files)",
        "",
        "| file | status | Quantcore ref(s) | builds | ports OK | LOM | golden | notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    not_migrated = []
    inv_files = [e["file"].replace("\\", "/").removeprefix("components/") for e in legacy]
    missing = sorted(set(inv_files) - set(LEGACY))
    for path in inv_files:
        spec = LEGACY.get(path)
        if spec is None:
            lines.append(f"| `{path}` | UNMAPPED | | | | | | add it to scripts/make_catalog.py LEGACY |")
            continue
        status = spec["status"]
        cells = [c for c in spec.get("cells", []) if not c.startswith("fn:")]
        fns = [c[3:] for c in spec.get("cells", []) if c.startswith("fn:")]
        recs = [checks[c] for c in cells if c in checks]
        if status == "not migrated":
            not_migrated.append((path, spec["reason"], spec.get("note", "")))
            lines.append(
                f"| `{path}` | not migrated: {spec['reason']} | — | — | — | — | — | {_esc(spec.get('note', ''))} |"
            )
            continue
        builds = f"{sum(r['builds'] for r in recs)}/{len(recs)}" if recs else "—"
        fn_ok = [_fn_ok(f) for f in fns]
        if fns:
            builds += f"; fn {sum(fn_ok)}/{len(fns)}"
        ok = f"{sum(ports_ok(r).startswith('yes') for r in recs)}/{len(recs)}" if recs else "—"
        lom_cells = [r for r in recs if _electrical(r["ref"])]
        lom = f"{sum(bool(r.get('lom')) for r in lom_cells)}/{len(lom_cells)}" if lom_cells else "n/a"
        refs = (
            ", ".join(f"`{c}`" for c in cells)
            + (", " if cells and fns else "")
            + ", ".join(f"`{f.rsplit('.', 1)[-1]}()`" for f in fns)
        )
        note = spec.get("note", "")
        if status == "design":
            nb = _design_artifacts(spec.get("chip", ""))
            note = (note + "; " if note else "") + (f"rebuilt: {nb}" if nb else "notebook: legacy builders")
            gold = "—"
        else:
            gold = _golden_cell(spec.get("golden", []), golden)
        lines.append(f"| `{path}` | {status} | {refs or '—'} | {builds} | {ok} | {lom} | {gold} | {_esc(note)} |")
    if missing:
        lines.append(f"\nMap entries without an inventory file: {missing}")

    # legacy design notebooks
    lines += [
        "",
        "## Legacy design notebooks (Quantum Metal)",
        "",
        "| notebook | components | builds | ports OK | LOM | rebuilt as | notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for nb, spec in LEGACY_NOTEBOOKS.items():
        recs = [checks[c] for c in spec["cells"] if c in checks]
        refs = ", ".join(f"`{c}`" for c in spec["cells"])
        b = f"{sum(r['builds'] for r in recs)}/{len(spec['cells'])}"
        ok = f"{sum(ports_ok(r).startswith('yes') for r in recs)}/{len(spec['cells'])}"
        el = [r for r in recs if _electrical(r["ref"])]
        lom = f"{sum(bool(r.get('lom')) for r in el)}/{len(el)}"
        art = _design_artifacts(spec["chip"]) or "legacy-b"
        lines.append(f"| `{nb}` | {refs} | {b} | {ok} | {lom} | {art} | {_esc(spec['note'])} |")

    # Not migrated
    lines += ["", "## Not migrated (explicit list)", "", "| file | reason | detail |", "|---|---|---|"]
    order = {r: i for i, r in enumerate(REASONS)}
    for path, reason, note in sorted(not_migrated, key=lambda t: (order.get(t[1], 9), t[0])):
        lines.append(f"| `{path}` | {reason} | {_esc(note)} |")
    lines += [
        "",
        "Also superseded by the PDK die frame (`layouts/chips/frame.py`) for chips, but kept as optional cells: the "
        "legacy markers and outlines (`CornerMarker`, `CrossMarker`, `GlobalMarker`, `DicingMarker`, "
        "`AlignmentMarkers`, `EbeamMarker`, `BoundaryBox`), drawn on the `marker_*` / `chip_boundary` layers.",
    ]

    # Quantcore cells
    inv_q = {e["ref"] for e in inventory.get("quantcore", [])}
    origins = legacy_origins()
    lines += [
        "",
        f"## Quantcore cells ({len(q_cells)})",
        "",
        "| ref | category | builds | ports OK | LOM | legacy origin | in inventory |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in q_cells:
        rec = checks.get(c.ref)
        if rec is None:
            continue
        org = ", ".join(f"`{o}`" for o in sorted(set(origins.get(c.ref, [])))) or "new"
        lines.append(
            f"| `{c.ref}` | {c.category} | {'yes' if rec['builds'] else 'NO: ' + _esc(rec['error'])} | "
            f"{_esc(ports_ok(rec))} | {_yes(rec.get('lom'))} | {org} | {'yes' if c.ref in inv_q else 'no (new)'} |"
        )
    return "\n".join(lines) + "\n"


_ELECTRICAL = {
    "qubit",
    "coupler",
    "capacitor",
    "resonator",
    "launcher",
    "termination",
    "junction",
    "waveguide",
    "airbridge",
}


def _electrical(ref: str) -> bool:
    from quantcore_circuits.layouts.catalog import find  # pylint: disable=import-outside-toplevel

    c = find(ref)
    return bool(c and c.category in _ELECTRICAL)


def _fn_ok(dotted: str) -> bool:
    import importlib  # pylint: disable=import-outside-toplevel

    module, _, name = dotted.rpartition(".")
    try:
        return callable(getattr(importlib.import_module(module), name))
    except Exception:  # noqa: BLE001  pylint: disable=broad-except
        return False


def _design_artifacts(chip) -> str:
    """Notebooks / design JSONs of the legacy builders for a chip id (or a list of candidate file stems)."""
    stems = {s.lower() for s in ([chip] if isinstance(chip, str) else list(chip or [])) if s}
    if not stems:
        return ""
    found = sorted(
        str(p.relative_to(ROOT))
        for p in (ROOT / "examples").rglob("*")
        if p.suffix in (".ipynb", ".json") and p.stem.lower() in stems and ".ipynb_checkpoints" not in str(p)
    )
    return ", ".join(f"`{f}`" for f in found)


def _metal_port_cases() -> dict[str, str]:
    """Metal class → the parametrisation id of the port test in tests/test_metal_components.py (its CASES)."""
    import ast  # pylint: disable=import-outside-toplevel

    tree = ast.parse((ROOT / "tests" / "test_metal_components.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "CASES" for t in node.targets):
            names = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
            from quantcore_circuits.layouts.metal import find_class_info  # pylint: disable=C0415

            out = {}
            for n in names:
                info = find_class_info(n)
                out[info.name if info else n] = n
            return out
    return {}


# ---- snapshots -----------------------------------------------------------------------------------------------
def snapshots(refs: list[str]) -> list[Path]:
    from kqcircuits.pya_resolver import pya  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.assembly.plan import pcell_params  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.layouts.registry import resolve_cell  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.live.snapshot import snapshot  # pylint: disable=import-outside-toplevel

    out = []
    for ref in refs:
        cls = resolve_cell(ref)
        layout = pya.Layout()
        top = layout.create_cell("TOP")
        cell = cls.create(layout, **pcell_params(cls, {}))
        top.insert(pya.DCellInstArray(cell.cell_index(), pya.DTrans()))
        name = ref.replace(":", "_")
        oas = BUILD / "cells" / f"{name}.oas"
        oas.parent.mkdir(parents=True, exist_ok=True)
        layout.write(str(oas))
        out.append(snapshot(oas, oas.with_suffix(".png"), size=(800, 800)))
    return out


# ---- main ----------------------------------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--migration", action="store_true", help="also build every inventory item → MIGRATION.md")
    ap.add_argument("--snapshots", action="store_true", help="also snapshot every Quantcore cell (build/components)")
    ap.add_argument("--no-golden", action="store_true", help="with --migration: do not run the golden tests")
    ap.add_argument(
        "--reuse", action="store_true", help="reuse build/components/checks.json and golden.xml of the last run"
    )
    args = ap.parse_args(argv)
    os.environ.setdefault("QCC_LIVE", "0")
    sys.path.insert(0, str(ROOT / "src"))

    from quantcore_circuits.layouts.catalog import NOTES, catalog, find  # pylint: disable=C0415

    entries = catalog(chips=True, routes=False)
    todo = [(c.ref, c.category) for c in entries if args.migration or c.category != "chip"]
    if args.migration:
        inventory = json.loads((DOCS / "inventory.json").read_text(encoding="utf-8"))
        known = {r for r, _ in todo}
        for e in inventory["kqc"] + inventory["metal"]:
            entry = find(e["ref"])
            if e["ref"] not in known and entry is not None and entry.cell:
                todo.append((e["ref"], entry.category))
    checks = {}
    if args.reuse and (BUILD / "checks.json").exists():
        checks = json.loads((BUILD / "checks.json").read_text(encoding="utf-8"))
    for i, (ref, category) in enumerate(todo, 1):
        if ref in checks:
            continue
        checks[ref] = check(ref, category, NOTES)
        flag = "ok" if checks[ref]["builds"] else "FAIL " + checks[ref]["error"][:100]
        print(f"[{i}/{len(todo)}] {ref}: {flag} ({checks[ref]['seconds']} s)", flush=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "checks.json").write_text(json.dumps(checks, indent=1, sort_keys=True), encoding="utf-8")
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "CATALOG.md").write_text(make_catalog(checks), encoding="utf-8")
    print(f"wrote {DOCS / 'CATALOG.md'}")
    if args.migration:
        if args.no_golden:
            golden = {}
        elif args.reuse and (BUILD / "golden.xml").exists():
            golden = parse_junit(BUILD / "golden.xml")
        else:
            golden = run_golden([*GOLDEN_FILES, "tests/test_metal_components.py"])
        (DOCS / "MIGRATION.md").write_text(make_migration(checks, golden), encoding="utf-8")
        print(f"wrote {DOCS / 'MIGRATION.md'}")
    if args.snapshots:
        for p in snapshots([c.ref for c in catalog(source="quantcore", chips=False)]):
            print(f"snapshot {p}")
    failed = [r for r, c in checks.items() if not c["builds"]]
    if failed:
        print(f"{len(failed)} entries failed to build: {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
