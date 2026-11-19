"""Code-first chip design (Metal-style), drawn live in KLayout as you type.

>>> d = Designer("q1_r1", box=(0, 0, 7500, 7500), chip={"name_chip": "Q1R1"}, live=True)   # opens KLayout
>>> pw = d.add("PAD_W", "BondPad", at=(1125, 3750), rot=270)
>>> pe = d.add("PAD_E", "BondPad", at=(6375, 3750), rot=90)
>>> fl = d.route("FL", pw.a, pe.a)                                       # ports are attributes
>>> q1 = d.add("Q1", "Xmon", at=(2975, 2200), cross_length=300, junction={"Lj_nH": 12, "Cj_fF": 2})
>>> d.route("R1", q1.claw_n, fl.hanger(s=2000, length=300, side="right"), meander=4200)
>>> d.save("examples/my_chip.json"); d.lom().model                       # design.json and its lumped circuit

Every ``add``/``route``/``set`` validates immediately (unknown cells, parameters or ports raise with the list of
valid ones) and, with ``live=True``, rebuilds the chip (≈0.1 s warm), writes ``build/<name>.oas`` + sidecar and
reloads KLayout through klive. A change that cannot be routed yet (e.g. a route to a component not placed yet) keeps
the last good layout and prints why. ``with d.batch():`` groups changes into one rebuild. The result is an ordinary
``design.json``, so the KLayout plugin, ``qcc watch``, simulation and analysis all work on it unchanged.
"""

from __future__ import annotations

import contextlib
import copy
import json
import time
from functools import lru_cache
from pathlib import Path

from quantcore_circuits.pdk import DEFAULT_PDK


class PortRef(str):
    """``"Q1.claw_n"`` with the port's geometry attached (``.pos``, ``.dir``, ``.a``, ``.b`` in the local frame)."""

    def __new__(cls, ref: str, port=None):
        obj = super().__new__(cls, ref)
        obj.port = port
        return obj


@lru_cache(maxsize=256)
def _ports(cell: str, params_json: str) -> dict:
    from quantcore_circuits.assembly.plan import pcell_params  # pylint: disable=C0415
    from quantcore_circuits.layouts.registry import element_ports, resolve_cell  # pylint: disable=C0415

    if cell.startswith("static:"):
        return {}
    cls = resolve_cell(cell)
    return element_ports(cls, **pcell_params(cls, json.loads(params_json)))


class InstanceHandle:
    def __init__(self, designer: Designer, name: str):
        self._d, self.name = designer, name

    @property
    def spec(self) -> dict:
        return self._d.data["instances"][self.name]

    @property
    def ports(self) -> dict:
        return _ports(self.spec["cell"], json.dumps(self.spec.get("params", {}), sort_keys=True))

    def __getattr__(self, port: str) -> PortRef:
        if port.startswith("_"):
            raise AttributeError(port)
        ports = self.ports
        if port not in ports:
            raise AttributeError(f"{self.name} ({self.spec['cell']}) has no port {port!r}; ports: {sorted(ports)}")
        return PortRef(f"{self.name}.{port}", ports[port])

    def __getitem__(self, port: str) -> PortRef:
        return self.__getattr__(port)

    def set(self, **params) -> InstanceHandle:
        """Change cell parameters (``at=`` / ``rot=`` are accepted too; ``junction=`` replaces the junction dict,
        e.g. ``{"Lj_nH": 7.0, "flux_phi0": 0.2, "asym": 0.1}``)."""
        with self._d._change(f"set {self.name}"):
            spec = self.spec
            place = spec["place"]
            for k in ("at", "rot", "mirror", "edge"):
                if k in params:
                    place.pop("snap", None)
                    place.pop("to", None)
                    place[k] = list(params.pop(k)) if k == "at" else params.pop(k)
            if "junction" in params:
                spec["junction"] = dict(params.pop("junction"))
            spec.setdefault("params", {}).update(params)
        return self

    def move(self, at=None, rot=None, edge: str | None = None) -> InstanceHandle:
        """Move / rotate; ``edge`` ("n"/"s"/"e"/"w"/"auto") puts the outer edge of the etch at the PDK pad distance
        (``frame.pad_edge``, 100 µm) from that die edge."""
        kw = {k: v for k, v in (("at", at), ("rot", rot), ("edge", edge)) if v is not None}
        return self.set(**kw)

    def __repr__(self) -> str:
        return f"<{self.spec['cell']} {self.name} ports={sorted(self.ports)}>"


class RouteHandle:
    def __init__(self, designer: Designer, name: str):
        self._d, self.name = designer, name

    @property
    def spec(self) -> dict:
        return self._d.data["routes"][self.name]

    def hanger(
        self,
        s: float | None = None,
        length: float = 300.0,
        side: str = "left",
        ground_gap: float = 6.0,
        direction: str = "forward",
        end: str = "short",
        open_gap: float = 6.0,
        bend: bool = True,
        near=None,
        coupler_gap: float | None = None,
        line_gap: float | None = None,
    ) -> dict:
        """End spec for a λ/4 coupler running along this route (use as another route's ``end``). ``bend=False``
        enters the coupler straight instead of with a 90° bend; ``direction`` flips which end is terminated.
        ``near=(x, y)`` instead of ``s`` centres the coupler at the point of this route nearest to (x, y).
        ``coupler_gap`` / ``line_gap`` narrow the two facing gaps along the coupler (closer, stronger coupling)."""
        spec = {
            "hanger": self.name,
            "s": s,
            "length": length,
            "side": side,
            "ground_gap": ground_gap,
            "direction": direction,
            "end": end,
            "open_gap": open_gap,
            "bend": bend,
        }
        for key, value in (("coupler_gap", coupler_gap), ("line_gap", line_gap)):
            if value is not None:
                spec[key] = value
        if near is not None:
            spec["near"] = list(near)
            spec.pop("s")
        elif s is None:
            raise ValueError("hanger(...) needs s= (arclength along this route) or near=(x, y)")
        return spec

    def set(self, **kw) -> RouteHandle:
        with self._d._change(f"set {self.name}"):
            for k, v in kw.items():
                if v is None:
                    self.spec.pop(k, None)
                else:
                    self.spec["length" if k == "meander" else k] = v
            if "meander" in kw:
                self.spec["type"] = "meander"
        return self

    @property
    def length(self) -> float | None:
        r = self._d.result
        return r.route_lengths().get(self.name) if r else None

    def __repr__(self) -> str:
        return f"<route {self.name}: {self.spec['from']} → {self.spec['to']}>"


class Designer:
    def __init__(
        self,
        name: str,
        box=(0.0, 0.0, 10000.0, 10000.0),
        pdk: str = DEFAULT_PDK,
        chip: dict | None = None,
        launchers: str | dict | None = None,
        live: bool = False,
        out: str | Path | None = None,
        delay: float = 0.0,
        open_klayout: bool | None = None,
        verbose: bool = True,
    ):
        """``live=True``: every change is rebuilt and redrawn in KLayout (klive). ``open_klayout`` (default: the
        ``QCC_KLAYOUT_GUI`` switch, on) starts KLayout when it is not running — also again after its window was
        closed — and raises its window on the first build; False only redraws a KLayout that is already open."""
        self.data: dict = {
            "schema": "qcc/0.1",
            "name": name,
            "pdk": pdk,
            "chip": {"box": list(box), "launchers": launchers, "params": {"with_grid": False, **(chip or {})}},
            "instances": {},
            "routes": {},
            "targets": {},
            "sim_groups": {},
            "couplings": {},
        }
        self.live, self.delay, self.verbose = live, delay, verbose
        self.out = Path(out) if out else Path("build") / f"{name}.oas"
        self.result = None
        self.history: list[str] = []
        self._batch = 0
        self._dirty = False
        self._open = open_klayout  # None: QCC_KLAYOUT_GUI decides at each build
        self._front = True  # raise the KLayout window on the first live build
        self._kl_pid: int | None = None  # the KLayout this designer started
        self._kl_hint = False
        self._autosave = True  # only Designer.load sets a path; see load()
        self.path: Path | None = None

    # ---- construction ------------------------------------------------------------------------------------------
    @classmethod
    def load(cls, source, autosave: bool | None = None, **kw) -> Designer:
        """Open a saved design. ``autosave`` (default: the ``live`` setting) writes every rebuild back to ``source``:
        on in a live KLayout session, so the plugin and ``qcc watch`` see your edits; off in scripts, tests and
        ``QCC_LIVE=0`` notebooks, so loading a design never rewrites it by accident (``d.save(path)`` still does)."""
        from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

        design = load_design(source)
        d = cls(design.name, **kw)
        d._autosave = d.live if autosave is None else bool(autosave)
        d.data = design.to_json_dict()
        for key in ("instances", "routes", "targets", "sim_groups", "couplings"):  # omitted when empty on disk
            d.data.setdefault(key, {})
        d.path = Path(source) if isinstance(source, (str, Path)) else None
        if d.live:
            d.show()
        return d

    def add(
        self,
        name: str,
        cell,
        at=None,
        rot: float = 0.0,
        mirror: bool = False,
        snap: str | None = None,
        to: str | None = None,
        snap_gap: float = 0.0,
        junction: dict | None = None,
        edge: str | None = None,
        **params,
    ) -> InstanceHandle:
        """Place a component: ``cell`` is a class (``Xmon``) or name; ``params`` are its PCell parameters.

        Absolute placement with ``at``/``rot``, or port snap with ``snap="port"`` (own port) and ``to=`` another
        instance's port (``q1.claw_n``, optional ``snap_gap``); the rebuild solves the rotation. ``edge`` ("n", "s",
        "e", "w" or "auto") applies the Quantcore pad rule to an absolute placement: the instance slides
        perpendicular to that die edge until the outer edge of its etch is the PDK pad distance (PDK
        ``frame.pad_edge``, 100 µm) from it. ``junction`` holds the lumped junction values for the LOM and the
        simulations: ``{"Lj_nH", "Cj_fF", "flux_phi0", "asym"}`` (L_J at zero flux, C_J, a SQUID's flux Φ/Φ0 and
        asymmetry d; without ``Lj_nH`` the drawn trilayer junction's PDK value is used). All other keyword arguments
        are cell parameters (e.g. the Xmon's ``gap``).
        """
        cell_name = cell if isinstance(cell, str) else cell.__name__
        self._check_cell(cell_name, params)
        if name in self.data["instances"] or name in self.data["routes"]:
            raise ValueError(f"{name!r} already exists")
        if to is not None:
            place = {"snap": snap if snap and "." in snap else f"{name}.{snap or 'a'}", "to": str(to)}
            if snap_gap:
                place["gap"] = snap_gap
            if mirror:  # applied before the snap rotation is solved (see design.schema.Place)
                place["mirror"] = True
        else:
            place = {"at": list(at or (0.0, 0.0)), "rot": rot}
            if mirror:
                place["mirror"] = True
            if edge:
                place["edge"] = edge
        spec = {"cell": cell_name, "params": params, "place": place}
        if junction:
            spec["junction"] = dict(junction)
        with self._change(f"add {name} ({cell_name})"):
            self.data["instances"][name] = spec
        return InstanceHandle(self, name)

    def array(
        self,
        name: str,
        cell,
        origin=(0.0, 0.0),
        pitch=(100.0, 100.0),
        shape=(1, 1),
        rot: float = 0.0,
        vary: dict | None = None,
        **params,
    ) -> list[InstanceHandle]:
        """Place ``shape = (columns, rows)`` copies of a cell on a grid (test-pad and junction arrays).

        Instances are named ``<name>_<col>_<row>``. ``vary`` maps a parameter to one value per copy (column-major,
        e.g. a junction-width sweep); the other ``params`` are shared.
        """
        (nx, ny), (px, py) = shape, pitch
        handles = []
        with self.batch():
            for i in range(nx):
                for j in range(ny):
                    k = i * ny + j
                    own = dict(params) | {p: v[k] for p, v in (vary or {}).items()}
                    at = (origin[0] + i * px, origin[1] + j * py)
                    handles.append(self.add(f"{name}_{i}_{j}", cell, at=at, rot=rot, **own))
        return handles

    @property
    def chip_ports(self) -> dict:
        """Chip-level (launcher) ports, referenced as ``"chip.<name>"``."""
        if not self.data["chip"].get("launchers"):
            return {}
        from quantcore_circuits.assembly.plan import _launcher_ports, chip_parameters  # pylint: disable=C0415

        design = self.design  # validated: preset defaults filled in
        return _launcher_ports(design.chip.launchers, chip_parameters(design))

    def route(
        self,
        name: str,
        start,
        end,
        meander: float | None = None,
        type: str | None = None,  # noqa: A002
        nodes=None,
        a: float | None = None,
        b: float | None = None,
        r: float | None = None,
        airbridges=None,
        meander_direction: int | None = None,
        **params,
    ) -> RouteHandle:
        """Connect two ports with a CPW (``meander=length`` for a fixed-length meander). ``end`` may be a port,
        ``other_route.hanger(...)`` or ``Designer.free_end(...)``; ``nodes`` are waypoints (tuples or
        :meth:`waypoint`). ``meander_direction=-1`` mirrors the meander (its first turn goes the other way)."""
        for p in (start, end):
            if isinstance(p, str):
                self._check_port(p)
        spec: dict = {
            "from": str(start) if isinstance(start, str) else start,
            "to": str(end) if isinstance(end, str) else end,
        }
        if meander is not None:
            spec.update(type="meander", length=float(meander))
        elif type:
            spec["type"] = type
        if nodes:
            spec["nodes"] = [list(n) if isinstance(n, tuple) else n for n in nodes]
        for k, v in (
            ("a", a),
            ("b", b),
            ("r", r),
            ("airbridges", airbridges),
            ("meander_direction", meander_direction),
        ):
            if v is not None:
                spec[k] = v
        if params:
            spec["params"] = params
        with self._change(f"route {name}"):
            self.data["routes"][name] = spec
        return RouteHandle(self, name)

    @staticmethod
    def waypoint(at, a: float | None = None, b: float | None = None, airbridge: bool = False, **params) -> dict:
        w = {"at": list(at)}
        if a is not None:
            w["a"] = a
        if b is not None:
            w["b"] = b
        if airbridge:
            w["airbridge"] = True
        if params:
            w["params"] = params
        return w

    @staticmethod
    def free_end(at, dir: float | None = None, term: float = 0.0) -> dict:  # noqa: A002
        return {"at": list(at), "dir": dir, "term": term}

    def remove(self, name: str) -> None:
        with self._change(f"remove {name}"):
            if name in self.data["instances"]:
                del self.data["instances"][name]
                for rname, rt in list(self.data["routes"].items()):
                    ends = [e for e in (rt["from"], rt["to"]) if isinstance(e, str)]
                    if any(e.split(".", 1)[0] == name for e in ends):
                        del self.data["routes"][rname]
            else:
                self.data["routes"].pop(name, None)

    def couple(
        self,
        name: str,
        a: str,
        b: str,
        C_fF: float | None = None,
        L_nH: float | None = None,
        note: str = "",
        wire: bool = False,
    ) -> None:
        """Declare a lumped coupling no route or snap carries (e.g. qubit arms facing each other).

        ``a``/``b`` are ``"Q1"`` (main island), ``"Q1.<port>"``, ``"Q1.<LOM node>"`` or a route name (its conductor,
        e.g. a hanger against a routed feedline: ``d.couple("K_R1", "R1", "FL")``); give ``C_fF`` (default C,
        value optional: a C-matrix fills it by island name) or ``L_nH``. ``wire=True`` declares a galvanic join of two
        *ports* instead (no element, no geometry): for overlapping metal, e.g. a legacy resonator end drawn inside a
        claw tail.
        """
        for end in (a, b):
            head = end.split(".", 1)[0]
            if head not in self.data["instances"] and not (not wire and str(end) in self.data["routes"]):
                raise ValueError(f"coupling {name}: no instance or route {head!r}")
        if wire:
            if C_fF is not None or L_nH is not None:
                raise ValueError(f"coupling {name}: a wire takes no value")
            for end in (a, b):
                self._check_port(str(end))
            kind, value = "wire", None
        else:
            kind, value = ("L", L_nH) if L_nH is not None else ("C", C_fF)
        with self._change(f"couple {name}", rebuild=False):
            self.data["couplings"][name] = {"between": [str(a), str(b)], "type": kind, "value": value, "note": note}

    def targets(self, **per_instance) -> None:
        with self._change("targets", rebuild=False):
            self.data["targets"].update(per_instance)

    def sim_group(
        self,
        name: str,
        select: list[str],
        margin_um: float = 300.0,
        analyses=("eigenmode_epr", "q3d_cmatrix"),  # decision #31: eigenmode/EPR first (the default analysis)
        ports: dict[str, str] | None = None,
        settings: dict | None = None,
    ) -> None:
        """A FEM sub-problem. ``ports`` maps a selected route to ``"keep"`` (not cut for capacitance analyses),
        ``"edge"`` or ``"internal"``; ``"edge"`` on a grounded line the box cuts (e.g. a qubit's λ/4 readout when only
        the qubit is selected) terminates it in 50 Ω there for eigenmode / driven runs. ``settings`` are passed to the
        simulation (solver options)."""
        spec = {"select": list(select), "margin_um": margin_um, "analyses": list(analyses)}
        if ports:
            spec["ports"] = dict(ports)
        if settings:
            spec["settings"] = dict(settings)
        with self._change(f"sim group {name}", rebuild=False):
            self.data["sim_groups"][name] = spec

    def sim_subset(
        self,
        name: str,
        pairs=None,
        qubits=None,
        margin_um: float = 300.0,
        analyses=("eigenmode_epr", "q3d_cmatrix"),
        settings: dict | None = None,
        split: str = "auto",
        verbose: bool = False,
        readouts: bool = True,
    ) -> list[str]:
        """Simulate a subset of the chip (:mod:`quantcore_circuits.sim_tools.subset`): ``pairs=[("Q3", "R3"), ("Q5",
        "R5")]`` (resonator None → the qubit's readout) or ``qubits=["Q3", "Q5"]``. Each chosen qubit comes with its
        readout chain; the feedline is always in the box and cut into 50 Ω ports by it; a bus between two chosen qubits
        comes in, a bus to a qubit outside the subset is cut (``ports={bus: "cut"}``: a 50 Ω stub at the chosen
        qubit's pad). Disjoint pairs get one box each (``split="auto"``; ``"one"``: one box). Adds one sim group per
        box and returns their names (``name`` itself when there is one box, else ``<name>_<qubits>``). The netlist is
        not touched: ``fill(whole_chip_model, design, [jobs])`` fills only these components. ``readouts=False``: the
        qubits alone (the box cuts their readouts into 50 Ω lines; an eigenmode box that fits a workstation)."""
        from quantcore_circuits.sim_tools.subset import describe, plan_subset  # pylint: disable=C0415

        groups = plan_subset(self.design, name, pairs=pairs, qubits=qubits, split=split, readouts=readouts)
        for sg in groups:
            spec = sg.spec(margin_um, analyses, settings)
            self.sim_group(sg.name, spec["select"], margin_um, analyses, spec.get("ports"), settings)
        self.subset_plan = groups
        if verbose:
            print(describe(groups))
        return [sg.name for sg in groups]

    def __getitem__(self, name: str):
        if name in self.data["instances"]:
            return InstanceHandle(self, name)
        if name in self.data["routes"]:
            return RouteHandle(self, name)
        raise KeyError(name)

    # ---- live --------------------------------------------------------------------------------------------------
    @contextlib.contextmanager
    def batch(self):
        """Group several changes into one rebuild."""
        self._batch += 1
        try:
            yield self
        finally:
            self._batch -= 1
            if self._batch == 0 and self._dirty and self.live:
                self.show()

    @contextlib.contextmanager
    def _change(self, what: str, rebuild: bool = True):
        backup = copy.deepcopy(self.data)
        try:
            yield
            self.design  # noqa: B018  (validate now: bad specs raise here, with the old state restored)
        except Exception:
            self.data = backup
            raise
        self.history.append(what)
        self._dirty = True
        if rebuild and self.live and self._batch == 0:
            self.show(quiet_errors=True)
            if self.delay:
                time.sleep(self.delay)

    def show(self, quiet_errors: bool = False):
        """Build, write ``build/<name>.oas`` (+ sidecar) and reload KLayout (starting it if needed)."""
        from quantcore_circuits.assembly import build, write_layout  # pylint: disable=import-outside-toplevel
        from quantcore_circuits.live import klive_available, send_to_klive  # pylint: disable=import-outside-toplevel

        t0 = time.perf_counter()
        try:
            result = build(self.design)
        except Exception as e:  # noqa: BLE001
            if not quiet_errors:
                raise
            if self.verbose:
                print(f"[qcc] {self.history[-1] if self.history else 'build'}: not built yet — {type(e).__name__}: {e}")
            return self.result
        self.result = result
        write_layout(result, self.out)
        if self.path and self._autosave:
            self.save(self.path)
        if self.live:
            self._live_klayout(klive_available, send_to_klive)
        self._dirty = False
        if self.verbose and self.live:
            last = self.history[-1] if self.history else "build"
            print(f"[qcc] {last}: built in {time.perf_counter() - t0:.2f} s → {self.out}")
        return result

    def _live_klayout(self, klive_available, send_to_klive) -> None:
        """Redraw in KLayout: start it when klive is not listening (unless switched off, or the KLayout this designer
        started is still coming up), send the layout, raise the window on the first build / after a start."""
        from quantcore_circuits.live import klayout as kl  # pylint: disable=import-outside-toplevel

        may_open = kl.gui_enabled() if self._open is None else bool(self._open)
        started = False
        if not klive_available() and may_open:
            if self._kl_pid and self._kl_pid in kl.klayout_pids():
                if self.verbose and not self._kl_hint:  # ours is open but klive never came up: do not start more
                    print(f"[qcc] KLayout pid {self._kl_pid} is open but klive is not listening on localhost:8082")
                    self._kl_hint = True
            else:
                try:
                    info = kl.open_klayout(self.out, front=False)
                except FileNotFoundError as e:  # no KLayout installed: stay headless (layouts are still written)
                    info = {"started": False, "klive": False, "hint": str(e)}
                    self._open = False
                started = bool(info.get("started"))
                self._kl_pid = info.get("pid") or self._kl_pid
                if self.verbose:
                    print(f"[qcc] KLayout: {info}")
        sent = klive_available()
        if sent:
            send_to_klive(self.out)
        if may_open and (started or (sent and self._front)):  # only a window that shows this layout
            kl.bring_to_front(self._kl_pid if started else None, self.out)
            self._front = False

    # ---- outputs -----------------------------------------------------------------------------------------------
    @property
    def design(self):
        from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

        return load_design(copy.deepcopy(self.data))

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.design.to_json_dict(), indent=2) + "\n", encoding="utf-8")
        self.path = path
        return path

    def lom(self, select: list[str] | None = None):
        """Lumped circuit of this layout (component estimates; see :mod:`quantcore_circuits.lom`)."""
        from quantcore_circuits.lom import lom_from_design  # pylint: disable=import-outside-toplevel

        return lom_from_design(self.design, select)

    def drc(self):
        from quantcore_circuits.assembly.drc import check  # pylint: disable=import-outside-toplevel

        return check(self.result or self.design)

    # ---- validation ----------------------------------------------------------------------------------------------
    @staticmethod
    def _check_cell(cell: str, params: dict) -> None:
        if cell.startswith("static:"):
            return
        from quantcore_circuits.layouts.registry import list_components, resolve_cell  # pylint: disable=C0415

        try:
            cls = resolve_cell(cell)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"unknown cell {cell!r}; available: {sorted(list_components())}") from e
        if hasattr(cls, "qcc_params"):  # wrapper cell: it validates its own parameters
            cls.qcc_params(dict(params))
            return
        schema = cls.get_schema()
        unknown = sorted(set(params) - set(schema))
        if unknown:
            close = sorted(n for n in schema if not n.startswith("_"))
            raise ValueError(f"{cell}: unknown parameter(s) {unknown}; parameters: {close}")

    def _check_port(self, ref: str) -> None:
        inst, _, port = ref.partition(".")
        if inst == "chip" and inst not in self.data["instances"]:
            if port not in self.chip_ports:
                raise ValueError(f"{ref!r}: chip launchers are {sorted(self.chip_ports)}")
            return
        if inst not in self.data["instances"]:
            raise ValueError(f"{ref!r}: no instance {inst!r} (placed: {sorted(self.data['instances'])})")
        h = InstanceHandle(self, inst)
        if port not in h.ports:
            raise ValueError(f"{ref!r}: {inst} has ports {sorted(h.ports)}")

    def __repr__(self) -> str:
        return (
            f"<Designer {self.data['name']}: {len(self.data['instances'])} instances, "
            f"{len(self.data['routes'])} routes, live={self.live}>"
        )
