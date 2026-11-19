"""Live PCells (opt-in, Settings): the Quantcore PDK cells as a KLayout library, so KLayout's own Instance tool and
its PCell parameter dialog place and edit them, while ``design.json`` stays the source of truth.

The plugin still does not import quantcore_circuits or KQCircuits inside KLayout (KLayout's Python is a MinGW build
without pydantic, and the KQC Salt package it may load is another KQC version than the one ``qcc`` builds with).
Each PCell here is a light declaration: its parameters come from one ``qcc components --source quantcore --schemas``
call, and its geometry is **copied from what ``qcc`` built**:

* after every rebuild, each placed component's built cell is cached under ``(cell, parameters)`` and the static
  instance is swapped for a library PCell instance with the same parameters (same transform, same ``id`` property),
  so the geometry in the view is exactly the build's;
* a parameter set not built yet (a new value in the Instance tool or the PCell dialog) is drawn from the nearest
  cached geometry of that cell at once, and a background ``qcc components CELL --oas`` fetches the real one
  (``--design`` gives it the chip's inherited parameters); the library is refreshed when it lands.

Edits flow back like every other edit: a library PCell instance without ``id`` (placed with the Instance tool) becomes
a design instance, a changed parameter becomes the instance's ``params``, both through ``SESSION.commit`` (Undo
works), and the rebuild replaces the preview with the built geometry.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

try:  # inside KLayout
    import pya  # type: ignore
except ImportError:  # standalone tests
    import klayout.db as pya  # type: ignore

LIB_NAME = "Quantcore"
CFG_LIVE = "qcc-kplugin-live-pcells"
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_TYPES = {
    "double": pya.PCellParameterDeclaration.TypeDouble,
    "int": pya.PCellParameterDeclaration.TypeInt,
    "string": pya.PCellParameterDeclaration.TypeString,
    "boolean": pya.PCellParameterDeclaration.TypeBoolean,
    "list": pya.PCellParameterDeclaration.TypeList,
}


# ---- parameter values (pure Python) -------------------------------------------------------------------------------
def norm(value):
    """A canonical JSON value: tuples as lists, integral floats as ints (10.0 and 10 are the same parameter)."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [norm(v) for v in value]
    if isinstance(value, dict):
        return {str(k): norm(v) for k, v in value.items()}
    return str(value)


def _number(text):
    try:
        f = float(text)
    except (TypeError, ValueError):
        return text
    return int(f) if f.is_integer() else f


def coerce(value, row: dict):
    """``value`` as KLayout's dialog hands it back (list items are strings) → the type of the schema ``row``."""
    kind = row.get("kqc_type") or {"int": "int", "float": "double", "bool": "boolean", "list": "list"}.get(
        row.get("type"), "string")
    default = row.get("default")
    if kind == "list":
        items = list(value) if isinstance(value, (list, tuple)) else [value]
        sample = next(iter(default), None) if isinstance(default, list) else None
        if isinstance(sample, str):
            return [str(v) for v in items]
        return [_number(v) if isinstance(v, str) else v for v in items]
    if kind == "double":
        return float(value)
    if kind == "int":
        return int(round(float(value)))
    if kind == "boolean":
        return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes")
    return value if isinstance(value, str) else str(value)


def own_params(schema: list[dict], values: dict) -> dict:
    """The design.json ``params`` for PCell ``values``: coerced, and only those that differ from the defaults."""
    out = {}
    for row in schema:
        if row["name"] not in values:
            continue
        v = norm(coerce(values[row["name"]], row))
        if v != norm(row["default"]):
            out[row["name"]] = v
    return out


def full_params(schema: list[dict], own: dict) -> dict:
    """Every PCell parameter: the defaults with ``own`` on top (what ``add_pcell_variant`` takes)."""
    return {row["name"]: own.get(row["name"], row["default"]) for row in schema}


def params_key(cell: str, own: dict) -> str:
    return f"{cell}:{json.dumps(norm(own), sort_keys=True)}"


def base_cell(ref: str) -> str:
    """The library name of a design.json ``cell`` (``Xmon`` or ``quantcore_circuits.layouts....Xmon``)."""
    return ref.rsplit(".", 1)[-1] if ref.startswith("quantcore_circuits.") else ref


def liveable(entry: dict, schemas: dict) -> str | None:
    """The library cell for a design instance, or None when it cannot be a live PCell: not a Quantcore PDK cell, or
    ``params`` outside its editable schema (shapes, layers), which the PCell could not carry."""
    cell = base_cell(entry.get("cell", ""))
    info = schemas.get(cell)
    if info is None:
        return None
    names = {row["name"] for row in info["schema"]}
    return cell if set(entry.get("params") or {}) <= names else None


def context_key(design: dict, path=None) -> str:
    """Geometry depends on the chip (inherited ``a``/``b``, PDK): a new context empties the geometry cache."""
    data = json.dumps([str(path or ""), design.get("pdk"), design.get("chip")], sort_keys=True)
    return hashlib.sha1(data.encode("utf-8")).hexdigest()[:12]  # noqa: S324


def _place(trans) -> dict:
    from qcc_kplugin.design_io import _place_from_trans  # pylint: disable=import-outside-toplevel

    return _place_from_trans(trans)


def library_cell_name(inst, layout) -> str | None:
    """The PCell name of an instance (in ``layout``) of the Quantcore library (None for anything else)."""
    if not inst.is_pcell():
        return None
    cell = layout.cell(inst.cell_index)
    lib = cell.library() if cell is not None and cell.is_library_cell() else None
    if lib is None or lib.name() != LIB_NAME:
        return None
    decl = inst.pcell_declaration()
    return decl.name() if decl is not None else None


def sync(design: dict, chip, schemas: dict) -> tuple[dict, list[str]]:
    """Quantcore library PCells in ``chip`` → ``design``: an instance without ``id`` (placed with KLayout's Instance
    tool) becomes a new design instance (and gets its ``id``); a changed parameter becomes the instance's ``params``
    (keys outside the PCell schema are kept). Moves, rotations and deletes are synced by the session as before."""
    from qcc_kplugin import design_io  # pylint: disable=import-outside-toplevel

    report = []
    layout = chip.layout()
    tag = []  # (cell index, transform, name): ids are set afterwards, since a property change can move an instance
    for inst in list(chip.each_inst()):
        cell = library_cell_name(inst, layout)
        info = schemas.get(cell) if cell else None
        if info is None:
            continue
        schema = info["schema"]
        own = own_params(schema, inst.pcell_parameters_by_name())
        name = inst.property("id")
        if not name:
            if inst.is_regular_array():
                report.append(f"{cell}: an array is not a design instance; place single instances")
                continue
            name = design_io.unique_name(design, "".join(c for c in cell if c.isupper())[:3] or "X")
            place = _place(inst.dcplx_trans)
            design_io.add_instance(design, name, cell, place["at"], place["rot"], own or None,
                                   bool(place.get("mirror")))
            tag.append((inst.cell_index, inst.dcplx_trans, name))
            report.append(f"placed {name} ({cell}) at ({place['at'][0]:g}, {place['at'][1]:g}) rot {place['rot']:g}")
            from qcc_kplugin import tools  # pylint: disable=import-outside-toplevel

            jnote = tools.fix_placed_junction(design, name)  # fixed at design time, in the same commit
            if jnote:
                report.append(jnote)
            continue
        entry = design.get("instances", {}).get(str(name))
        if entry is None or base_cell(entry.get("cell", "")) != cell:
            continue
        old = entry.get("params") or {}
        before = own_params(schema, old)  # explicit default values in design.json are no change
        if before == own:
            continue
        new = dict(old)  # keys outside the schema, and explicit defaults that did not change, stay as written
        for row in schema:
            n = row["name"]
            if n in own:
                new[n] = own[n]
            elif n in before:
                del new[n]  # set back to its default
        changed = sorted(k for k in set(own) | set(before) if own.get(k) != before.get(k))
        design_io.set_instance(design, str(name), new)
        report.append(f"{name}: {', '.join(changed)} set in KLayout's PCell dialog")
    for ci, trans, name in tag:
        inst = _find(chip, lambda i, ci=ci, trans=trans: not i.property("id") and i.cell_index == ci
                     and i.dcplx_trans == trans)
        if inst is not None:
            inst.set_property("id", name)
    return design, report


def _find(chip, pred):
    """The first instance of ``chip`` matching ``pred``, looked up afresh (Instance references go stale when another
    instance of the cell is changed)."""
    return next((i for i in chip.each_inst() if pred(i)), None)


# ---- geometry cache ------------------------------------------------------------------------------------------------
class GeometryCache:
    """Flat copies of built component cells, by :func:`params_key`, in a private layout."""

    def __init__(self):
        self.layout = pya.Layout()
        self.cells: dict[str, int] = {}
        self.latest: dict[str, str] = {}  # cell → the key cached last (the preview for an unbuilt parameter set)
        self.context = ""

    def clear(self) -> None:
        self.layout = pya.Layout()
        self.cells.clear()
        self.latest.clear()

    def put(self, key: str, src) -> None:
        """Cache ``src`` (a cell of any layout, in its local frame) under ``key``, flattened."""
        if key in self.cells:
            old = self.layout.cell(self.cells[key])
            if old is not None:
                self.layout.delete_cell(old.cell_index())
        tgt = self.layout.create_cell(f"c{len(self.cells)}_{key.split(':', 1)[0]}")
        tgt.copy_tree(src)
        tgt.flatten(-1, True)
        self.cells[key] = tgt.cell_index()
        self.latest[key.split(":", 1)[0]] = key

    def get(self, key: str):
        ci = self.cells.get(key)
        return self.layout.cell(ci) if ci is not None else None

    def nearest(self, cell: str):
        key = self.latest.get(cell)
        return self.get(key) if key else None

    def load(self, key: str, path) -> bool:
        """Cache the geometry ``qcc components CELL --oas`` wrote (top cell ``qcc_component``)."""
        src = pya.Layout()
        src.read(str(path))
        top = next((c for c in src.top_cells() if c.name == "qcc_component"), None)
        if top is None:
            return False
        self.put(key, top)
        return True


def draw(src, layout, cell) -> None:
    """Copy the (flat) cached ``src`` into a PCell's ``cell`` of ``layout``, layer by layer (same layer infos as the
    built OAS, so the view gets no new layers)."""
    for li in src.layout().layer_indexes():
        shapes = src.shapes(li)
        if shapes.is_empty():
            continue
        cell.shapes(layout.layer(src.layout().get_info(li))).insert(shapes)


def draw_marker(layout, cell, size: float = 100.0) -> None:
    """Nothing of this cell is cached yet: a small open square until its geometry arrives."""
    li = layout.layer(pya.LayerInfo(130, 1, "1t1_base_metal_gap_wo_grid"))
    h, w = size / 2, 2.0
    for box in ((-h, -h, h, -h + w), (-h, h - w, h, h), (-h, -h, -h + w, h), (h - w, -h, h, h)):
        cell.shapes(li).insert(pya.DBox(*box))


# ---- declarations ----------------------------------------------------------------------------------------------------
class Provider:
    """Geometry for the declarations: the cache, plus background ``qcc`` fetches of parameter sets not built yet."""

    def __init__(self, qcc: str = "qcc", design=None, env=None, outdir=None):
        self.cache = GeometryCache()
        self.schemas: dict = {}
        self.qcc = qcc
        self.design = design  # path of design.json (chip context for --oas), or None
        self.env = env
        self.outdir = Path(outdir or Path(tempfile.gettempdir()) / "qcc_kplugin_pcells")
        self.fallback: set[str] = set()  # keys produced with a preview, to refresh once their geometry is cached
        self.queue: dict[str, tuple[str, dict]] = {}  # key → (cell, own) waiting for a fetch (latest last)
        self.running: tuple[str, subprocess.Popen, Path] | None = None
        self.failed: dict[str, str] = {}
        self.produced = 0
        self.declarations: list = []

    def produce(self, cell: str, values: dict, layout, target) -> None:
        self.produced += 1
        schema = self.schemas[cell]["schema"]
        own = own_params(schema, values)
        key = params_key(cell, own)
        src = self.cache.get(key)
        if src is None:
            self.fallback.add(key)
            if key not in self.failed:
                self.request(cell, own)
            src = self.cache.nearest(cell)
        if src is None:
            draw_marker(layout, target)
        else:
            draw(src, layout, target)

    def request(self, cell: str, own: dict) -> None:
        key = params_key(cell, own)
        if self.running is not None and self.running[0] == key:
            return
        self.queue.pop(key, None)
        self.queue[key] = (cell, own)

    def poll(self) -> bool:
        """Advance the background fetch; True when new geometry was cached (refresh the library)."""
        new = False
        if self.running is not None:
            key, proc, path = self.running
            if proc.poll() is None:
                return False
            self.running = None
            if proc.returncode == 0 and path.exists():
                try:
                    new = self.cache.load(key, path)
                except RuntimeError as e:
                    self.failed[key] = str(e)
            else:
                self.failed[key] = f"qcc exited {proc.returncode}"
            try:
                path.unlink()
            except OSError:
                pass
        if self.queue and self.running is None:
            key = next(reversed(self.queue))  # the newest request: the value the user looks at now; older ones
            cell, own = self.queue.pop(key)  # were previews already replaced (a placed one is built anyway)
            self.queue.clear()
            if self.cache.get(key) is None:
                self.outdir.mkdir(parents=True, exist_ok=True)
                path = self.outdir / f"{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}.oas"  # noqa: S324
                args = [self.qcc, "components", cell, "--params", json.dumps(own), "--oas", str(path)]
                if self.design:
                    args += ["--design", str(self.design)]
                self.running = (key, subprocess.Popen(  # noqa: S603
                    args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=self.env,
                    creationflags=_NO_WINDOW), path)
        return new

    def busy(self) -> bool:
        return self.running is not None or bool(self.queue)

    def stop(self) -> None:
        if self.running is not None and self.running[1].poll() is None:
            self.running[1].kill()  # only the fetch this provider started
        self.running = None
        self.queue.clear()


def declaration(cell: str, info: dict, provider: Provider):
    """A PCell declaration for Quantcore ``cell`` (schema rows of ``qcc components --schemas``)."""
    schema = info["schema"]

    def __init__(self):
        pya.PCellDeclarationHelper.__init__(self)
        for row in schema:
            kind = _TYPES.get(row.get("kqc_type"), pya.PCellParameterDeclaration.TypeString)
            label = row.get("description") or row["name"]
            kw = {"default": row["default"]}
            if row.get("unit"):
                kw["unit"] = row["unit"]
            if row.get("choices") and kind == pya.PCellParameterDeclaration.TypeString:
                kw["choices"] = [[str(c), str(c)] for c in row["choices"]]
            self.param(row["name"], kind, label, **kw)

    def display_text_impl(self):
        return cell

    def produce_impl(self):
        values = {row["name"]: getattr(self, row["name"]) for row in schema}
        provider.produce(cell, values, self.layout, self.cell)

    cls = type(cell, (pya.PCellDeclarationHelper,), {
        "__init__": __init__, "display_text_impl": display_text_impl, "produce_impl": produce_impl,
        "__doc__": info.get("description", ""),
    })
    return cls()


def make_library(schemas: dict, provider: Provider):
    """The ``Quantcore`` library with one PCell per schema entry (not registered yet)."""
    lib = pya.Library()
    lib.description = "Quantcore PDK cells (design.json; geometry built by qcc)"
    provider.schemas = schemas
    provider.declarations = [declaration(cell, info, provider) for cell, info in sorted(schemas.items())]
    for decl in provider.declarations:  # (the provider keeps the Python objects alive)
        lib.layout().register_pcell(type(decl).__name__, decl)
    return lib


def safe_refresh(lib) -> None:
    """``lib.refresh()`` (re-produce every variant, so new geometry replaces a preview), with KLayout's Instance tool
    switched off meanwhile: KLayout 0.30.3 crashes when a library is refreshed while that tool shows a preview of one
    of its PCells (tested). The tool is switched on again, so the user stays in it."""
    views = []
    main = getattr(pya, "MainWindow", None)
    window = main.instance() if main is not None else None
    if window is not None:
        for i in range(window.views()):
            view = window.view(i)
            if view.mode_name() == "instance":
                view.switch_mode("select")
                views.append(view)
    lib.refresh()
    for view in views:
        view.switch_mode("instance")


def liven(chip, design: dict, lib, provider: Provider) -> list[str]:
    """After a rebuild: cache each component's built cell, then swap the static instance for a library PCell
    instance with the same parameters (transform and properties such as ``id`` stay). Returns the instance names."""
    layout = chip.layout()
    todo = []
    for inst in list(chip.each_inst()):
        name = inst.property("id")
        entry = design.get("instances", {}).get(str(name)) if name else None
        if entry is None or inst.is_pcell():
            continue
        cell = liveable(entry, provider.schemas)
        if cell is None:
            continue
        schema = provider.schemas[cell]["schema"]
        own = own_params(schema, entry.get("params") or {})
        key = params_key(cell, own)
        provider.cache.put(key, layout.cell(inst.cell_index))
        todo.append((str(name), cell, own, key))
    seeded = {key for *_, key in todo}
    if seeded & provider.fallback:  # previews drawn for these parameter sets: draw the built geometry instead
        provider.fallback -= seeded
        safe_refresh(lib)
    old_cells, done = set(), []
    for name, cell, own, _ in todo:
        inst = _find(chip, lambda i, name=name: str(i.property("id") or "") == name and not i.is_pcell())
        if inst is None:
            continue
        pid = lib.layout().pcell_id(cell)
        variant = layout.add_pcell_variant(lib, pid, full_params(provider.schemas[cell]["schema"], own))
        old_cells.add(inst.cell_index)
        inst.cell_index = variant
        done.append(name)
    for ci in old_cells:
        c = layout.cell(ci)
        if c is not None and c.parent_cells() == 0:
            layout.prune_cell(ci, -1)
    return done


# ---- the plugin's live library (GUI) ---------------------------------------------------------------------------
class Live:
    """The opt-in state: schemas loading in the background, the registered library, the provider."""

    def __init__(self):
        self.lib = None
        self.provider: Provider | None = None
        self.loading: tuple[subprocess.Popen, Path] | None = None
        self.timer = None
        self.error = ""
        self._last: tuple = ()

    @property
    def ready(self) -> bool:
        return self.lib is not None

    def enabled(self) -> bool:
        from qcc_kplugin.session import config  # pylint: disable=import-outside-toplevel

        return config(CFG_LIVE, "false").lower() == "true"

    def start(self, wait: bool = False) -> None:
        """Load the schemas (one ``qcc`` call, ~1 s, in the background) and register the library."""
        from qcc_kplugin.session import SESSION, clean_env  # pylint: disable=import-outside-toplevel

        if self.ready or self.loading is not None:
            return
        fd, name = tempfile.mkstemp(prefix="qcc_pcell_schemas_", suffix=".json")
        os.close(fd)
        out = open(name, "wb")  # noqa: SIM115  (closed below / in _poll_loading)
        proc = subprocess.Popen(  # noqa: S603
            [SESSION.qcc, "components", "--source", "quantcore", "--schemas"], stdout=out,
            stderr=subprocess.DEVNULL, env=clean_env(), creationflags=_NO_WINDOW)
        out.close()
        self.loading = (proc, Path(name))
        if wait:
            proc.wait(timeout=120)
            self._poll_loading()
        self._start_timer()

    def _start_timer(self) -> None:
        if self.timer is None:
            self.timer = pya.QTimer(pya.Application.instance().main_window())
            self.timer.interval = 300
            self.timer.timeout(self.tick)
            self.timer.start()

    def _poll_loading(self) -> None:
        from qcc_kplugin.session import SESSION, clean_env, log, message  # pylint: disable=import-outside-toplevel

        proc, path = self.loading
        if proc.poll() is None:
            return
        self.loading = None
        try:
            schemas = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            self.error = f"live PCells: no schemas from qcc ({e})"
            message(self.error, 15)
            return
        finally:
            try:
                path.unlink()
            except OSError:
                pass
        self.provider = Provider(SESSION.qcc, env=clean_env())
        self.lib = make_library(schemas, self.provider)
        self.lib.register(LIB_NAME)
        log(f"live PCells: library {LIB_NAME} with {len(schemas)} cells")
        message(f"live PCells: library {LIB_NAME} ({len(schemas)} cells) in KLayout's Instance tool")
        if SESSION.design_path is not None:
            SESSION.focus_chip()  # the components in the view become live PCells

    def tick(self) -> None:
        try:
            if self.loading is not None:
                self._poll_loading()
            if self.provider is not None and self.provider.poll():
                safe_refresh(self.lib)
        except Exception:  # noqa: BLE001  (a timer must never raise)
            import traceback  # pylint: disable=import-outside-toplevel

            from qcc_kplugin.session import log  # pylint: disable=import-outside-toplevel

            log(f"ERROR in the live PCell timer\n{traceback.format_exc()}")

    def stop(self) -> None:
        if self.loading is not None and self.loading[0].poll() is None:
            self.loading[0].kill()
        self.loading = None
        if self.provider is not None:
            self.provider.stop()

    # ---- session hooks --------------------------------------------------------------------------------------------
    def active(self) -> bool:
        return self.ready and self.enabled()

    def after_build(self, session, chip) -> None:
        """The view shows a fresh build: its components become live PCells (geometry = the build's)."""
        if not self.active() or chip is None or session.design_path is None:
            return
        if not any(inst.property("id") and not inst.is_pcell() for inst in chip.each_inst()):
            return  # nothing static to swap (this runs on every focus of the chip cell)
        design = session.design()
        ctx = context_key(design, session.design_path)
        p = self.provider
        p.design = session.design_path
        if ctx != p.cache.context:
            p.cache.clear()
            p.cache.context = ctx
        liven(chip, design, self.lib, p)

    def sync(self, session, chip) -> None:
        """Instance tool placements and PCell dialog edits → design.json (one commit)."""
        if not self.active() or chip is None:
            return
        if self._signature(chip) == self._last:
            return  # no library instance added and no parameter changed (a change makes a new variant cell)
        design = session.design()
        design, report = sync(design, chip, self.provider.schemas)
        self._last = self._signature(chip)
        if report:
            session.commit(design, "; ".join(report))
            for line in report:
                if ": junction L_J " in line:
                    from qcc_kplugin.session import message  # pylint: disable=import-outside-toplevel

                    message(line, 12)

    @staticmethod
    def _signature(chip) -> tuple:
        layout = chip.layout()
        return tuple(sorted((str(inst.property("id") or ""), inst.cell_index) for inst in chip.each_inst()
                            if library_cell_name(inst, layout)))


LIVE = Live()


def startup() -> None:
    """Called by the autorun macro: register the library when Settings has live PCells on."""
    if LIVE.enabled():
        LIVE.start()
