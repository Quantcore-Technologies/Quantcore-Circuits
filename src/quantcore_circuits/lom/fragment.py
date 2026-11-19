"""LOM fragments: the lumped model of one layout component, and how its layout ports attach to it.

A component's LOM model is a :class:`Fragment` built from the instance (cell parameters, junction values, PDK):

* ``nodes`` — local node name → ``{"island": FEM net label}`` (e.g. ``"island"`` → ``"Q1.island"``). Local names
  ``island`` / ``island1`` / ``island2`` are qubit islands (a floating transmon has two), ``pad`` a 50 Ω port
  conductor; anything else is a coupler / line conductor,
* ``elements`` — lumped branches between local nodes or ``"gnd"`` with an *estimated* value (see
  :mod:`.estimates` and :mod:`.calibration`), and the ``fem`` source that can replace the estimate (``"cmatrix"``),
* ``port_nodes`` — layout port → local node; ``"gnd"`` for galvanically grounded ports; ``"control:<kind>"`` for
  ports that carry a control line (flux bias, drive) rather than a circuit connection,
* ``lines`` — distributed CPW sections inside the component (a resonator, a meander, a plain waveguide). The
  builder decides what a line is once it knows what its ends connect to (wire, λ/4 or λ/2 resonator), and it adds
  the length of routes that continue the line (see :class:`Line`).
* ``hangers`` — coupled-line sections of a line to a conductor *outside* the component that no port carries (a
  legacy resonator whose coupler runs next to a separate feedline cell). A design coupling without a value between
  the instance (or its line node) and that conductor (``d.couple("K_R1", "R1", "FL")``) becomes the ``HANGER``
  element; each entry is ``{"line": <line name>, "coupling_length_um", "ground_gap_um", "end": "short"|"open"}``
  (the line end the section is at), optionally ``"source"``.
* ``straps`` — local nodes that are ground straps when no port on them is joined (route, wire coupling or snap):
  an airbridge over a waveguide lands on the ground plane on both sides, so its ports map to ``gnd`` (no element).

Cells declare their model with a ``qcc_lom(name, instance, pdk) -> Fragment`` classmethod, or are registered with
:func:`register_lom` (KQC cells: :mod:`.kqc_models`; Quantum Metal wrapper cells ``"metal:<Class>"``:
:mod:`.metal_models`; ported legacy cells: :mod:`.quantcore_models`). Cells without a model get one bare node per
port (and a note).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field

QUBIT_NODES = ("island", "island1", "island2")


@dataclass
class Element:
    name: str  # global branch name, e.g. "C_Q1", "Cg_Q1_claw_n"
    type: str  # C | L | JJ | SQUID | R | TLres | HANGER
    nodes: tuple[str, str]  # local node names or "gnd"
    value: dict  # e.g. {"estimate": 64.1, "unit": "fF", "fem": "cmatrix"} or {"Lj_nH": 12, "Cj_fF": 2}
    knob: dict | None = None  # {"param": "Q1.cross_length"}
    note: str = ""


@dataclass
class Line:
    """A CPW section inside a component, on local node ``node`` (one conductor: both ends are that node).

    ``ports`` are the layout ports at its two ends (``None`` for an end inside the component, e.g. the coupling
    capacitor of a KQC ``QuarterWaveCpwResonator``). ``term`` is what each end is when nothing connects to it:
    ``"short"`` (KQC waveguides with ``term = 0`` end in the ground plane), ``"open"`` (a termination gap or a
    coupling capacitor). ``resonator=True`` makes it a resonator whatever its ends connect to (a meander between two
    couplers is a λ/2 bus); otherwise a line between two connected conductors is a wire and only a line with a free
    end is a (stub) resonator. ``couplings`` are coupled-line sections to other local nodes (a hanger:
    ``{"node": "pl", "coupling_length_um": 500, "ground_gap_um": 10}``).

    Lines joined end to end (a route between two line ports, a wire coupling or snap between them, a termination on
    a line end) are one line for the builder. ``through=True`` marks a pass-through section (a taper, an airbridge
    crossing): it only extends whatever line it joins, which is named after its main line or route, not after it
    (``length_um`` 0: the builder takes the distance between its two ports).
    """

    name: str
    node: str
    ports: tuple[str | None, str | None]
    length_um: float
    a_um: float
    b_um: float
    term: tuple[str, str] = ("short", "short")
    resonator: bool = False
    couplings: list[dict] = field(default_factory=list)
    knob: str | None = None  # instance parameter for the line length, e.g. "Q1R.resonator_length"
    through: bool = False  # a pass-through section (taper): extends the line it joins, never names it


@dataclass
class Fragment:
    nodes: dict[str, dict] = field(default_factory=dict)
    elements: list[Element] = field(default_factory=list)
    port_nodes: dict[str, str] = field(default_factory=dict)
    knobs: dict[str, tuple[float, float]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)
    hangers: list[dict] = field(default_factory=list)  # see the module docstring
    straps: list[str] = field(default_factory=list)  # local nodes grounded when no port on them is joined


LomFn = Callable[[str, object, object], Fragment]
_REGISTRY: dict[str, LomFn] = {}
METAL_PREFIX = "metal:"


def register_lom(cell_name: str):
    """Decorator: ``@register_lom("Swissmon") def swissmon_lom(name, inst, pdk) -> Fragment``.

    KQC/Quantcore cells are registered by class name (subclasses inherit the model); Quantum Metal wrapper cells by
    ``"metal:<MetalClass>"``.
    """

    def deco(fn: LomFn) -> LomFn:
        _REGISTRY[cell_name] = fn
        return fn

    return deco


def registered() -> dict[str, LomFn]:
    """All registered LOM models (cell / ``metal:`` class name → model function)."""
    _load_models()
    return dict(_REGISTRY)


def _load_models() -> None:
    # model modules register on import; they are imported lazily to keep lom.fragment import-light
    from quantcore_circuits.lom import kqc_models, metal_models, quantcore_models  # noqa: F401  pylint: disable=C0415


def metal_class(cell_ref: str) -> str | None:
    """Metal class name of a wrapper cell reference (``"metal:TransmonPocket"`` → ``"TransmonPocket"``)."""
    if cell_ref.startswith(METAL_PREFIX):
        return cell_ref[len(METAL_PREFIX) :]
    return None


def lom_model(cell_ref: str) -> LomFn | None:
    """The LOM model of a cell reference, or None (static cells, unknown cells, cells without a model)."""
    if cell_ref.startswith("static:"):
        return None
    _load_models()
    mc = metal_class(cell_ref)
    if mc is not None:
        try:  # spelling variants (case, module name) → the qlibrary class name
            from quantcore_circuits.layouts.metal import canonical_class_name  # pylint: disable=C0415

            mc = canonical_class_name(mc)
        except (ImportError, ValueError):
            pass
        return _REGISTRY.get(f"{METAL_PREFIX}{mc}") or _metal_by_mro(mc)
    from quantcore_circuits.layouts.registry import resolve_cell  # pylint: disable=import-outside-toplevel

    try:
        cls = resolve_cell(cell_ref)
    except ValueError:
        return None
    fn = getattr(cls, "qcc_lom", None)
    if fn is not None:
        return fn
    for klass in cls.__mro__:
        if klass.__name__ in _REGISTRY:
            return _REGISTRY[klass.__name__]
    return None


def _metal_by_mro(metal_cls: str) -> LomFn | None:
    """A Metal class without its own model inherits its base class's (e.g. a user subclass of TransmonPocket)."""
    try:
        from quantcore_circuits.lom.metal_models import metal_mro  # pylint: disable=import-outside-toplevel

        for base in metal_mro(metal_cls):
            if f"{METAL_PREFIX}{base}" in _REGISTRY:
                return _REGISTRY[f"{METAL_PREFIX}{base}"]
    except ImportError:
        return None
    return None


def generic_fragment(name: str, inst, ports: list[str]) -> Fragment:
    """No LOM model: every layout port becomes its own bare node (connectivity is kept, values are not)."""
    frag = Fragment(nodes={p: {} for p in ports}, port_nodes={p: p for p in ports})
    frag.notes.append(f"{name} ({inst.cell}) has no LOM model: its ports are bare nodes without elements")
    return frag


# ---- helpers shared by the model modules ----------------------------------------------------------------------------
def cell_params(inst) -> dict:
    """Cell parameter defaults merged with the instance's parameters (KQC / Quantcore cells), with the junction the
    build draws: an unset KQC default ``junction_type`` (``"Manhattan"``, ...) is the PDK trilayer junction
    (``assembly.plan.pdk_junction_type``), so the LOM and the simulations take the drawn junction's PDK value."""
    from quantcore_circuits.assembly.plan import pdk_junction_type  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.layouts.registry import resolve_cell  # pylint: disable=import-outside-toplevel

    cls = resolve_cell(inst.cell)
    params = {k: v.default for k, v in cls.get_schema().items()} | dict(inst.params)
    pdk_jt = pdk_junction_type(cls, dict(inst.params))
    if pdk_jt is not None:
        params["junction_type"] = pdk_jt
    return params


def _first(v, default=None):
    """The first entry of a per-junction list, or the value itself."""
    if isinstance(v, (list, tuple)):
        return v[0] if v else default
    return default if v is None else v


def junction_values(inst) -> tuple[float | None, float]:
    """(Lj nH or None, Cj fF) of an instance (first entry when the design gives a list per junction)."""
    j = getattr(inst, "junction", None)
    lj = _first(j.Lj_nH) if j else None
    cj = _first(j.Cj_fF, 0.0) if j else 0.0
    return (None if lj is None else lj), float(cj or 0.0)


def squid_l_eff(lj0_nH: float, flux_phi0: float = 0.0, asym: float = 0.0) -> float:
    """L of a DC SQUID (no loop inductance) at flux Φ/Φ0 with asymmetry d:
    L_J0 / (|cos πΦ| √(1 + d² tan² πΦ)) = L_J0 / √(cos² πΦ + d² sin² πΦ). Raises at Φ = ½ with d = 0 (no finite L)."""
    from quantcore_circuits.analysis.amplifiers import squid_ls  # pylint: disable=import-outside-toplevel

    x = math.pi * float(flux_phi0)
    if math.cos(x) ** 2 + float(asym) ** 2 * math.sin(x) ** 2 < 1e-24:
        raise ValueError(
            f"a symmetric SQUID (d = {asym:g}) at Φ = {flux_phi0:g} Φ0 has no finite L_J: move flux_phi0 off ½ or set "
            "junction.asym"
        )
    return float(squid_ls(float(lj0_nH), float(flux_phi0), float(asym)))


@dataclass(frozen=True)
class EffectiveJunction:
    """A component's junction as the LOM and every simulation take it (lumped, fixed at design time).

    ``lj0_nH``: L_J at zero flux (a SQUID: both junctions in parallel); ``lj_eff_nH``: at ``flux_phi0`` with
    asymmetry ``asym`` (a single JJ: ``lj0_nH``); None when nothing gives a value. ``kind``: ``"JJ"``, ``"SQUID"``
    or None (no junction). ``source``: ``"design"``, ``"drawn <type> (PDK junction rule)"``, a model's own fallback
    (e.g. a Metal option), or None.
    """

    lj0_nH: float | None
    cj_fF: float = 0.0
    flux_phi0: float = 0.0
    asym: float = 0.0
    kind: str | None = "JJ"
    source: str | None = None

    @property
    def lj_eff_nH(self) -> float | None:
        if self.lj0_nH is None or self.kind != "SQUID":
            return self.lj0_nH
        return squid_l_eff(self.lj0_nH, self.flux_phi0, self.asym)

    def as_dict(self) -> dict:
        """Plain JSON (the build sidecar's ``instances.<name>.junction``)."""
        out = {"kind": self.kind, "Lj0_nH": self.lj0_nH, "Cj_fF": self.cj_fF, "flux_phi0": self.flux_phi0,
               "asym": self.asym, "Lj_eff_nH": None, "source": self.source}
        try:
            out["Lj_eff_nH"] = self.lj_eff_nH
        except ValueError as e:
            out["error"] = str(e)
        return out

    def describe(self) -> str:
        """``junction L 6.734 nH, C 15 fF (drawn Quantcore Squid, PDK junction rule; Φ = 0, d = 0)``."""
        src = re.sub(r" \((.*)\)$", r", \1", self.source or "no value")
        lj = self.lj_eff_nH
        head = "junction L " + ("none" if lj is None else f"{lj:.4g} nH")
        if self.kind == "SQUID" and lj is not None and abs(lj - self.lj0_nH) > 1e-9:
            head += f" (L_J0 {self.lj0_nH:.4g} nH)"
        tail = f"Φ = {self.flux_phi0:g}, d = {self.asym:g}" if self.kind == "SQUID" else "single junction"
        return f"{head}, C {self.cj_fF:g} fF ({src}; {tail})"


def effective_junction(inst, params: dict | None = None, pdk=None, kind: str | None = None) -> EffectiveJunction:
    """The junction values of an instance: the design's ``junction`` (L_J0, C_J, Φ, d; first entry of a list), else
    the drawn trilayer junction on the PDK junction rule (:func:`drawn_junction` of ``params``), else no L.

    ``params``: the cell parameters the drawn junction is read from (``junction_type``, ``junction_params``,
    ``junction_width``); None: the cell defaults merged with the instance's. ``kind``: ``"JJ"`` / ``"SQUID"`` / None
    as the model knows it; None derives it from ``junction_type``. ``pdk``: a junction process for the drawn values
    (None: the default Quantcore process, which the layout cells draw with). Φ and d are design values whatever gives
    L_J (they are simulation values, not fab values).
    """
    if params is None:
        try:
            params = cell_params(inst)
        except Exception:  # noqa: BLE001  (an unknown / wrapped cell: its own parameters)
            params = dict(getattr(inst, "params", None) or {})
    if kind is None:
        kind = junction_kind(params.get("junction_type", ""))
    j = getattr(inst, "junction", None)
    flux = float(_first(j.flux_phi0, 0.0) or 0.0) if j else 0.0
    asym = float(_first(j.asym, 0.0) or 0.0) if j else 0.0
    if kind is None:
        return EffectiveJunction(None, 0.0, flux, asym, None, None)
    lj, cj = junction_values(inst)
    source = "design" if lj is not None else None
    if lj is None:
        drawn = drawn_junction(params, getattr(pdk, "junction", pdk))
        if drawn is not None:
            lj, cj, source = drawn
    return EffectiveJunction(None if lj is None else float(lj), float(cj or 0.0), flux, asym, kind, source)


def junction_from_element(el: Element) -> EffectiveJunction:
    """The :class:`EffectiveJunction` of a model's ``JJ`` / ``SQUID`` element (``Lj_nH`` is L_J0; an amplifier that
    applies its own static bias keeps L_J0 in ``Lj0_nH`` and the bias in ``bias_phi0``)."""
    v = el.value or {}
    lj0 = v.get("Lj0_nH", v.get("Lj_nH"))
    flux = v.get("bias_phi0", v.get("flux_phi0", 0.0))
    return EffectiveJunction(
        None if lj0 is None else float(lj0),
        float(v.get("Cj_fF") or 0.0),
        float(flux or 0.0),
        float(v.get("asym") or 0.0),
        el.type,
        v.get("source") if lj0 is not None else None,
    )


def instance_junction(name: str, inst, pdk=None) -> EffectiveJunction | None:
    """The junction of a placed component as its LOM model gives it (its ``JJ`` / ``SQUID`` element: the export uses
    the same L_J0, C_J, Φ, d as the LOM). None: the component has no junction (its model has no such element, or a
    cell without a model is a Metal wrapper or has no ``junction_type``); another cell without a model and with a
    ``junction_type`` gets :func:`effective_junction`."""
    fn = lom_model(inst.cell)
    if fn is not None:
        if pdk is None or isinstance(pdk, str):
            from quantcore_circuits.pdk import get_pdk  # pylint: disable=import-outside-toplevel

            pdk = get_pdk(pdk) if pdk else get_pdk()
        try:
            frag = fn(name, inst, pdk)
        except Exception:  # noqa: BLE001  (a model that cannot evaluate: the design / drawn values below)
            frag = None
        if frag is not None:
            el = next((e for e in frag.elements if e.type in ("JJ", "SQUID")), None)
            return junction_from_element(el) if el is not None else None
    if metal_class(inst.cell) is not None:  # every Metal wrapper has a junction_type; only its model knows a junction
        return None
    try:
        params = cell_params(inst)
    except Exception:  # noqa: BLE001
        params = dict(getattr(inst, "params", None) or {})
    if "junction_type" not in params:
        return None
    return effective_junction(inst, params)


def missing_junction_message(name: str, inst, ej: EffectiveJunction | None = None) -> str:
    """Why ``name`` has no junction L_J and where to set it (KLayout component dialog or design.json)."""
    try:
        params = cell_params(inst)
    except Exception:  # noqa: BLE001
        params = dict(getattr(inst, "params", None) or {})
    err = ej.as_dict().get("error") if ej is not None and ej.lj0_nH is not None else None
    if err:  # a value without a finite L (Φ = ½, d = 0)
        return f"{name}: {err} (instances.{name}.junction)"
    jt = params.get("junction_type")
    if jt:
        try:
            from kqcircuits.junctions import junction_type_choices  # pylint: disable=import-outside-toplevel
        except ImportError:
            junction_type_choices = []
        why = f"its {'KQC ' if jt in junction_type_choices else ''}{jt} junction has no PDK value"
    else:
        why = "no design value and no drawn trilayer junction"
    return (f"{name}: no junction L_J ({why}): set it in KLayout (component dialog ▸ Junction) or "
            f"instances.{name}.junction.Lj_nH")


def junction_kind(junction_type: str) -> str | None:
    """``"SQUID"``, ``"JJ"`` or None (no junction) from a KQC/Quantcore ``junction_type`` name."""
    jt = str(junction_type or "").lower()
    if jt in ("no squid", "nosquid", "none"):
        return None
    if jt in ("manhattan", "sim squid") or ("squid" in jt and "single" not in jt):
        return "SQUID"
    return "JJ"


def drawn_junction(params: dict, process=None) -> tuple[float, float, str] | None:
    """(L_J nH, C_J fF, source) of the trilayer junction a qubit draws — its ``junction_type`` is a trilayer cell
    (``"Quantcore Junction"``, ``"Trilayer Squid"``, ...), sized by ``junction_params`` (Xmon, ``metal:``) or KQC
    ``junction_width`` — on the PDK junction rule (``process``: a junction process; None the default); None for other
    junction types."""
    jt = (params or {}).get("junction_type")
    if not jt:
        return None
    from quantcore_circuits.layouts.junctions.trilayer import trilayer_junction_values  # pylint: disable=C0415

    jp = params.get("junction_params") or {}
    if isinstance(jp, str):
        import ast  # pylint: disable=import-outside-toplevel
        import json  # pylint: disable=import-outside-toplevel

        try:
            jp = json.loads(jp or "{}")
        except ValueError:
            jp = ast.literal_eval(jp)
    if "junction_width" in params:
        jp = {"junction_width": params["junction_width"], **jp}
    values = trilayer_junction_values(str(jt), jp, process)
    if values is None:
        return None
    return round(values.lj_nH, 4), round(values.cj_fF, 3), f"drawn {jt} (PDK junction rule)"


def junction_value(ej: EffectiveJunction) -> dict:
    """A ``JJ`` / ``SQUID`` element value: ``Lj_nH`` (L_J0), ``Cj_fF``, ``source`` and, for a SQUID, ``asym`` and
    ``flux_phi0`` (the LOM applies them when it fills the circuit: :func:`squid_l_eff`)."""
    value = {"Lj_nH": ej.lj0_nH, "Cj_fF": ej.cj_fF, "source": ej.source or "design"}
    if ej.kind == "SQUID":
        value |= {"asym": ej.asym, "flux_phi0": ej.flux_phi0}
    return value


def junction_element(
    name: str, a: str, b: str, inst, kind: str = "JJ", note: str = "", drawn_params: dict | None = None
) -> Element:
    """The ``J_<name>`` element of a qubit between nodes a and b (:func:`effective_junction`: the design's
    ``junction``, else the drawn trilayer junction of ``drawn_params`` — None: the cell's merged parameters)."""
    ej = effective_junction(inst, drawn_params, kind=kind)
    return Element(f"J_{name}", kind, (a, b), junction_value(ej), {"param": f"{name}.junction.Lj_nH"}, note)


def port_resistor(name: str, node: str = "pad", r_ohm: float = 50.0, note: str = "") -> Element:
    return Element(f"Port_{name}", "R", (node, "gnd"), {"R_ohm": r_ohm, "source": "design"}, note=note)
