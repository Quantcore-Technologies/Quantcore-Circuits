"""Catalog of every component usable as a ``design.json`` ``cell``: Quantcore cells, KQCircuits elements and Quantum
Metal ``qlibrary`` components, each with a category.

>>> from quantcore_circuits.layouts.catalog import catalog, find
>>> [c.ref for c in catalog(category="launcher")]           # BondPad, Launcher, LauncherDC, metal:Launchpad...
>>> find("TransmonPocket").ref                               # 'metal:TransmonPocket'
>>> find("Xmon").port_names()                                # ports of a default instance (built lazily)

Listing is cheap: KQC classes are imported (≈1 s), Quantum Metal classes are read from source without importing
Metal. Ports are computed on demand (:meth:`Component.ports_of`), which builds the cell (and imports Metal for
``metal:`` entries).

``catalog()`` lists components (``cell=True``) and, with ``chips=True``, whole KQC chips (category ``chip``; usable as
cells for reference, not as components). ``routes=True`` adds the Metal routes, which are not cells (``cell=False``;
:data:`~quantcore_circuits.layouts.metal.ROUTE_MAPPING` says which qcc route replaces each).

Catalog decisions (2026-11-15; docs/components/DUPLICATES.md): :data:`EXCLUDED` refs are not listed (they may
still resolve by ref); :data:`LEGACY` cells stay listed and placeable with a ``legacy`` reason; :data:`ALIASES` groups
cells of the same kind with the same circuit that are drawn differently (``alias_of`` / ``aliases``, a marker only:
nothing is redirected).
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
from dataclasses import asdict, dataclass, field
from functools import cache
from pathlib import Path

CATEGORIES = (
    "qubit",
    "junction",
    "coupler",
    "capacitor",
    "resonator",
    "launcher",
    "termination",
    "waveguide",
    "airbridge",
    "marker",
    "test_structure",
    "flip_chip",
    "chip",
    "shape",
    "other",
)
SOURCES = ("quantcore", "kqc", "metal")

# KQC package → category; elements/ is refined by module/class name below
_KQC_PACKAGES = {
    "elements": None,
    "junctions": "junction",
    "qubits": "qubit",
    "test_structures": "test_structure",
    "chips": "chip",
}
_KQC_ELEMENT_RULES = (
    (r"x_coupler|capacitive_x", "coupler"),
    (r"capacitor", "capacitor"),
    (r"resonator", "resonator"),
    (r"launcher", "launcher"),
    (r"airbridge", "airbridge"),
    (r"chip_frame|marker", "marker"),
    (r"flip_chip|f2f|tsv|bump", "flip_chip"),
    (r"waveguide|meander", "waveguide"),
    (r"fluxline", "other"),
)
_QUANTCORE_FOLDERS = {"qubits": "qubit", "junctions": "junction", "chips": "chip"}

# ref → note shown in the catalog (decisions about ports that do not follow the general rules)
NOTES = {
    "LauncherDC": (
        "DC pad: its one port 'port' sits at the pad centre with no direction (KQC adds no corner; the square pad "
        "is symmetric). Place it with at=/rot=; a route may start or end there (it leaves toward its next node); "
        "it cannot be snapped to. For an RF launcher with a directed port use Launcher or BondPad."
    ),
    "Swissmon": (
        "port 'drive' has no direction with default parameters (KQC puts no port_drive_corner). Coupler ports "
        "'cplr0..2' have a = port_width[i]; the qubit's own gap around them is wider than b."
    ),
    "Xmon": (
        "claw tails ('claw_n/w/e') start the readout CPW: their clearance is claw_tail_gap (-1 = the element b, "
        "the chip CPW gap; claw_ground: claw_ground_gap) and the port declares exactly that (a = claw_tail_width); "
        "the claw body keeps the claw_spacing clearance. junction_type 'Quantcore Junction' / 'Quantcore Squid' = "
        "the PDK trilayer junctions; 3/0 keep-out = the legacy cross grown by 2*claw_base + 10 + claw_finger_width."
    ),
    "SpiralLine": (
        "legacy draw.spiral (Archimedean / Fermat / double Fermat by angle; the legacy double-Fermat typo y_bls/y1s "
        "fixed). Ports 'a'/'b' at the path ends face along the tangent (not Manhattan); metal by default: place it on "
        "a pocket (pocket_margin, or metal:Rectangle subtract). LOM: an open-ended line of the drawn length (rough, "
        "no kinetic inductance)."
    ),
    "ProbePadPair": (
        "chip_11m's commented-out probe pads (DC test structure, no ports, no circuit model): upper pad in 1/0, "
        "lower pad in the 3/0 second metal (qcc_keepout); junction_type 'Trilayer Junction Compact' puts the JX_500 "
        "junction in the cut-out."
    ),
    "JunctionTestPads": (
        "the legacy QWri test-pad block (Quantcore). KQC's test-structure factory of the same name is "
        "kqcircuits.test_structures.junction_test_pads.junction_test_pads.JunctionTestPads (dotted path)."
    ),
    "CoupledResonator": (
        "'end' is an open end: with ground=True the gap cap lies beyond the port, so anything joined there "
        "galvanically is cut off (ground=False leaves the end for a connection)."
    ),
    "QubitResonator": (
        "'end' (tail) is an open end: with ground=True the gap cap lies beyond the port, so anything joined there "
        "galvanically is cut off."
    ),
    **{
        f"metal:{name}": (
            f"draws metal only, no pocket ({why}): alone it is empty in the negative mask, as in Metal's own GDS "
            "(metal on the ground plane). Place it on a pocket, e.g. metal:Rectangle with subtract: true; its metal "
            "goes to base_metal_addition, which the fab export removes from the etch. Metal's defaults are mm-scale."
        )
        for name, why in (
            ("TransmonConcentricType2", "Metal leaves its pocket commented out"),
            ("TunableCoupler02", "Metal computes its pocket but never adds it"),
            ("ResonatorLumped", "perimeter and trace are both metal"),
            ("NSquareSpiral", "a metal spiral path; LOM on a pocket: an open line of the drawn length (rough)"),
        )
    },
    "CoupledConnector": (
        "'end' is an open end with ground=False (default): the gap box covers the port, so nothing can be joined "
        "galvanically; ground=True leaves the end for a connection."
    ),
    # cells re-implemented from QPDK (gdsfactory/quantum-rf-pdk, MIT) and SQDMetal (Apache-2.0)
    "Flipmon": (
        "QPDK flipmon_with_bbox (MIT). Face 2b1 (top-chip disc, its etch, the bump) is on KQC face-2b1 layers, which "
        "the PDK maps to 800/0+ (flip-chip). Port 'coupler' is on the M1 etch edge, 13 µm beyond QPDK's plate port "
        "o1 at defaults."
    ),
    "TrilayerConcentricTransmon": (
        "The Quantcore copy of KQC's ConcentricTransmon (same islands, couplers, drive port, parameters, ports and "
        "LOM branches) with the PDK trilayer junction: junction_type defaults to 'Quantcore Squid' (fingers 2/0 + "
        "4/0, spacer 50/0, gradient 51-53/0), sized by junction_params. KQC's cell keeps its Manhattan SQUID as a "
        "choice (left unset, a design draws it as the Quantcore Squid)."
    ),
    "Gatemon": (
        "QPDK gatemon (MIT): M1 plus the CNT contacts, nanotube, hBN, Al patches and top gate on the proposed "
        "layers 600-604/0 (qpdk_cells.GATEMON_LAYERS; no fab numbers yet, draw_process_layers=False for M1 "
        "only). Port 'readout' is the island edge (a = island width, b = pocket_gap_top), not a CPW end: snap it to "
        "GatemonCoupler.qubit."
    ),
    "GatemonCoupler": (
        "QPDK gatemon_coupler (MIT). Port 'qubit' is a capacitive reference plane (a = island_width, b = "
        "pocket_gap_top), not a CPW end: snap a Gatemon 'readout' to it."
    ),
    "TransmonTaperedInsets": (
        "SQDMetal TransmonTaperedInsets (Apache-2.0). The corner and pocket pins keep SQDMetal's normals "
        "(top_*_pin +x, bottom_*_pin +y, top_pocket_pin +x, bottom_pocket_pin -x): placement marks in or at the "
        "pocket, not CPW ends. Connection-pad ports are CPW ends."
    ),
    "SmoothCapacitorSemicircle": (
        "SQDMetal Smooth_Capacitor_Semicircle (Apache-2.0). Port 'target' is a placement reference: snap it to the "
        "qubit pin (SQDMetal start_pin); routes start at 'a' (set lead_length to reach the pocket edge)."
    ),
    "CapacitiveXCoupler": (
        "KQC draws no port refpoints, only its arm ends p11, p21, p31, p41 (KQC's own simulation ports): qcc gives "
        "them as CPW ports (element a/b) facing out along each arm (registry.KQC_EXTRA_PORTS, '+': S, E, N, W; 'x': "
        "the corners). LOM: each arm couples through its finger capacitor to the floating centre cross."
    ),
    "WaveguideCoplanarCurved": (
        "origin at the arc centre: port 'a' at (r, 0), 'b' at angle alpha, both facing out along the tangent "
        "(registry.KQC_EXTRA_PORTS; KQC draws no ports). LOM: a CPW line of r·|alpha|."
    ),
}

# refs not offered by the catalog (design decisions); they may still resolve by ref (``registry.resolve_cell``)
EXCLUDED = {
    "metal:MyQComponent": (
        "an exact copy of metal:Rectangle (Metal's 'EDIT HERE' user template), used by no design or test "
        "(decision 2026-11-15)"
    ),
}

# legacy cells (decision 2026-11-15): kept in the catalog and placeable (existing designs and golden tests build
# them by name); ``Component.legacy`` carries the reason. New designs use the cell named in the reason.
LEGACY = {
    "SpiralPath": (
        "legacy spiral.lym: the archimedean curve of SpiralLine (XOR 2.4 of 155 µm²) without ports or LOM model; "
        "golden test only. New designs: SpiralLine"
    ),
    "SquidV0": (
        "pre-HSQ SQUID (no spacer); no design uses it since chip_01 moved to the PDK SQUID; golden tests only. "
        "New designs: QuantcoreSquid ('Quantcore Squid')"
    ),
    "StripesTest": "= StripesTestIncreasingWidth with stripe_step 0 (XOR 0); unused. Use StripesTestIncreasingWidth",
    "ManhattanSingleJunction": (
        "KQC shadow-evaporation single junction (2/0 footprint, not the Quantcore trilayer process); unused. "
        "Use QuantcoreJunction"
    ),
    "metal:SQUID_LOOP": "Metal 2/0 SQUID footprint without pins, not the trilayer process; unused. Use QuantcoreSquid",
    "metal:BridgeFreeJunction": (
        "Metal 2/0 junction footprint without pins, not the trilayer process; unused. Use QuantcoreJunction"
    ),
    "DoublePadsSplines": "DoublePads with spline islands (same junction and model family); unused. Use DoublePads",
    "metal:NSquareSpiral": (
        "Metal sample shape (metal only, no pocket); unused; the same job as metal:ResonatorCoilRect"
    ),
    "metal:Airbridge": "unused; routes and KQC elements draw AirbridgeRectangular (use it, or a route airbridge)",
    "CapacitiveXCoupler": (
        "KQC test element 'for testing FEM computations'; unused. Ports p11..p41 and a LOM model since 2026-11-15"
    ),
    "WaveguideCoplanarCurved": (
        "the bare arc piece routes are drawn with; unused as a cell. Use a route (its bends). Ports a/b and a line "
        "LOM since 2026-11-15"
    ),
}

# Alias groups (decision 2026-11-15): cells of the same kind with the same circuit (equivalent LOM models for the
# same dimensions; tests/test_catalog_decisions.py) that are drawn differently (own drawing code, parameter names,
# defaults, port names, keep-out). A marker only: nothing is redirected, every ref keeps its geometry, parameters and
# ports. canonical ref → {alias ref: how its parameters and ports map onto the canonical}.
ALIASES: dict[str, dict[str, str]] = {
    # the user's pairs (the LaunchpadWirebond pair is in the launch-pad group below)
    "CpweOpenEnd": {
        "metal:OpenToGround": "termination_gap → length, width → a, gap → b; port open → a (XOR 0 at 6 and 10 µm)",
    },
    "WaveguideCoplanarSplitter": {
        "metal:LineTee": (
            "t_length → lengths [t, t, t] with angles [0, 180, 270]; prime_end → a, prime_start → b, second_end → c "
            "(XOR 0 at defaults)"
        ),
    },
    "WaveguideCoplanarTaper": {
        "CpweTaper": (
            "linear profile (taper_type 0): length → taper_length, a_end → a2, b_end → b2; ports a, b (XOR 0.03 of "
            "565 µm², dbu rounding). The exponential profiles 1–3 have no KQC drawing (same LOM: mean a/b)"
        ),
    },
    # the other exact-duplicate groups of docs/components/DUPLICATES.md where the definition fits
    "BondPad": {  # G15: every pad is the KQC Launcher polygon with mapped parameters; all are a 50 Ω port
        "metal:LaunchpadWirebond": (
            "the Launcher polygon (pad_height, pad_width, taper_height → taper_length, pad_gap) + a lead_length CPW "
            "lead (XOR 300 µm² = the lead); port tie → a"
        ),
        "metal:LaunchpadWirebondDriven": (
            "= metal:LaunchpadWirebond (same options, XOR 0) + pin 'in' on the pad (the same conductor); port tie → a"
        ),
        "Launcher": (
            "s → pad_height, l → taper_length, a_launcher → pad_width, b_launcher = launcher_frame_gap → pad_gap; "
            "BondPad = the Launcher rotated 270° (XOR 0); port port → a"
        ),
        "ConnectorPad": (
            "rounded=False = the Launcher polygon with a side gap b·pad_width/a and a back gap pad_height (no BondPad "
            "parameter set matches); rounded=True has no Launcher drawing; port a. BondPad / ConnectorPad keep their "
            "own 3/0 keep-out and lumped-port refpoints"
        ),
        "CpweBondPad": (
            "taper_type 0 = the Launcher polygon rotated 180° and shifted (XOR 0); taper_type 1–3 differ; port a"
        ),
    },
    "WaveguideCoplanar": {  # G18 straight CPW
        "CpwSegment": (
            "length L → path [(-L/2, 0), (L/2, 0)] (CpwSegment is centred on the origin; XOR 0); ports a, b. "
            "CpwSegment adds the legacy 3/0 keep-out"
        ),
    },
    "QuantcoreJunction": {  # G4: the PDK preset of TrilayerJunction
        "TrilayerJunction": "finger_width 0.5, second_finger_width 0.6, clearer True = QuantcoreJunction (XOR 0)",
    },
    "QuantcoreSquid": {  # G5: the PDK preset of TrilayerSquid
        "TrilayerSquid": "finger_width 0.25, second_finger_width 0.6, clearer True = QuantcoreSquid (XOR 0)",
    },
    "metal:TransmonPocket": {  # G1
        "metal:TransmonPocket6": (
            "same options; for the same connection pad set Pocket6's pad_cpw_shift 5 µm and pocket_rise 65 µm "
            "(TransmonPocket's pad defaults; Pocket6's own are 0) (XOR 0); loc_W 0 adds Pocket6's middle positions"
        ),
    },
    "metal:TransmonCross": {  # G2
        "metal:TransmonStar": (
            "num_points 4, arm_length / arm_width / arm_gap → cross_length / cross_width / cross_gap, "
            "junction_arm_index 3 (XOR 0); claws: arm_index instead of connector_location"
        ),
    },
    "FluxHoles": {"FluxHoleArray": "the array's hole centres as FluxHoles' list (XOR 0); no circuit elements"},  # G29
    "StripesTestIncreasingWidth": {"StripesTest": "stripe_step 0 (XOR 0); lithography test, no circuit"},  # G25
}


def alias_group(ref: str) -> list[str]:
    """The refs of ``ref``'s alias group, canonical first ([] when ``ref`` has no aliases)."""
    for canonical, members in ALIASES.items():
        if ref == canonical or ref in members:
            return [canonical, *members]
    return []


@dataclass
class Component:
    """One catalog entry. ``ref`` is what goes into ``design.json`` ``cell`` (or ``Designer.add``)."""

    name: str
    ref: str
    source: str  # quantcore | kqc | metal
    category: str
    module: str
    description: str = ""
    cell: bool = True  # False: not instantiable as a cell (Metal routes)
    note: str = ""
    legacy: str = ""  # why the cell is legacy (LEGACY); "" = current. Legacy cells stay listed and placeable
    # canonical cell of its alias group (ALIASES: same circuit, drawn differently); "" = no group, or the canonical
    alias_of: str = ""
    aliases: list[str] = field(default_factory=list)  # the other cells of its alias group (canonical included)
    ports: list[str] | None = field(default=None, compare=False)  # filled by catalog(ports=True) / port_names()

    def resolve(self):
        """The Element class of this entry."""
        from quantcore_circuits.layouts.registry import resolve_cell  # pylint: disable=import-outside-toplevel

        if not self.cell:
            raise ValueError(f"{self.ref} is not a cell: {self.note}")
        return resolve_cell(self.ref)

    def ports_of(self, **params) -> dict:
        """Ports (``Port`` objects, local frame) of an instance with ``params`` (design.json style)."""
        from quantcore_circuits.assembly.plan import pcell_params  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.layouts.registry import element_ports  # pylint: disable=import-outside-toplevel

        cls = self.resolve()
        return element_ports(cls, **pcell_params(cls, params))

    def port_names(self) -> list[str]:
        """Port names of a default instance (cached on the entry)."""
        if self.ports is None:
            self.ports = sorted(self.ports_of()) if self.cell else []
        return self.ports

    def as_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    def tag(self) -> str:
        """Marker for listings: ``(legacy)``, ``(alias of <ref>)``, both, or ``""``."""
        parts = (["legacy"] if self.legacy else []) + ([f"alias of {self.alias_of}"] if self.alias_of else [])
        return f"({'; '.join(parts)})" if parts else ""

    def listing_line(self) -> str:
        """One line of the plain ``qcc components`` listing: ref, source, tag, description, note."""
        tag = f"{self.tag()} " if self.tag() else ""
        note = f"  [{self.note}]" if self.note else ""
        return f"  {self.ref:32s} {self.source:9s} {tag}{self.description[:70]}{note}"


# ---- sources ----------------------------------------------------------------------------------------------------
def _first_line(obj) -> str:
    doc = inspect.getdoc(obj) or ""
    return next((ln.strip() for ln in doc.splitlines() if ln.strip()), "")[:160]


def _is_abstract(cls) -> bool:
    from kqcircuits.elements.element import Element  # pylint: disable=import-outside-toplevel

    return cls.build is Element.build


@cache
def _quantcore() -> tuple[Component, ...]:
    from quantcore_circuits import layouts  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.layouts.metal import MetalComponent  # pylint: disable=import-outside-toplevel

    out = []
    for cls in layouts.pcell_classes():
        if issubclass(cls, MetalComponent):
            continue  # the generic wrapper: listed per Metal class as metal:<Class>
        parts = cls.__module__.split(".")
        folder = parts[2] if len(parts) > 3 else ""
        category = getattr(cls, "qcc_category", None) or _QUANTCORE_FOLDERS.get(folder, "other")
        out.append(Component(cls.__name__, cls.__name__, "quantcore", category, cls.__module__, _first_line(cls)))
    return tuple(out)


@cache
def _kqc() -> tuple[Component, ...]:
    import kqcircuits  # pylint: disable=import-outside-toplevel
    from kqcircuits.elements.element import Element  # pylint: disable=import-outside-toplevel

    base = Path(kqcircuits.__file__).parent
    out, seen = [], set()
    for pkg, pkg_category in _KQC_PACKAGES.items():
        for info in pkgutil.walk_packages([str(base / pkg)], prefix=f"kqcircuits.{pkg}."):
            try:
                module = importlib.import_module(info.name)
            except Exception:  # noqa: BLE001  pylint: disable=broad-except
                continue
            for name, cls in inspect.getmembers(module, inspect.isclass):
                if cls.__module__ != module.__name__ or not issubclass(cls, Element) or name in seen:
                    continue
                if name.startswith("_") or (_is_abstract(cls) and pkg != "chips"):
                    continue
                category = pkg_category
                if category is None:
                    key = f"{info.name.rsplit('.', 1)[-1]} {name.lower()}"
                    category = next((c for pat, c in _KQC_ELEMENT_RULES if re.search(pat, key)), "other")
                seen.add(name)
                out.append(Component(name, name, "kqc", category, info.name, _first_line(cls)))
    return tuple(out)


@cache
def _metal() -> tuple[Component, ...]:
    from quantcore_circuits.layouts.metal import ROUTE_MAPPING, qlibrary_index  # pylint: disable=C0415

    out = []
    for name, info in sorted(qlibrary_index().items()):
        if info.is_route:
            note = f"Metal route, not a cell: use a qcc {ROUTE_MAPPING.get(name, 'route')}"
            out.append(
                Component(name, f"metal:{name}", "metal", "waveguide", info.module, info.description, False, note)
            )
        else:
            out.append(Component(name, f"metal:{name}", "metal", info.category, info.module, info.description))
    return tuple(out)


_SOURCES = {"quantcore": _quantcore, "kqc": _kqc, "metal": _metal}


def catalog(
    category: str | None = None,
    source: str | None = None,
    chips: bool = True,
    routes: bool = False,
    ports: bool = False,
) -> list[Component]:
    """Catalog entries (fresh copies), Quantcore first, then KQC, then Metal; each group sorted by category and name.

    ``category``/``source`` filter; ``chips=False`` drops whole chips; ``routes=True`` adds the Metal routes (not
    cells); ``ports=True`` also builds every entry to fill ``ports`` (slow; imports Quantum Metal).
    """
    if category is not None and category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}; categories: {', '.join(CATEGORIES)}")
    if source is not None and source not in SOURCES:
        raise ValueError(f"unknown source {source!r}; sources: {', '.join(SOURCES)}")
    out = []
    for src in SOURCES:
        if source is not None and src != source:
            continue
        group = [Component(**asdict(c)) for c in _SOURCES[src]() if c.ref not in EXCLUDED]
        for c in group:
            if c.ref in NOTES and not c.note:
                c.note = NOTES[c.ref]
            c.legacy = LEGACY.get(c.ref, "")
            members = alias_group(c.ref)
            c.alias_of = members[0] if members and members[0] != c.ref else ""
            c.aliases = [m for m in members if m != c.ref]
        group.sort(key=lambda c: (CATEGORIES.index(c.category), c.name.lower()))
        out += group
    out = [
        c
        for c in out
        if (category is None or c.category == category) and (chips or c.category != "chip") and (routes or c.cell)
    ]
    if ports:
        for c in out:
            try:
                c.port_names()
            except Exception:  # noqa: BLE001  pylint: disable=broad-except
                c.ports = None
    return out


def find(name: str) -> Component | None:
    """The entry for a ref or name: exact ref, then exact name, then case-insensitive (Metal routes included)."""
    entries = catalog(routes=True)
    for key in (lambda c: c.ref, lambda c: c.name):
        for c in entries:
            if key(c) == name:
                return c
    low = name.lower().removeprefix("metal:")
    for c in entries:
        if c.name.lower() == low or c.ref.lower() == name.lower():
            return c
    if name.startswith("metal:"):
        from quantcore_circuits.layouts.metal import find_class_info  # pylint: disable=import-outside-toplevel

        info = find_class_info(name[len("metal:") :])
        if info is not None:
            return next((c for c in entries if c.ref == f"metal:{info.name}"), None)
    return None


def categories() -> dict[str, list[str]]:
    """Category → refs (components and chips)."""
    out: dict[str, list[str]] = {}
    for c in catalog():
        out.setdefault(c.category, []).append(c.ref)
    return out


def listing(entries: list[Component]) -> list[str]:
    """The plain ``qcc components`` listing of ``entries``: a ``<category>:`` header per category, then one
    :meth:`Component.listing_line` per entry (legacy and alias cells tagged)."""
    lines, current = [], None
    for c in sorted(entries, key=lambda c: (c.category, c.source != "quantcore", c.ref.lower())):
        if c.category != current:
            current = c.category
            lines.append(f"{current}:")
        lines.append(c.listing_line())
    return lines


__all__ = [
    "ALIASES",
    "CATEGORIES",
    "EXCLUDED",
    "LEGACY",
    "NOTES",
    "SOURCES",
    "Component",
    "alias_group",
    "catalog",
    "categories",
    "find",
    "listing",
]
