"""Pydantic schema for ``design.json`` (schema ``qcc/0.1``).

The design file is the single source of truth: geometry is always regenerated from it. Units are µm and degrees.
The structure follows gdsfactory's ``Netlist``/``Instance``/``Placement`` ideas, but cells are KQC Elements and
connections are KQC refpoint ports (``port_<name>`` + ``port_<name>_corner``).

Port references are strings ``"<instance>.<port>"``. The reserved instance name ``chip`` refers to chip-level ports
(e.g. launchers: ``"chip.WN"``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "qcc/0.1"
_ACCEPTED_SCHEMAS = {SCHEMA_VERSION, "qcd/0.1"}  # "qcd/0.1" is the name used before the rename to quantcore_circuits
CHIP = "chip"  # reserved instance name for chip-level ports


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def split_port_ref(ref: str) -> tuple[str, str]:
    """Split ``"Q1.claw_n"`` into ``("Q1", "claw_n")``."""
    inst, sep, port = ref.partition(".")
    if not sep or not inst or not port:
        raise ValueError(f"port reference {ref!r} must look like '<instance>.<port>'")
    return inst, port


class Place(_Model):
    """Placement of an instance: absolute (``at``/``rot``) or port-to-port snap (``snap``/``to``).

    For a snap, the instance is rotated so that its ``snap`` port faces the ``to`` port (outward directions
    anti-parallel) and translated so that both ports coincide; ``gap`` then pushes it out along the target port
    direction. ``rot`` is ignored for snaps; ``mirror`` is applied before solving the rotation.

    ``edge`` (``"n"``/``"s"``/``"e"``/``"w"``, or ``"auto"`` = the die edge nearest ``at``; absolute placements
    only) slides the instance perpendicular to that die edge so the outer edge of its etch sits the PDK's
    ``frame.pad_edge`` (100 µm) from it — the Quantcore pad rule; ``at`` keeps the position
    along the edge.
    """

    at: tuple[float, float] | None = None
    rot: float = 0.0
    mirror: bool = False
    snap: str | None = None
    to: str | None = None
    gap: float = 0.0
    edge: Literal["n", "s", "e", "w", "auto"] | None = None

    @model_validator(mode="after")
    def _one_mode(self):
        if (self.snap is None) != (self.to is None):
            raise ValueError("snap placement needs both 'snap' and 'to'")
        if self.snap is not None and self.at is not None:
            raise ValueError("use either 'at' or 'snap'/'to', not both")
        if self.snap is None and self.at is None:
            raise ValueError("placement needs 'at' or 'snap'/'to'")
        if self.edge is not None and self.snap is not None:
            raise ValueError("'edge' applies to absolute placements ('at'), not snaps")
        return self

    @property
    def is_snap(self) -> bool:
        return self.snap is not None


class PortSpec(_Model):
    """Explicit port of a static (freeform) cell. Direction is the outward direction in degrees."""

    name: str
    at: tuple[float, float]
    dir: float
    a: float | None = None
    b: float | None = None


class Junction(_Model):
    """Lumped junction values for the LOM and the simulations (not geometry or fab), fixed per component.

    ``Lj_nH`` is L_J at zero flux (a SQUID: both junctions in parallel), ``Cj_fF`` its capacitance. A SQUID also has
    ``flux_phi0`` (static flux Φ/Φ0) and ``asym`` (d = (I_c1 − I_c2)/(I_c1 + I_c2)); the defaults (0, 0) are a symmetric
    SQUID at its sweet spot. Each field also takes a list, one value per junction (the first one is used).
    Without ``Lj_nH`` the drawn trilayer junction's PDK value is used (``lom.fragment.effective_junction``).
    """

    Lj_nH: float | list[float] | None = None
    Cj_fF: float | list[float] = 0.0
    flux_phi0: float | list[float] = 0.0
    asym: float | list[float] = 0.0

    @field_validator("asym")
    @classmethod
    def _asym_range(cls, v):
        if any(abs(float(x)) > 1 for x in (v if isinstance(v, list) else [v])):
            raise ValueError(f"junction asym {v!r}: d = (I_c1 - I_c2)/(I_c1 + I_c2) lies in [-1, 1]")
        return v


class Instance(_Model):
    """A placed component.

    ``cell`` is a dotted class path (``"quantcore_circuits.layouts.Xmon"``,
    ``"kqcircuits.qubits.swissmon.Swissmon"``), a short name known to :mod:`quantcore_circuits.layouts` (``"Xmon"``),
    or ``"static:<path.oas>"`` for freeform cells with ``ports``.
    """

    cell: str
    params: dict[str, Any] = Field(default_factory=dict)
    place: Place
    ports: list[PortSpec] | None = None
    junction: Junction | None = None

    @model_validator(mode="after")
    def _static_ports(self):
        if self.cell.startswith("static:") and not self.ports:
            raise ValueError("static cells need an explicit 'ports' list")
        return self


class Waypoint(_Model):
    """A route waypoint with optional KQC ``Node`` extras (airbridge, taper, ...).

    ``r`` is the bend radius of the corner *at this waypoint only* (µm); the route's ``r`` applies to every other
    corner. ``None`` (default) uses the route radius.
    """

    at: tuple[float, float]
    airbridge: bool = False
    a: float | None = None
    b: float | None = None
    r: float | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class FreeEnd(_Model):
    """A route end that is not a port: a point, a direction (deg) and a termination gap.

    ``dir`` follows the port convention: it points from this end *towards the route* (for a resonator that ends
    heading down, ``dir`` is 90). ``term`` is the KQC termination length: 0 shorts the centre conductor to ground
    (λ/4 short end), a positive value leaves an open end with that gap.
    """

    at: tuple[float, float]
    dir: float | None = None
    term: float = 0.0


class HangerEnd(_Model):
    """End a route in a coupler running parallel to another route (e.g. a λ/4 resonator hanging off a feedline).

    The coupler is centred at arclength ``s`` (µm, measured along the target route's node polyline), on the ``side``
    (relative to the target route's direction of travel), separated from it by a ``ground_gap`` metal strip between the
    two CPW gaps. The route approaches the coupler perpendicularly at one end and terminates at the other:
    ``direction="forward"`` terminates downstream (in the target route's travel direction). ``end="short"`` grounds the
    termination (λ/4 short end), ``end="open"`` leaves an ``open_gap`` gap. ``bend=True`` (default) brings the
    route into the coupler with a 90° bend (perpendicular to the target route); ``bend=False`` enters it straight,
    along the coupler axis (the route must then arrive in line with the coupler).

    Instead of ``s``, ``near=(x, y)`` (µm, chip coordinates) centres the coupler at the point of the target route
    nearest to that point, so it stays put when the target route's start moves (e.g. a pad moved to the die edge).

    ``coupler_gap`` / ``line_gap`` (µm, None = the CPW's own gap ``b``) narrow the two gaps that face each other along
    the coupler: this route's gap on the line's side and the line's gap on this route's side. The centre lines come
    closer by what they save (stronger coupling at the same ``ground_gap`` strip); the outer gaps keep ``b``. The
    build draws the extra ground as ``base_metal_addition`` over the coupler length.
    """

    hanger: str
    s: float | None = None
    length: float
    near: tuple[float, float] | None = None
    side: Literal["left", "right"] = "left"
    ground_gap: float = 6.0
    direction: Literal["forward", "backward"] = "forward"
    end: Literal["short", "open"] = "short"
    open_gap: float = 6.0
    bend: bool = True
    coupler_gap: float | None = None
    line_gap: float | None = None

    @model_validator(mode="after")
    def _one_position(self):
        if (self.s is None) == (self.near is None):
            raise ValueError("hanger end needs exactly one of 's' (arclength) or 'near' (a point)")
        return self


RouteEndSpec = str | FreeEnd | HangerEnd


class Route(_Model):
    """A CPW connection between two ports, built with KQC ``WaveguideComposite``.

    ``type="meander"`` makes a fixed-``length`` route; the meander is inserted on ``meander_segment`` (default: the
    longest straight segment that is not part of a port stub or hanger coupler) using KQC
    ``Node(length_increment=...)``.
    """

    from_: str | FreeEnd = Field(alias="from")
    to: RouteEndSpec
    type: Literal["cpw", "meander"] = "cpw"
    nodes: list[tuple[float, float] | Waypoint] = Field(default_factory=list)
    length: float | None = None
    meander_segment: int | None = None
    meanders: int = -1
    meander_direction: Literal[1, -1] = 1  # which way the meander's first turn goes (KQC Node.meander_direction)
    a: float | None = None
    b: float | None = None
    r: float | None = None
    airbridges: Literal["auto", "none"] | int = "none"
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _meander_length(self):
        if self.type == "meander" and self.length is None:
            raise ValueError("meander routes need a 'length'")
        if isinstance(self.from_, FreeEnd) and isinstance(self.to, FreeEnd):
            raise ValueError("a route needs at least one port end")
        return self

    def waypoints(self) -> list[Waypoint]:
        return [n if isinstance(n, Waypoint) else Waypoint(at=n) for n in self.nodes]


class Launchers(_Model):
    """KQC sample-holder launchers with names: ``assign`` maps pad numbers to port names (KQC
    ``launcher_assignments``); only assigned pads are drawn unless ``enabled`` lists names to keep.

    ``type`` is a KQC sample holder ("ARD24", "SMA8", "DC24"). Any of ``n`` (pads in total, or ``[top, right,
    bottom, left]`` per side), ``launcher_type`` ("RF"/"DC"), ``width``, ``gap``, ``indent``, ``pitch`` and
    ``frame_gap`` (µm) override that preset, or, with ``type="custom"``, define the launchers outright (KQC
    ``produce_n_launchers``); then the chip keeps its own box.
    """

    type: str = "custom"  # noqa: A003
    assign: dict[int, str] = Field(default_factory=dict)
    enabled: list[str] | None = None
    n: int | list[int] | None = None
    launcher_type: Literal["RF", "DC"] | None = None
    width: float | None = None
    gap: float | None = None
    indent: float | None = None
    pitch: float | None = None
    frame_gap: float | None = None

    @model_validator(mode="after")
    def _custom_needs_geometry(self):
        if self.type == "custom" and self.n is None:
            raise ValueError("custom launchers need at least 'n' (and usually width, gap, indent, pitch)")
        return self


class Chip(_Model):
    """Chip-level settings, passed to the KQC ``Chip`` base class (``box``, ``with_grid``, ``name_chip``, ...)."""

    cell: str = "quantcore_circuits.assembly.DesignChip"
    box: tuple[float, float, float, float] = (0.0, 0.0, 10000.0, 10000.0)
    launchers: str | Launchers | None = None  # KQC sample holder type ("SMA8", "ARD24") or named launchers
    params: dict[str, Any] = Field(default_factory=dict)


class Coupling(_Model):
    """A lumped element the layout implies but no route or snap carries, e.g. two qubit arms facing each other.

    ``between`` holds two ends, each ``"<instance>"`` (its main island), ``"<instance>.<port>"``,
    ``"<instance>.<LOM node>"`` or ``"<route>"`` (the route's conductor, e.g. a hanger declared against a routed
    feedline). The LOM builder adds the element between those nodes; ``fem: True`` lets a C-matrix replace the value by
    island name.

    ``type: "wire"`` is a galvanic join with no element and no geometry: both ends must be ports
    (``"<instance>.<port>"``), their LOM nodes merge into one conductor, and the netlist check counts the pair as a
    declared connection. It is for cells whose metal overlaps instead of meeting port to port (legacy chips keep their
    absolute positions, e.g. a resonator end drawn inside an Xmon claw tail).
    """

    between: tuple[str, str]
    type: Literal["C", "L", "wire"] = "C"  # noqa: A003
    value: float | None = None  # fF for C, nH for L; None = estimate later / FEM only
    fem: bool = True
    note: str = ""

    @model_validator(mode="after")
    def _wire_ends_are_ports(self):
        if self.type == "wire":
            bad = [e for e in self.between if "." not in e]
            if bad:
                raise ValueError(f"wire coupling ends must be '<instance>.<port>': {bad}")
            if self.value is not None:
                raise ValueError("wire coupling takes no value")
        return self


class SimGroup(_Model):
    """A simulation sub-problem: the selected instances (plus routes between them) cut out with a margin."""

    select: list[str]
    margin_um: float = 300.0
    # decision #31: eigenmode/EPR is the default analysis (frequencies, participations); Q3D adds the capacitances
    analyses: list[str] = Field(default_factory=lambda: ["eigenmode_epr", "q3d_cmatrix"])
    # keep = do not cut (capacitance); edge = terminate a grounded line the box cuts (eigenmode / driven); cut = remove
    # the route for every analysis and end it at each selected instance with a short 50 Ω stub (subset simulation:
    # a bus to a qubit outside the subset, :mod:`quantcore_circuits.sim_tools.subset`)
    ports: dict[str, Literal["edge", "internal", "keep", "cut"]] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)


class Design(_Model):
    schema_: str = Field(SCHEMA_VERSION, alias="schema")
    name: str = "design"
    pdk: str = "quantcore_nb_sapphire_v1"
    chip: Chip = Field(default_factory=Chip)
    instances: dict[str, Instance] = Field(default_factory=dict)
    routes: dict[str, Route] = Field(default_factory=dict)
    nets: Literal["derived"] | list[list[str]] = "derived"
    targets: dict[str, dict[str, float]] = Field(default_factory=dict)
    sim_groups: dict[str, SimGroup] = Field(default_factory=dict)
    couplings: dict[str, Coupling] = Field(default_factory=dict)

    @field_validator("schema_")
    @classmethod
    def _schema(cls, v):
        if v not in _ACCEPTED_SCHEMAS:
            raise ValueError(f"unsupported design schema {v!r}; expected {SCHEMA_VERSION!r}")
        return SCHEMA_VERSION

    @field_validator("instances")
    @classmethod
    def _reserved(cls, v):
        if CHIP in v:
            raise ValueError(f"'{CHIP}' is a reserved instance name")
        return v

    @model_validator(mode="after")
    def _references(self):
        known = set(self.instances) | {CHIP}
        for name, inst in self.instances.items():
            if inst.place.is_snap:
                own, _ = split_port_ref(inst.place.snap) if "." in inst.place.snap else (name, inst.place.snap)
                if own != name:
                    raise ValueError(f"{name}: snap port {inst.place.snap!r} must belong to {name}")
                target, _ = split_port_ref(inst.place.to)
                if target not in known:
                    raise ValueError(f"{name}: snap target {inst.place.to!r} refers to unknown instance")
        for name, route in self.routes.items():
            for end in (route.from_, route.to):
                if isinstance(end, str) and split_port_ref(end)[0] not in known:
                    raise ValueError(f"route {name}: {end!r} refers to unknown instance")
                if isinstance(end, HangerEnd) and end.hanger not in self.routes:
                    raise ValueError(f"route {name}: hanger target {end.hanger!r} is not a route")
                if isinstance(end, HangerEnd) and end.hanger == name:
                    raise ValueError(f"route {name}: cannot hang off itself")
        for cname, c in self.couplings.items():
            for end in c.between:
                head = end.split(".", 1)[0]
                if head not in self.instances and not (c.type != "wire" and end in self.routes):
                    raise ValueError(f"coupling {cname}: {end!r} refers to unknown instance or route")
        for gname, group in self.sim_groups.items():
            for sel in group.select:
                if sel not in self.instances and sel not in self.routes:
                    raise ValueError(f"sim group {gname}: unknown instance/route {sel!r}")
        return self

    def to_json_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json", by_alias=True, exclude_defaults=False)
        if not data["couplings"]:  # optional section: designs without it keep their JSON (and hash) unchanged
            del data["couplings"]
        for inst in data["instances"].values():
            if inst["place"].get("edge") is None:
                inst["place"].pop("edge", None)
            junction = inst.get("junction")
            if isinstance(junction, dict):  # flux / asymmetry at the default (0) stay out of the file
                for key in ("flux_phi0", "asym"):
                    if junction.get(key) == 0 and not isinstance(junction.get(key), list):
                        junction.pop(key, None)
        for route in data["routes"].values():  # optional route options at their defaults stay out of the file
            if route.get("meander_direction") == 1:
                route.pop("meander_direction")
            for node in route.get("nodes") or []:  # per-corner radius: optional, absent when unset
                if isinstance(node, dict) and node.get("r") is None:
                    node.pop("r", None)
            for end in (route.get("from"), route.get("to")):
                if isinstance(end, dict) and end.get("bend") is True:
                    end.pop("bend")
                if isinstance(end, dict) and "hanger" in end:
                    for key in ("near", "s"):
                        if end.get(key) is None:
                            end.pop(key, None)
        launchers = data["chip"].get("launchers")
        if isinstance(launchers, dict):  # launcher overrides are optional too: unset ones stay out of the file
            for key in ("n", "launcher_type", "width", "gap", "indent", "pitch", "frame_gap"):
                if launchers.get(key) is None:
                    launchers.pop(key, None)
        return data
