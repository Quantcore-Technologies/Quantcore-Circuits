"""Quantcore process design kit: fab layer map, stack-up and CPW defaults.

Geometry is always drawn in KQC layer names (``1t1_base_metal_gap_wo_grid``, ``1t1_SIS_junction``, ...) plus a few
Quantcore layers (:data:`QCC_LAYERS`, drawn at their fab numbers). Fab layer numbers appear at mask export
(:mod:`quantcore_circuits.layouts.wafers.fab_export`). The map below is the fab layer map (2026-11-03), all as a
**negative** mask (drawn = removed / exposed):

=========  ================================================  ====================================================
fab layer  source                                            meaning
=========  ================================================  ====================================================
1/0        KQC ``base_metal_gap`` (drawn = etch)             fine structure: feedline ends, resonator and
                                                             transmon ground cut-outs
2/0        KQC ``SIS_junction``                              junction top finger
3/0        derived: filled keep-outs (:class:`KeepoutRule`)  second-metal subtractive etch: each 1/0 feature
                                                             *including* what lies between its gaps (a CPW's
                                                             centre conductor, a qubit's island) + ground margin,
                                                             plus the cheese holes (the same squares as on 1/0)
4/0        KQC ``SIS_junction_2``                            junction second finger
50/0       qcc ``hsq``                                       junction spacer material (HSQ)
51–53/0    qcc ``spacer_1`` … ``spacer_3``                   spacer gradient (greyscale lithography shades)
100/0      qcc ``chip_boundary`` (drawn by the die frame)    chip boundary
500/0      qcc ``wafer_boundary``                            wafer boundary (wafer level, ``Wafer``)
501/0      qcc ``wafer_markers``                             wafer markers: die labels / outlines, alignment
                                                             and orientation marks (wafer level, ``Wafer``)
1000/0 …   qcc ``marker_0`` … (drawn by the die frame)       marker layers: 1000/0 dicing markers, 1001/0
                                                             alignment-marker grids (confirmed 2026-11-03)
300/0      KQC ``airbridge_pads``                            airbridge layers ("300/0"); the bridge
301/0      KQC ``airbridge_flyover``                         (flyover) on 301/0 is an assumption
700/0      KQC ``through_silicon_via``                       TSVs
800/0 …    KQC face ``2b1`` (flip-chip top chip)             800/0 its base-metal etch, 801/0 indium bumps,
                                                             802/0 under-bump metal, 803/0 + 804/0 its
                                                             junction fingers (numbering after 800 assumed)
=========  ================================================  ====================================================

**Universal Quantcore (QCT) chip rules** (2026-11-03), applied to every chip built with this PDK:

* the die frame: L-shaped dicing markers and the 3×3 alignment grids (:class:`DieFrame`); the device ID is optional
  (edge centres → beside the feedline pads, 50 µm gap → slid along the left/right edges; omitted if nowhere free);
* the brand text is ``"QCT"`` (:attr:`Pdk.brand`) wherever a KQC chip frame draws one;
* **fab export only** (never in simulation exports): ground **cheese** in a band around the components
  (:class:`CheeseRule`: 3/0 grown by ``rows`` grid pitches, 5 µm squares, 20 µm gaps, none within 4 µm of the 3/0
  keep-outs; every hole is written on 1/0 *and* on 3/0, 2026-11-17) and
  **rounded corners** with a radius tied to each polygon's shortest dimension (:class:`CornerRounding`).

The die frame (:class:`DieFrame`, ``components/pdk_geometry_summary.md``) is drawn on every chip by default.
``hsq_boundary`` (legacy HSQ write-field frame, 150/0) is kept for the legacy marker cells but is not a fab layer.
Legacy helper layers 9/0 (bounding box) and 10/0 (scratch) are not exported.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field, replace
from functools import cache

from kqcircuits.pya_resolver import pya

# Extra layers not present in KQC's default layer config, drawn directly at their fab numbers (KQC's own layers use
# datatype ≥ 1, apart from 220–225/0, so none of these collide).
QCC_LAYERS = {
    "hsq": pya.LayerInfo(50, 0, "qcc_spacer"),
    "spacer_1": pya.LayerInfo(51, 0, "qcc_spacer_1"),
    "spacer_2": pya.LayerInfo(52, 0, "qcc_spacer_2"),
    "spacer_3": pya.LayerInfo(53, 0, "qcc_spacer_3"),
    "chip_boundary": pya.LayerInfo(100, 0, "qcc_chip_boundary"),
    "wafer_boundary": pya.LayerInfo(500, 0, "qcc_wafer_boundary"),
    "wafer_markers": pya.LayerInfo(501, 0, "qcc_wafer_markers"),
    "hsq_boundary": pya.LayerInfo(150, 0, "qcc_hsq_boundary"),  # legacy, not exported
    **{f"marker_{i}": pya.LayerInfo(1000 + i, 0, f"qcc_marker_{i}") for i in range(4)},
    # gatemon process layers drawn by qpdk_cells.Gatemon at the components agent's *proposed* numbers: not fab layers
    # until fab numbers are given, so `qcc mask` reports them as dropped instead of losing them silently
    **{
        f"gatemon_{n}": pya.LayerInfo(600 + i, 0, f"qcc_{n}")
        for i, n in enumerate(("cnt_contact", "cnt", "hbn", "jj_patch", "top_gate"))
    },
}


@dataclass(frozen=True)
class FabLayer:
    layer: int
    datatype: int
    source: str  # KQC layer name (without face prefix), qcc layer name, or "derived"
    invert: bool = False  # True: export the complement inside the chip box (positive metal)
    description: str = ""
    faces: tuple[str, ...] | None = None  # KQC faces to read (union); None = the PDK's own face

    @property
    def info(self) -> pya.LayerInfo:
        return pya.LayerInfo(self.layer, self.datatype)


@dataclass(frozen=True)
class Stack:
    """Material stack used by simulation exports (all lengths in µm)."""

    substrate_material: str = "sapphire"
    substrate_permittivity: float = 10.25  # effective isotropic value used by Quantcore (2026-11-02)
    substrate_loss_tangent: float = 1e-6
    substrate_height: float = 650.0  # wafer thickness confirmed (2026-11-02)
    metal_height: float = 0.0  # 0 = sheet (PEC) metal; Nb film ~0.2 µm if thick metal is needed
    metal_thickness_um: float = 0.2  # used by analytic CPW formulas only
    upper_box_height: float = 1000.0
    lower_box_height: float = 0.0
    london_penetration_depth_um: float = 0.09  # Nb


@dataclass(frozen=True)
class DieFrame:
    """Die frame (``components/pdk_geometry_summary.md``), drawn inside the chip box; all lengths in µm.

    Corner L-shaped dicing markers (legs along the die edges), a design area inset by ``margin``, a
    ``marker_area`` square in each corner of the design area holding a 3×3 alignment grid, and the device-ID block
    centred at the bottom of the design area. Grid positions are measured from the die corner, mirrored for the
    other corners.

    **Pad rule** (2026-11-03; distance 2026-11-10): bond pads and launchers sit with the outer edge of their
    etch ``pad_edge`` = 100 µm from the die edge (the design-area margin), whatever the original chip did.
    ``place.edge`` in a design puts an instance there; KQC sample-holder launchers get their ``launcher_indent`` from
    it (unless a design sets ``launchers.indent``); the DRC flags pads that are not there (``pad_edge`` warning).
    """

    margin: float = 100.0
    dicing_leg: float = 250.0
    dicing_width: float = 25.0
    marker_area: float = 500.0
    grid_x: tuple[float, float, float] = (302.5, 452.5, 602.5)
    grid_y: tuple[float, float, float] = (305.0, 452.5, 600.0)
    grid_small: float = 5.0  # corners and centre of the 3×3 grid
    grid_large: float = 10.0  # edge midpoints
    device_id: tuple[float, float] = (700.0, 300.0)
    pad_edge: float = 100.0  # pads/launchers: outer etch edge this far from the die edge (2026-11-10)
    dicing_layer: str = "marker_0"
    alignment_layer: str = "marker_1"
    boundary_layer: str = "chip_boundary"


@dataclass(frozen=True)
class KeepoutRule:
    """3/0: where the second metal is etched away after its deposition (design rule, 2026-11-03), so it cannot short
    the 1/0 features. Filled regions — they do not exclude the 1/0 structure in the middle:

    * routes (CPW lines, meanders): the whole CPW footprint (gaps + centre conductor) grown by ``route_margin``
      (legacy resonators ≈ 6 µm: some ground on both sides);
    * components (qubits, pads, capacitors …): the bounding box of their etch grown by ``component_margin`` — a
      square/rectangle engulfing some ground (as the legacy Xmon / two-pad PCells draw it), unless the cell defines
      its own keep-out with a classmethod ``qcc_keepout(params) -> [pya.DBox | pya.DPolygon]`` (local µm);
    * anything else drawn in 1/0 (device-ID text, shapes placed directly): grown by ``other_margin``.

    Fab change 2026-11-17 (design rule): every 3/0 keep-out is 4 µm wider per side than before
    (the cheese sat too close to its edge): ``route_margin`` 6 → 10, ``component_margin`` 20 → 24,
    ``other_margin`` 5 → 9, and the keep-outs the cells draw themselves (``qcc_keepout``, legacy PCells) grow by ``own_grow`` = 4 (applied once in
    :func:`~quantcore_circuits.layouts.wafers.fab_export.keepout_region`, not per cell).

    Whole chips placed as one cell (e.g. a KQC chip replica) are opened and their parts treated as above.

    Gaps the union leaves between neighbouring keep-outs are filled when smaller than ``fill_holes_um2``; larger
    enclosed areas — the ground inside a closed bus ring — stay outside 3/0 (they are ground, not a feature), so the
    cheese can reach them (notebooks-metal, 2026-11-10).
    """

    route_margin: float = 10.0
    component_margin: float = 24.0
    other_margin: float = 9.0
    own_grow: float = 4.0  # added to a cell's own ``qcc_keepout`` shapes
    fill_holes_um2: float = 200.0 * 200.0


@dataclass(frozen=True)
class CheeseRule:
    """Ground cheese (design rule): holes only in a band around the components, not over the whole chip.

    The band is the 3/0 keep-out grown by ``rows`` grid pitches; ``size`` µm squares on a chip-aligned grid with
    ``gap`` µm between them (pitch = size + gap) are kept where they lie entirely in the band, ``clearance`` µm or
    more from 3/0, inside the design area and clear of the frame's markers and device ID. They are etched (added to
    ``layer``, M1 = 1/0) and, as the same squares (not grown by the keep-out margin), added to 3/0 (2026-11-17: the
    cheese is on both fab layers 1/0 and 3/0; the clearance is to the keep-outs alone). Simulation exports never get
    cheese.

    Where it is drawn (2026-11-03): in the chip build itself, into KQC's ``ground_grid`` layer, so layouts and
    snapshots show it (chip parameter ``cheese``: ``"auto"`` default, ``"pdk"``, ``"original"``). **The original
    design wins**: a design that carries its own cheese (KQC ``with_grid``, or a static cell with its holes — mark it
    ``cheese: "original"``) keeps it and gets no PDK band; a design without any gets this band. The fab export adds
    the band only to a build that has no cheese at all.
    """

    size: float = 5.0
    gap: float = 20.0
    rows: int = 3
    clearance: float = 4.0  # no hole closer than this to 3/0 (2026-11-17)
    layer: str = "M1"

    @property
    def pitch(self) -> float:
        return self.size + self.gap


@dataclass(frozen=True)
class CornerRounding:
    """Fab-export rounding of sharp corners (design rule): each polygon's corners get a radius tied to its shortest
    dimension, so narrow features keep their shape and wide ones get softer corners.

    Shortest dimension d = min(2·area/perimeter, shortest straight edge ≥ ``min_edge``) (a strip of width w gives
    w); radius r = min(``fraction`` · d, ``max_radius``), skipped below ``min_radius``. Applied to ``layers``
    (fab-layer names) before cheesing; junction fingers are left exact by default.
    """

    fraction: float = 0.25
    max_radius: float = 10.0
    min_radius: float = 0.1
    min_edge: float = 2.0  # ignore shorter edges (arc facets, joints) when bounding the radius
    points: int = 64  # points per full circle
    layers: tuple[str, ...] = ("M1", "M3")


# ---- junction process (components-pdk agent; design decisions #1 / #21, 2026-11-03) ------------------------------
@dataclass(frozen=True)
class JunctionProcess:
    """Quantcore Nb/AlOx/Nb trilayer junction rule (2026-11-03): Nb gap Δ = 1.4 meV, R_n 40–50 kΩ, qubits
    at 4–8 GHz. Formulas: :mod:`quantcore_circuits.circuit.bridges` (I_c·R_n = πΔ/2e, Ambegaokar–Baratoff at
    T ≪ T_c; L_J = Φ0/2πI_c; R_n = R_n·A / area; :func:`~quantcore_circuits.circuit.bridges.size_junction`).

    **Assumed** (not stated in the fab spec; flagged as an open assumption): the specific resistance
    ``rn_area_ohm_um2`` = 45 kΩ × 0.30 µm², chosen so the trilayer chips' nominal qubit junction (straight 0.5 µm ×
    bent 0.6 µm: chip_05 Q2–Q6, chip_10a, chip_11m ``JX``, the centre of the chip_04/06/08 test sweeps) has
    R_n = 45 kΩ; that is J_c = πΔ/(2e·R_n·A) ≈ 0.163 µA/µm² (16 A/cm²). ``cj_fF_per_um2`` (50 fF/µm²) is the
    usual Nb/AlOx/Nb specific capacitance. Sizing keeps the bent finger at ``bent_finger_um`` and solves the
    straight finger, rounded to ``finger_grid_um`` within ``finger_range_um``.

    ``spacer_gradient`` switches the 51–53/0 dose levels on by default in every junction cell that draws a 50/0
    spacer (decision #4: rectangular spacers split into ``spacer_shades`` nested strips of width/3, windows and
    concentric spacers into rings; :func:`quantcore_circuits.layouts.junctions.trilayer.spacer_gradient_levels`).
    """

    material: str = "Nb/AlOx/Nb trilayer"
    gap_meV: float = 1.4
    rn_target_kohm: tuple[float, float] = (40.0, 50.0)
    rn_nominal_kohm: float = 45.0
    f_q_range_GHz: tuple[float, float] = (4.0, 8.0)
    nominal_fingers_um: tuple[float, float] = (0.5, 0.6)  # (straight, bent) of the trilayer chips' qubit junction
    rn_area_ohm_um2: float = 13500.0  # ASSUMED: rn_nominal_kohm × the nominal finger area
    cj_fF_per_um2: float = 50.0  # ASSUMED
    bent_finger_um: float = 0.6
    finger_grid_um: float = 0.01
    finger_range_um: tuple[float, float] = (0.1, 2.0)
    spacer_gradient: bool = True
    spacer_shades: int = 3
    # the R_n window is for the device: a SQUID's parallel R_n (2026-11-13: "40-50 kΩ is for the whole SQUID,
    # actual junctions are higher based on ratio"); a symmetric SQUID's junctions are 2× (asymmetric: by the ratio)

    @property
    def nominal_area_um2(self) -> float:
        return self.nominal_fingers_um[0] * self.nominal_fingers_um[1]

    @property
    def jc_uA_per_um2(self) -> float:
        """Critical-current density implied by ``gap_meV`` and ``rn_area_ohm_um2`` (µA/µm²)."""
        return 3.141592653589793 * self.gap_meV * 1e-3 / 2 / self.rn_area_ohm_um2 * 1e6


@dataclass(frozen=True)
class KineticInductance:
    """Kinetic inductance of the superconducting film (decision #45, 2026-11-03).

    Sheet kinetic inductance of a film of thickness ``t`` and London penetration depth ``λ_L`` in the local London
    limit (uniform current across the thickness, T ≪ T_c, dirty-limit λ_eff supplied as ``λ_L``):

        L_s = μ0 · λ_L · coth(t / λ_L)        [H/□]    (Annett 1990; Tinkham §3; coth → λ_L/t · μ0 λ_L for t ≪ λ_L)

    For the Nb of this PDK (λ_L = 90 nm, t = 200 nm): L_s = 0.1158 pH/□ (≈ 0.12 pH/□).
    ``sheet_inductance_pH_sq`` overrides the formula with a measured value (e.g. from a resonator-frequency fit);
    ``enabled=False`` switches kinetic inductance off everywhere (analytic CPW formulas, resonator lengths, wire
    inductors): the old values return.
    Not valid when t ≳ 3 λ_L (bulk: use the geometric inductance only, L_s → μ0 λ_L is still the surface value) or
    for dimensions ≲ the Pearl length 2λ²/t.
    """

    enabled: bool = True
    sheet_inductance_pH_sq: float | None = None  # explicit L_s override (pH/□); None: from λ_L and t

    def sheet_pH_sq(self, stack: Stack) -> float:
        """L_s in pH/□ (0 when disabled)."""
        if not self.enabled:
            return 0.0
        if self.sheet_inductance_pH_sq is not None:
            return float(self.sheet_inductance_pH_sq)
        lam, t = stack.london_penetration_depth_um, stack.metal_thickness_um
        x = t / lam
        return 4e-7 * math.pi * lam * 1e-6 / math.tanh(x) * 1e12


@dataclass(frozen=True)
class Pdk:
    name: str
    version: str
    fab_layers: dict[str, FabLayer]
    stack: Stack = field(default_factory=Stack)
    cpw_a: float = 10.0  # centre width, µm
    cpw_b: float = 6.0  # gap, µm
    turn_radius: float = 100.0
    m3_margin_um: float = 5.0  # legacy: 3/0 = 1/0 grown by this; superseded by ``keepout`` (other_margin)
    face: str = "1t1"
    design_grid_um: float = 0.001  # snap grid for GUI placement (KLayout grid is used if coarser)
    die_size: tuple[float, float] = (7500.0, 7500.0)  # standard die (µm)
    frame: DieFrame | None = field(default_factory=DieFrame)  # None: KQC's chip frame instead
    brand: str = "QCT"  # brand text on chip frames (2026-11-03)
    keepout: KeepoutRule = field(default_factory=KeepoutRule)  # 3/0 keep-outs
    cheese: CheeseRule | None = field(default_factory=CheeseRule)  # fab export only; None: no cheese
    rounding: CornerRounding | None = field(default_factory=CornerRounding)  # fab export only; None: sharp corners
    junction: JunctionProcess = field(default_factory=JunctionProcess)  # trilayer junction rule (components-pdk)
    kinetic: KineticInductance = field(default_factory=KineticInductance)  # film kinetic inductance (decision #45)
    # other films of the process by name (2026-11-10: "yes we will do NbN; add it to the PDK"): the default
    # film is ``kinetic`` (Nb); "NbN" is the high-kinetic-inductance film of KI devices (KI-TWPA, KIPA): L_s 20 pH/□
    # as the NY CREATES / twpa-sim geometry assumes. Choosing a film per element is a later step
    films: dict[str, KineticInductance] = field(
        default_factory=lambda: {"Nb": KineticInductance(), "NbN": KineticInductance(sheet_inductance_pH_sq=20.0)}
    )

    def film(self, name: str | None = None) -> KineticInductance:
        """The kinetic inductance of film ``name`` ("Nb", "NbN"); None → the default film (``kinetic``)."""
        if name is None:
            return self.kinetic
        if name not in self.films:
            raise KeyError(f"PDK {self.name}: no film {name!r}; films: {sorted(self.films)}")
        return self.films[name]

    def material_dict(self) -> dict:
        return {
            self.stack.substrate_material: {
                "permittivity": self.stack.substrate_permittivity,
                "dielectric_loss_tangent": self.stack.substrate_loss_tangent,
            }
        }

    def simulation_params(self) -> dict:
        """KQC ``Simulation`` parameters for this stack."""
        s = self.stack
        return {
            "face_stack": [self.face],
            "substrate_height": [s.substrate_height],
            "substrate_material": [s.substrate_material],
            "material_dict": str(self.material_dict()),
            "metal_height": [s.metal_height],
            "upper_box_height": s.upper_box_height,
            "lower_box_height": s.lower_box_height,
        }


_FAB_LAYERS = {
    "M1": FabLayer(1, 0, "base_metal_gap", description="fine structure etch (negative)"),
    "JJ_STRAIGHT": FabLayer(2, 0, "SIS_junction", description="junction top finger"),
    "M3": FabLayer(3, 0, "derived", description="second-metal keep-out: filled keep-outs (KeepoutRule)"),
    "JJ_BENT": FabLayer(4, 0, "SIS_junction_2", description="junction second finger"),
    "HSQ": FabLayer(50, 0, "hsq", description="junction spacer material"),
    "SPACER_1": FabLayer(51, 0, "spacer_1", description="spacer gradient, shade 1"),
    "SPACER_2": FabLayer(52, 0, "spacer_2", description="spacer gradient, shade 2"),
    "SPACER_3": FabLayer(53, 0, "spacer_3", description="spacer gradient, shade 3"),
    "CHIP_BOUNDARY": FabLayer(100, 0, "chip_boundary", description="chip boundary"),
    "WAFER_BOUNDARY": FabLayer(500, 0, "wafer_boundary", description="wafer boundary"),
    "WAFER_MARKERS": FabLayer(501, 0, "wafer_markers", description="wafer markers"),
    "MARKERS_DICING": FabLayer(1000, 0, "marker_0", description="dicing markers"),
    "MARKERS_ALIGN": FabLayer(1001, 0, "marker_1", description="alignment markers"),
    "AIRBRIDGE_PADS": FabLayer(300, 0, "airbridge_pads", description="airbridge pads"),
    "AIRBRIDGE_BRIDGE": FabLayer(301, 0, "airbridge_flyover", description="airbridge bridge (301/0 assumed)"),
    "TSV": FabLayer(700, 0, "through_silicon_via", description="through-silicon vias", faces=("1t1", "2b1")),
    "FC_M1": FabLayer(800, 0, "base_metal_gap", description="flip-chip top chip (face 2b1) etch", faces=("2b1",)),
    "FC_BUMPS": FabLayer(801, 0, "indium_bump", description="indium bumps", faces=("1t1", "2b1")),
    "FC_UBM": FabLayer(802, 0, "underbump_metallization", description="under-bump metal", faces=("1t1", "2b1")),
    "FC_JJ_1": FabLayer(803, 0, "SIS_junction", description="face 2b1 junction finger 1", faces=("2b1",)),
    "FC_JJ_2": FabLayer(804, 0, "SIS_junction_2", description="face 2b1 junction finger 2", faces=("2b1",)),
}

# Default process: Nb on sapphire. Version 2: the 2026-11-03 layer map and die frame (v1 had HSQ on 500/0).
QUANTCORE_NB_SAPPHIRE_V1 = Pdk(name="quantcore_nb_sapphire_v1", version="3", fab_layers=_FAB_LAYERS)

# Same layers and CPW rules on high-resistivity silicon (kept for comparison runs and older designs).
QUANTCORE_NB_SI_V1 = Pdk(
    name="quantcore_nb_si_v1",
    version="3",
    fab_layers=_FAB_LAYERS,
    stack=Stack(substrate_material="silicon", substrate_permittivity=11.45),
)

DEFAULT_PDK = QUANTCORE_NB_SAPPHIRE_V1.name
_PDKS = {p.name: p for p in (QUANTCORE_NB_SAPPHIRE_V1, QUANTCORE_NB_SI_V1)}


# A design's own substrate on a PDK: "quantcore_nb_sapphire_v1+substrate(h=500,eps_r=11.45,tan_d=1e-06)" is that PDK
# with the substrate thickness (µm), permittivity and loss tangent replaced (any subset; the KLayout plugin's Chip
# settings write it). Everything that reads the design's PDK (CPW / λ/4 estimates, LOM, simulation exports) follows.
SUBSTRATE_KEYS = {"h": "substrate_height", "eps_r": "substrate_permittivity", "tan_d": "substrate_loss_tangent"}
_SUBSTRATE_RE = re.compile(r"^(?P<base>[^+]+)\+substrate\((?P<args>[^)]*)\)$")


def substrate_name(base: str, h: float | None = None, eps_r: float | None = None, tan_d: float | None = None) -> str:
    """The PDK name of ``base`` with its own substrate values (None / equal to the PDK's: left out; all left out: the
    plain ``base``)."""
    stack = get_pdk(base).stack
    parts = []
    for key, value in (("h", h), ("eps_r", eps_r), ("tan_d", tan_d)):
        if value is not None and abs(float(value) - float(getattr(stack, SUBSTRATE_KEYS[key]))) > 1e-15:
            parts.append(f"{key}={float(value):g}")
    return f"{base}+substrate({','.join(parts)})" if parts else base


@cache
def _with_substrate(name: str) -> Pdk:
    m = _SUBSTRATE_RE.match(name)
    if m is None:
        raise ValueError(f"unknown PDK {name!r}; known: {sorted(_PDKS)}")
    base = get_pdk(m["base"])
    values = {}
    for item in filter(None, (s.strip() for s in m["args"].split(","))):
        key, _, value = item.partition("=")
        if key.strip() not in SUBSTRATE_KEYS:
            raise ValueError(f"PDK {name!r}: unknown substrate key {key.strip()!r}; keys: {', '.join(SUBSTRATE_KEYS)}")
        values[SUBSTRATE_KEYS[key.strip()]] = float(value)
    return replace(base, name=name, stack=replace(base.stack, **values))


def get_pdk(name: str = DEFAULT_PDK) -> Pdk:
    try:
        return _PDKS[name]
    except KeyError as e:
        if "+substrate(" in str(name):
            return _with_substrate(name)
        raise ValueError(f"unknown PDK {name!r}; known: {sorted(_PDKS)}") from e


def register_pdk(pdk: Pdk) -> None:
    _PDKS[pdk.name] = pdk


__all__ = [
    "DEFAULT_PDK",
    "QCC_LAYERS",
    "QUANTCORE_NB_SAPPHIRE_V1",
    "QUANTCORE_NB_SI_V1",
    "CheeseRule",
    "CornerRounding",
    "KeepoutRule",
    "DieFrame",
    "JunctionProcess",
    "FabLayer",
    "Pdk",
    "Stack",
    "get_pdk",
    "substrate_name",
    "register_pdk",
]
