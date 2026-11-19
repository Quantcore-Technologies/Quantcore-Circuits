"""``qcc`` command line."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from quantcore_circuits import __version__

# Piped or redirected output on Windows defaults to cp1252, and `qcc --help` (Rich box characters, µ, →, Δ) crashed
# with UnicodeEncodeError. Pipes get UTF-8; a console that still cannot encode a character shows "?" instead.
for _stream in (sys.stdout, sys.stderr):
    try:
        if (getattr(_stream, "encoding", "") or "").lower().replace("-", "") != "utf8":
            if _stream.isatty():
                _stream.reconfigure(errors="replace")
            else:
                _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

app = typer.Typer(
    help="Quantcore circuits: design.json → KQC layout → simulation → parameters → feedback.", no_args_is_help=True
)
sim_app = typer.Typer(help="Simulation jobs (HFSS/Q3D, Elmer, Palace).", no_args_is_help=True)
results_app = typer.Typer(help="Parse, extract and store results.", no_args_is_help=True)
runner_app = typer.Typer(help="Job runner / filesystem queue (lab server).", no_args_is_help=True)
design_app = typer.Typer(help="design.json utilities.", no_args_is_help=True)
hfss_app = typer.Typer(help="Ansys HFSS / Q3D projects (AEDT 2024 R1/R2).", no_args_is_help=True)
circuit_app = typer.Typer(
    help="Lumped circuit (LOM): layout → circuit.json, LOM simulation, circuit → layout.", no_args_is_help=True
)
app.add_typer(sim_app, name="sim")
app.add_typer(results_app, name="results")
app.add_typer(runner_app, name="runner")
app.add_typer(design_app, name="design")
app.add_typer(hfss_app, name="hfss")
app.add_typer(circuit_app, name="circuit")


def _version(value: bool):
    if value:
        typer.echo(f"quantcore-circuits {__version__}")
        raise typer.Exit()


@app.callback()
def main(version: bool = typer.Option(False, "--version", callback=_version, is_eager=True, help="Show version.")):
    """Quantcore circuits CLI."""


@app.command()
def selftest(
    allow_missing: bool = typer.Option(
        False, "--allow-missing", help="A missing extra (analysis, sim, notebook) is skipped instead of failing."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the checks as JSON."),
):
    """Check this install: imports of every extra, a Q1 + R1 chip (build, DRC, LOM, job export), ansysedt lookup."""
    from quantcore_circuits.selftest import main as run_selftest  # pylint: disable=import-outside-toplevel

    code = run_selftest(allow_missing=allow_missing, as_json=as_json)
    if code:
        raise typer.Exit(code)


@app.command("kqc-files")
def kqc_files(
    version: str = typer.Option(None, "--version", help="kqcircuits version (default: the installed one)."),
    source: Path = typer.Option(
        None, "--source", help="A KQCircuits checkout or a source zip, instead of the download."
    ),
    force: bool = typer.Option(False, "--force", help="Fetch again even when the cache has them."),
):
    """Fetch the KQCircuits files its PyPI package lacks: the simulation scripts and the label font.

    Downloads them for the installed kqcircuits release from github.com/iqm-finland/KQCircuits into the user cache
    (the HFSS / Q3D / Elmer export and KQC's chip-frame labels need them). Nothing to do for a KQCircuits checkout.
    """
    from quantcore_circuits import kqc_files as kf  # pylint: disable=import-outside-toplevel

    found, where = kf.find_kqc_scripts()
    font = kf.ensure_kqc_data()
    if found is not None and where == "kqcircuits" and font is not None and not force:
        typer.echo(f"kqcircuits has its own scripts and font: {found}")
        return
    try:
        path = kf.fetch_kqc_files(version=version, source=source, force=force)
    except (OSError, ValueError) as e:
        typer.echo(f"could not fetch the KQCircuits files: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(f"KQCircuits files for {version or kf.kqc_version()}: {path}")


# ---- layout -------------------------------------------------------------------------------------------------------
LABEL_HEIGHT_HELP = ("Height of the instance name labels in µm (capital letters; 0 = none). Default: KQC's 280. An "
                     "annotation layer only: the fab mask, simulations and the design hash do not change.")


def _label_override(label_height: float | None) -> dict:
    """The chip override of ``--label-height`` (none when not given: the default build stays as it is)."""
    if label_height is None:
        return {}
    if label_height < 0:
        raise typer.BadParameter("--label-height must be >= 0")
    return {"instance_label_height": float(label_height)}


@app.command()
def build(
    design: Path,
    out: Path = typer.Option(None, "-o", help="Output .oas/.gds (default build/<name>.oas)"),
    show: bool = typer.Option(False, help="Send to KLayout via klive"),
    keep_going: bool = typer.Option(
        False,
        "--keep-going",
        help="A route that cannot be built is left out (named in the sidecar's failed_routes, its last good route kept "
        "in <name>.last_good_routes.json) instead of failing the build. The default is strict.",
    ),
    label_height: float = typer.Option(
        None, "--label-height", help=LABEL_HEIGHT_HELP,
    ),
):
    """Build DESIGN (.json/.py) into a KQC chip and write it."""
    from quantcore_circuits.assembly import build as build_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.assembly import last_good, write_layout  # pylint: disable=import-outside-toplevel

    prev = None
    if keep_going:  # the output path is known before the build: the last good routes sit beside it
        from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

        prev = last_good.load(last_good.store_path(out or Path("build") / f"{load_design(design).name}.oas"))
    result = build_design(design, keep_going=keep_going, last_good=prev, **_label_override(label_height))
    out = out or Path("build") / f"{result.design.name}.oas"
    write_layout(result, out)
    typer.echo(f"wrote {out}  (hash {result.hash})")
    for name, length in result.route_lengths().items():
        typer.echo(f"  route {name}: {length:.2f} um")
    for name, failed in result.failed_routes.items():  # only with --keep-going
        typer.echo(f"  FAILED {failed.error}  (route {name} is not in the layout"
                   + ("; its last good route is kept)" if failed.last_good else ")"), err=True)
    if show:
        from quantcore_circuits.live import send_to_klive  # pylint: disable=import-outside-toplevel

        typer.echo(f"klive: {send_to_klive(out)}")


@app.command()
def watch(
    design: Path,
    out: Path = typer.Option(None, "-o"),
    klive: bool = typer.Option(True, help="Use klive"),
    extra: list[Path] = typer.Option(None, help="More files to watch (e.g. imported modules)"),
    label_height: float = typer.Option(None, "--label-height", help=LABEL_HEIGHT_HELP),
):
    """Rebuild on every save and reload KLayout (klive)."""
    from quantcore_circuits.live import watch as run_watch  # pylint: disable=import-outside-toplevel

    run_watch(design, out, extra=extra, klive=klive, chip_overrides=_label_override(label_height))


@app.command()
def components(
    cell: str = typer.Argument(None, help="Show ports of this cell (name, dotted path or metal:<Class>)"),
    category: str = typer.Option(None, "--category", "-c", help="Only this category (qubit, coupler, launcher, ...)"),
    source: str = typer.Option(None, "--source", "-s", help="Only this source: quantcore, kqc or metal"),
    as_json: bool = typer.Option(False, "--json", help="Machine-readable: refs (or ports with CELL)"),
    details: bool = typer.Option(False, "--details", help="With --json: full catalog records instead of refs"),
    show_all: bool = typer.Option(False, "--all", help="Include whole KQC chips and Metal routes (not cells)"),
    outline: bool = typer.Option(
        False, "--outline", help="With CELL --json: also its bbox and a simplified outline (the KLayout placement ghost)"
    ),
    params: str = typer.Option("{}", "--params", help="With CELL: PCell parameters as JSON"),
    schema: bool = typer.Option(False, "--schema", help="With CELL: its editable parameters and defaults (JSON)"),
    schemas: bool = typer.Option(
        False, "--schemas", help="Every listed cell's editable parameters in one JSON (the KLayout PCell library)"
    ),
    oas: Path = typer.Option(None, "--oas", help="With CELL: write its geometry (a static cell) to this OASIS file"),
    design: Path = typer.Option(
        None, "--design", help="With CELL --oas: build it as in this design (chip-inherited parameters, PDK junction)"
    ),
):
    """List available components (Quantcore, KQC, Quantum Metal) by category, or the ports of one."""
    from quantcore_circuits.assembly.plan import pcell_params  # noqa: PLC0415
    from quantcore_circuits.layouts.catalog import catalog  # noqa: PLC0415
    from quantcore_circuits.layouts.registry import element_ports, resolve_cell  # noqa: PLC0415

    if cell:
        cls = resolve_cell(cell)
        try:
            user = json.loads(params or "{}")
        except ValueError as e:
            raise typer.BadParameter(f"--params is not JSON: {e}") from e
        if oas:
            _component_oas(cls, user, oas, design)
            typer.echo(str(oas))
            return
        if schema:
            from quantcore_circuits.layouts.registry import element_schema  # noqa: PLC0415

            typer.echo(json.dumps(element_schema(cls)))
            return
        if outline:
            from quantcore_circuits.layouts.registry import element_outline  # noqa: PLC0415

            typer.echo(json.dumps(element_outline(cls, **pcell_params(cls, user))))
            return
        ports = element_ports(cls, **pcell_params(cls, user))
        if as_json:
            typer.echo(json.dumps([p.as_dict() for p in ports.values()], indent=2))
            return
        for name, p in ports.items():
            d = p.as_dict()
            typer.echo(f"  {name:12s} at {d['at']}  dir {d['dir']}  a={d['a']} b={d['b']}")
        return
    try:
        entries = catalog(category=category, source=source, chips=show_all or category == "chip", routes=show_all)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    if schemas:
        typer.echo(json.dumps(_cell_schemas([c for c in entries if c.cell])))
        return
    if as_json:
        typer.echo(json.dumps([c.as_dict() for c in entries] if details else [c.ref for c in entries], indent=2))
        return
    current = None
    for c in sorted(entries, key=lambda c: (c.category, c.source != "quantcore", c.ref.lower())):
        if c.category != current:
            current = c.category
            typer.echo(f"{current}:")
        typer.echo(c.listing_line())  # "(legacy)" / "(alias of X)" before the description


def _cell_schemas(entries) -> dict:
    """``{ref: {"category", "description", "schema"}}`` for catalog ``entries``: the ``--schema`` rows of each cell,
    each with ``kqc_type`` (``double``, ``int``, ``string``, ``boolean``, ``list``), so the KLayout plugin can declare
    its PCells in one call. A cell that cannot be resolved is left out."""
    from kqcircuits.util.parameters import pdt  # noqa: PLC0415

    from quantcore_circuits.layouts.registry import element_schema, resolve_cell  # noqa: PLC0415

    names = {pdt.TypeDouble: "double", pdt.TypeInt: "int", pdt.TypeString: "string", pdt.TypeBoolean: "boolean",
             pdt.TypeList: "list"}
    out = {}
    for c in entries:
        try:
            cls = resolve_cell(c.ref)
        except ValueError:
            continue
        kqc = cls.get_schema()
        rows = element_schema(cls)
        for row in rows:
            row["kqc_type"] = names.get(kqc[row["name"]].data_type, "string")
        out[c.ref] = {"category": c.category, "description": c.description, "schema": rows}
    return out


def _component_oas(cls, own: dict, out: Path, design: Path | None = None) -> None:
    """Write one component's geometry, as a design build makes it (chip-inherited parameters of ``design`` and the
    PDK junction default), to ``out``: a top cell ``qcc_component`` holding the static component cell at the origin."""
    import os  # pylint: disable=import-outside-toplevel
    import tempfile  # pylint: disable=import-outside-toplevel

    from kqcircuits.pya_resolver import pya  # noqa: PLC0415
    from kqcircuits.util.load_save_layout import save_layout  # noqa: PLC0415

    from quantcore_circuits.assembly.plan import chip_parameters, element_params, inherited_params  # noqa: PLC0415
    from quantcore_circuits.layouts.chips.design_chip import ensure_registered  # noqa: PLC0415
    from quantcore_circuits.layouts.registry import create_cell  # noqa: PLC0415

    ensure_registered()
    inherited = {}
    if design is not None:
        from quantcore_circuits.design import load_design  # noqa: PLC0415

        inherited = inherited_params(chip_parameters(load_design(design)))
    layout = pya.Layout()
    cell = create_cell(layout, cls, what=cls.__name__, **element_params(cls, inherited, own))
    top = layout.create_cell("qcc_component")  # a top-level library proxy is not written; wrap it like a build
    top.insert(pya.DCellInstArray(cell.cell_index(), pya.DTrans()))
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=out.suffix or ".oas", dir=out.parent)
    os.close(fd)
    try:
        save_layout(tmp, layout, [top])
        os.replace(tmp, out)  # atomic: the plugin polls for the file
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


@app.command()
def synth(
    f_q: float = typer.Option(..., help="Qubit f01 [GHz]"),
    alpha: float = typer.Option(..., help="α [MHz]"),
    f_r: float = typer.Option(..., help="Resonator [GHz]"),
    g: float = typer.Option(..., help="g [MHz]"),
    a: float = 10.0,
    b: float = 6.0,
):
    """LOM-first synthesis: targets → Lj, C_Σ, Cg, λ/4 length."""
    from quantcore_circuits.analysis.synthesis import synthesize_transmon_readout  # noqa: PLC0415

    res = synthesize_transmon_readout(f_q, alpha, f_r, g, a, b)
    typer.echo(json.dumps(res, indent=2, default=float))


@app.command()
def mask(
    design: Path,
    out: Path = typer.Option(None, "-o"),
    positive: list[str] = typer.Option(None),
    cheese: bool = typer.Option(
        True, help="Cheese: the build's (PDK band or the original design's own); --no-cheese writes none"
    ),
    round_corners: bool = typer.Option(True, "--round/--no-round", help="PDK corner rounding (r ∝ shortest dim.)"),
    grid: bool = typer.Option(False, help="KQC's whole-area ground grid (with_grid) instead of the PDK band"),
):
    """Fab export with the PDK fab rules: layers 1/0–4/0, 50–53/0, 100/0, 300/301, 700, 800+, 1000/0+; --positive M1
    inverts a layer. Corner rounding is on by default; the cheese is the build's own (the PDK band unless the design
    has its own cheese, which wins). Simulation exports never get either."""
    import warnings  # pylint: disable=import-outside-toplevel

    from quantcore_circuits.assembly import build as build_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.layouts.wafers.fab_export import export_fab  # noqa: PLC0415

    result = build_design(design, **({"with_grid": True} if grid else {}))
    out = out or Path("build") / f"{result.design.name}_fab.oas"
    report: dict = {}
    with warnings.catch_warnings():  # reported below instead
        warnings.simplefilter("ignore")
        export_fab(
            result,
            out,
            {name: "positive" for name in positive or []},
            report=report,
            cheese=cheese,
            rounding=round_corners,
        )
    typer.echo(
        f"wrote {out} (cheese holes: {report.get('cheese_holes', 0)} from {report.get('cheese_source', 'none')}, "
        f"rounded corners: {round_corners})"
    )
    for name, n in sorted((report.get("written") or {}).items()):
        typer.echo(f"  {name}: {n} shapes")
    dropped = report.get("dropped") or {}
    if dropped:
        typer.echo("NOT in the mask (no PDK v2 fab layer for these):", err=True)
        for name, n in sorted(dropped.items()):
            typer.echo(f"  {name}: {n} shapes", err=True)


@app.command()
def review(
    design: Path,
    port: int = 8765,
    open_browser: bool = True,
    run_dir: Path = typer.Option(None, help="Run directory (default build/<design name>)"),
):
    """Open the live dashboard for DESIGN: steps, goal, plots, circuit, Hamiltonian, jobs, screenshots."""
    from quantcore_circuits.review.server import serve  # pylint: disable=import-outside-toplevel

    serve(design, port=port, open_browser=open_browser, run_dir=run_dir)


@app.command()
def dashboard(
    run: str = typer.Argument(None, help="Run name (build/<run>); default: follow the run with the latest activity"),
    port: int = 8765,
    open_browser: bool = True,
    root: Path = typer.Option(None, help="Folder with the run directories (default: <repo>/build)"),
):
    """Live dashboard that follows the notebooks' tracked runs (``track.start(...)`` / ``QCC_TRACK=1``)."""
    from quantcore_circuits.review.server import serve_live  # pylint: disable=import-outside-toplevel

    serve_live(root, run, port=port, open_browser=open_browser)


# ---- design -------------------------------------------------------------------------------------------------------
@design_app.command("validate")
def design_validate(design: Path):
    from quantcore_circuits.assembly import plan_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

    d = load_design(design)
    plan = plan_design(d)
    typer.echo(f"ok: {len(d.instances)} instances, {len(d.routes)} routes, {len(plan.all_ports())} ports")


@design_app.command("ports")
def design_ports(design: Path, as_json: bool = typer.Option(False, "--json")):
    """All resolved ports of a design (absolute positions), e.g. for the KLayout plugin's connect dialog."""
    from quantcore_circuits.assembly import plan_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

    ports = {ref: p.as_dict() for ref, p in plan_design(load_design(design)).all_ports().items()}
    if as_json:
        typer.echo(json.dumps(ports))
        return
    for ref, p in ports.items():
        typer.echo(f"  {ref:18s} at {p['at']}  dir {p['dir']}  a={p['a']} b={p['b']}")


@design_app.command("junctions")
def design_junctions(
    design: Path,
    names: list[str] = typer.Argument(None, help="Only these instances (default: every component with a junction)"),
    as_json: bool = typer.Option(False, "--json"),
    default: bool = typer.Option(False, "--default", help="No names: the qubits of the default simulation subset"),
):
    """Each junction as the LOM and the eigenmode / driven exports take it: L_J0, C_J, flux Φ/Φ0, asymmetry d, L at
    that flux and the source (design or drawn trilayer junction, PDK rule). Exit 1 when one has no L_J."""
    from quantcore_circuits.guiflow import junctions, missing_junctions  # pylint: disable=import-outside-toplevel

    if default and not names:
        from quantcore_circuits.guiflow import resolve_selection  # pylint: disable=import-outside-toplevel

        names = resolve_selection(design, [], default=True)[0]
        if not names:
            names = ["-"]  # no qubit at all: nothing to check (an empty list would mean every component)
    found = junctions(design, names or None)
    missing = missing_junctions(design, names or None)
    if as_json:
        typer.echo(json.dumps({"junctions": found, "missing": missing}))
    else:
        for n, j in found.items():
            lj = "none" if j["Lj_eff_nH"] is None else f"{j['Lj_eff_nH']:.4g} nH"
            l0 = "" if j["Lj0_nH"] is None or j["Lj0_nH"] == j["Lj_eff_nH"] else f" (L_J0 {j['Lj0_nH']:.4g} nH)"
            typer.echo(f"  {n:14s} {j['kind']:5s} L {lj}{l0}, C {j['Cj_fF']:g} fF, flux {j['flux_phi0']:g}, "
                       f"asym {j['asym']:g}  [{j['source'] or 'no value'}]")
        for msg in missing.values():
            typer.echo(f"  missing: {msg}", err=True)
    if missing:
        raise typer.Exit(1)


@design_app.command("placement-junction")
def design_placement_junction(
    cell: str,
    params: str = typer.Option("{}", "--params", help="Cell parameters as JSON"),
):
    """JSON of the junction values a new CELL gets when placed (``{"Lj_nH", "Cj_fF", "source"}``: the drawn trilayer
    junction's PDK value, else the PDK nominal SQUID), or ``null`` for a component without a junction."""
    from quantcore_circuits.guiflow import placement_junction  # pylint: disable=import-outside-toplevel

    typer.echo(json.dumps(placement_junction(cell, json.loads(params))))


@design_app.command("netlist")
def design_netlist(design: Path):
    """M3 netlist check: declared connections vs. the KQC geometric netlist (opens/shorts with coordinates)."""
    from quantcore_circuits.assembly import build as build_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.assembly.netlist import check_netlist  # pylint: disable=import-outside-toplevel

    report = check_netlist(build_design(design))
    for group in sorted(report.extracted, key=sorted):
        typer.echo(f"  net: {' <-> '.join(sorted(group)) if len(group) > 1 else sorted(group)[0] + ' (open end)'}")
    for issue in report.issues:
        typer.echo(f"  {issue}")
    typer.echo("netlist OK" if report.ok else f"netlist: {len(report.opens)} open(s), {len(report.shorts)} short(s)")
    if not report.ok:
        raise typer.Exit(1)


@design_app.command("drc")
def design_drc(
    design: Path,
    netlist: bool = typer.Option(True, help="Also run the KQC netlist check"),
    keep_going: bool = typer.Option(False, "--keep-going", help="Report a route that cannot be built (route_failed) and "
                                    "check the rest, instead of stopping at it"),
):
    """Connectivity DRC: dangling ports, components without LOM, outside chip, overlaps, crossings, opens/shorts."""
    from quantcore_circuits.assembly.drc import check  # pylint: disable=import-outside-toplevel

    report = check(design, netlist=netlist, keep_going=keep_going)
    typer.echo(str(report))
    if not report.ok:
        raise typer.Exit(1)


@circuit_app.command("export")
def circuit_export(
    design: Path,
    group: str = typer.Option("chip", "--group", "-g", help="'chip' (all) or a sim_groups name"),
    out: Path = typer.Option(None, "-o", help="Output circuit.json (default build/<name>.circuit.json)"),
):
    """Layout → LOM netlist: components' lumped models joined along routes/snaps (values = component estimates)."""
    from quantcore_circuits.circuit.derive import circuit_from_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.circuit.schema import save_circuit  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom import lom_from_design  # pylint: disable=import-outside-toplevel

    d = load_design(design)
    model = circuit_from_design(design, group)
    out = out or Path("build") / f"{d.name}.circuit.json"
    save_circuit(model, out)
    build = lom_from_design(design)  # the file: its last good routes stand in for a failed route
    for n, spec in model.nodes.items():
        typer.echo(f"  node {n:14s} {'ground' if spec.ground else ', '.join(spec.nets) or '-'}")
    for n, b in model.branches.items():
        typer.echo(f"  {b.type:7s} {n:16s} {b.nodes[0]} - {b.nodes[1]}")
    for name, c in model.controls.items():
        typer.echo(f"  control {name}: {c['kind']} -> {c['target']}")
    for note in build.notes:
        typer.echo(f"  note: {note}")
    for port in build.unconnected:
        typer.echo(f"  unconnected port: {port}")
    typer.echo(f"wrote {out}")


@circuit_app.command("simulate")
def circuit_simulate(
    source: Path = typer.Argument(..., help="circuit.json, or a design (its layout LOM is used)"),
    job: Path = typer.Option(None, help="Fill capacitances from this simulation job (design input only)"),
    group: str = typer.Option("chip", "--group", "-g"),
    json_out: Path = typer.Option(None, "--json", help="Also write the result (modes, params, netlist values) as JSON"),
    png: Path = typer.Option(None, "--png", help="Also draw the circuit schematic (matplotlib) to this PNG"),
):
    """LOM simulation: QuCat normal modes + kappa, QuTiP dressed spectrum -> f_q, alpha, f_r, chi, kappa."""
    from quantcore_circuits.circuit.fill import fill  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.circuit.schema import load_circuit  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom.simulate import simulate  # pylint: disable=import-outside-toplevel

    # "[lom] ..." stage lines on stderr (stdout unchanged): the KLayout plugin's Run LOM progress bar reads them
    typer.echo(f"[lom] reading the circuit {source.name}", err=True)
    data = json.loads(source.read_text(encoding="utf-8"))
    if str(data.get("schema", "")).startswith("qcc-circuit"):
        filled = fill(load_circuit(data), None)
    else:
        from quantcore_circuits.circuit.derive import circuit_from_design  # pylint: disable=C0415

        filled = fill(circuit_from_design(source, group), source, job)
    typer.echo(f"[lom] solving {len(filled.model.branches)} branches: QuCat normal modes, then the QuTiP spectrum "
               "(minutes for 5+ qubits)", err=True)
    res = simulate(filled)
    typer.echo(f"[lom] writing the result ({len(res.modes)} modes)", err=True)
    if json_out is not None:
        import dataclasses  # pylint: disable=import-outside-toplevel

        payload = {
            "schema": "qcc-lom-result/0.1",
            "name": filled.model.name,
            "source": str(source),
            "modes": [dataclasses.asdict(m) for m in res.modes],
            "chi_MHz": res.chi_MHz,
            "params": res.params,
            "zz_MHz": res.zz_MHz,
            "notes": list(res.notes),
            "netlist": res.netlist,
            "branches": {n: {"type": b.type, "nodes": list(b.nodes)} for n, b in filled.model.branches.items()},
            "png": str(png) if png is not None else None,
        }
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
    if png is not None:
        typer.echo("[lom] drawing the circuit", err=True)
        from quantcore_circuits.circuit.draw import draw_circuit  # pylint: disable=import-outside-toplevel

        draw_circuit(filled.model, res.netlist, png, title=filled.model.name)
    for m in res.modes:
        typer.echo(
            f"  mode {m.index} {m.label:6s} {m.kind:9s} f={m.f_GHz:.4f} GHz  kappa={m.kappa_MHz:.4g} MHz  "
            f"A={m.anharmonicity_MHz:.1f} MHz"
        )
    for k, v in res.params.items():
        typer.echo(f"  {k:16s} {v:.5g}")
    for note in res.notes:
        typer.echo(f"  note: {note}")


@circuit_app.command("layout")
def circuit_layout(
    circuit: Path,
    out: Path = typer.Option(..., "-o", help="Output design.json"),
    live: bool = typer.Option(False, help="Lay it out live in KLayout"),
):
    """LOM -> layout: transmon + lambda/4 pairs with targets -> knobs -> a laid-out feedline chip."""
    from quantcore_circuits.circuit.schema import load_circuit  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.lom.synthesize import layout_from_circuit  # pylint: disable=import-outside-toplevel

    d = layout_from_circuit(load_circuit(circuit), live=live)
    for sol in d.synthesis:
        typer.echo("  " + ", ".join(f"{k}={v:.4g}" for k, v in sol["knobs"].items()))
    typer.echo(f"wrote {d.save(out)}")


@design_app.command("to-python")
def design_to_python_cmd(
    design: Path,
    out: Path = typer.Option(None, "-o", help="Output script (default: <design name>.py next to the design)"),
    check: bool = typer.Option(True, help="Run the script here and require the same design hash (default on)"),
):
    """Write a readable Python script (the Designer API) that rebuilds DESIGN: the GUI prototype continues as code.

    The script writes the design.json again (``python design.py``); the round trip is checked (same ``qcc design
    hash``). Entries the Designer calls cannot say are written as plain data with a comment."""
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design.pyscript import RoundTripError, write_python  # pylint: disable=C0415

    out = out or Path(design).with_name(f"{load_design(design).name}.py")
    try:
        write_python(design, out, check=check)
    except RoundTripError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(f"wrote {out}" + ("  (round trip checked: same design hash)" if check else ""))


@design_app.command("hash")
def design_hash_cmd(design: Path):
    from quantcore_circuits.design import design_hash, load_design  # pylint: disable=import-outside-toplevel

    typer.echo(design_hash(load_design(design)))


# ---- simulation ---------------------------------------------------------------------------------------------------
@sim_app.command("build")
def sim_build(
    design: Path,
    group: str = typer.Option(..., "--group", "-g"),
    analysis: str = typer.Option(
        ...,
        "--analysis",
        "-a",
        help="q3d_cmatrix | hfss_eigenmode | eigenmode_epr | elmer_cap | palace_cap | palace_eig",
    ),
    out: Path = typer.Option(None, "-o", help="Job directory"),
    overwrite: bool = False,
):
    """Create a simulation job directory for a sim group."""
    from quantcore_circuits.sim_tools import build_simulation, export_job  # pylint: disable=import-outside-toplevel

    setup = build_simulation(design, group, analysis)
    out = out or Path("build") / "jobs" / f"{setup.design.name}_{group}_{analysis}"
    export_job(setup, out, overwrite=overwrite)
    typer.echo(f"job {out}")
    for p in setup.ports:
        typer.echo(f"  port {p.number}: {p.kind:9s} {p.name}")


def _settings(pairs: list[str] | None) -> dict:
    """``key=value`` pairs → dict; values are JSON when they parse (numbers, booleans, objects), else strings."""
    import json  # pylint: disable=import-outside-toplevel

    out = {}
    for item in pairs or []:
        if "=" not in item:
            raise typer.BadParameter(f"--set expects key=value, got {item!r}")
        key, raw = item.split("=", 1)
        try:
            out[key.strip()] = json.loads(raw)
        except ValueError:
            out[key.strip()] = raw
    return out


def _print_render(r) -> None:
    mode = getattr(r, "mode", "batch")
    typer.echo(f"job {r.job_dir}  ({r.seconds:.0f} s, AEDT {mode} pid {r.pid}, {'ok' if r.ok else 'FAILED'})")
    if getattr(r, "note", ""):
        typer.echo(f"note: {r.note}")
    typer.echo(f"project {r.project}")
    for line in r.status:
        typer.echo(f"  {line}")
    for k, v in r.summary.items():
        typer.echo(f"  {k}: {v}")
    for key in ("cmatrix", "eigenmodes", "sparams"):
        if key in r.results:
            typer.echo(f"  results.{key}: {r.results[key]}")


@hfss_app.command("render")
def hfss_render(
    design: Path,
    group: str = typer.Option("chip", "--group", "-g", help="'chip' (whole chip) or a sim_groups name"),
    analysis: str = typer.Option(
        "eigenmode_epr", "--analysis", "-a", help="eigenmode_epr (default) | hfss_eigenmode | q3d_cmatrix | hfss_driven"
    ),
    out: Path = typer.Option(None, "-o", help="Job directory (default build/jobs/<sim name>)"),
    solve: bool = typer.Option(False, help="Also solve (qcc_solve.py in a new non-graphical AEDT) and collect results"),
    settings: list[str] = typer.Option(
        None,
        "--set",
        help="Solver setting key=value (JSON value), repeatable, e.g. --set percent_error=1 "
        '--set mesh_size={"1t1_gap":10}',
    ),
    airbridges: bool = typer.Option(
        None,
        "--airbridges/--no-airbridges",
        help="Keep airbridges in the simulated geometry (default: the group's setting, else dropped)",
    ),
    timeout: float = typer.Option(None, help="Seconds before qcc kills the AEDT process tree it started"),
    open_gui: bool = typer.Option(False, "--open", help="Open the rendered project in a new AEDT GUI"),
    graphical: bool = typer.Option(False, help="Run the render with the AEDT window instead of -ng"),
    aedt: str = typer.Option(
        None, "--aedt", help="batch (new -ng AEDT, default) | gui (new AEDT window, left open) | attach (the open AEDT)"
    ),
    show: bool = typer.Option(False, help="Also send the chip to KLayout via klive"),
    dry_run: bool = typer.Option(False, help="Export the job and print the AEDT command only"),
):
    """Render DESIGN (whole chip or a sim group) into an AEDT project: geometry, stack, ports, Lj boundaries."""
    from quantcore_circuits.sim_tools import hfss  # pylint: disable=import-outside-toplevel

    cfg = _settings(settings)
    if show:
        from quantcore_circuits.assembly import show as show_design  # pylint: disable=import-outside-toplevel

        typer.echo(f"klive: {show_design(design)}")
    if dry_run:
        from quantcore_circuits.sim_tools import build_simulation, export_job  # pylint: disable=C0415

        setup = build_simulation(design, group, analysis, airbridges=airbridges)
        job = export_job(setup, out or Path("build") / "jobs" / setup.simulation.name, overwrite=True, **cfg)
        try:
            typer.echo(" ".join(hfss.render_command(job, graphical=graphical)))
        except FileNotFoundError as e:
            typer.echo(f"job {job}")
            typer.echo(str(e))
        return
    r = hfss.render(
        design,
        group,
        analysis,
        job_dir=out,
        solve=solve,
        open_gui=open_gui,
        graphical=graphical,
        timeout=timeout,
        airbridges=airbridges,
        aedt=aedt,
        **cfg,
    )
    _print_render(r)
    if not r.ok:
        raise typer.Exit(1)


@hfss_app.command("solve")
def hfss_solve(
    job: Path,
    timeout: float = typer.Option(None, help="Seconds before qcc kills the AEDT process tree it started"),
    graphical: bool = typer.Option(False, help="Run with the AEDT window instead of -ng"),
    aedt: str = typer.Option(
        None, "--aedt", help="batch (new -ng AEDT, default) | gui (new AEDT window, left open) | attach (the open AEDT)"
    ),
):
    """Solve an exported Ansys JOB directory (new batch AEDT, a new window or the open AEDT) and collect results."""
    from quantcore_circuits.sim_tools import hfss  # pylint: disable=import-outside-toplevel

    r = hfss.solve_job(job, timeout=timeout, graphical=graphical, aedt=aedt)
    _print_render(r)
    if not r.ok:
        raise typer.Exit(1)


@hfss_app.command("check")
def hfss_check(job: Path):
    """Read JOB's rendered .aedt back: stack, metal sheets, ports / terminations, nets and every solver setting."""
    from quantcore_circuits.sim_tools import hfss  # pylint: disable=import-outside-toplevel

    report = hfss.check_project(job)
    for c in report["checks"]:
        typer.echo(f"{'ok ' if c['ok'] else 'BAD'} {c['check']}  {c['detail']}")
    for row in report["settings"]:
        mark = {True: "ok ", False: "BAD", None: " - "}[row["ok"]]
        typer.echo(f"{mark} setting {row['key']} = {row['expected']!r}  found {row['found']!r}  ({row['where']})")
    typer.echo("OK" if report["ok"] else "FAILED")
    if not report["ok"]:
        raise typer.Exit(1)


@hfss_app.command("collect")
def hfss_collect(
    job: Path,
    aedt: str = typer.Option("batch", "--aedt", help="batch (a new non-graphical AEDT, default) | gui (a new window)"),
):
    """Re-export a solved job from its saved project as it is now (no solve), e.g. after you changed the setup in AEDT
    and solved there; then ``qcc results import DESIGN JOB``. Close the project in your own AEDT first, or run
    ``scripts/qcc_collect.py`` in that AEDT (Tools > Run Script) instead."""
    from quantcore_circuits.guiflow import convergence_feedback  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.sim_tools import hfss  # pylint: disable=import-outside-toplevel

    if aedt not in ("batch", "gui"):
        raise typer.BadParameter("--aedt is batch or gui")
    try:
        r = hfss.collect_job(job, aedt=aedt)
    except FileNotFoundError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(f"collected {r.job_dir} in {r.seconds:.0f} s ({'ok' if r.ok else 'FAILED'}; log {r.log})")
    typer.echo(f"mesh: {convergence_feedback(job)['message']}")
    if not r.ok:
        raise typer.Exit(1)


@sim_app.command("subset")
def sim_subset_cmd(
    design: Path,
    instances: str = typer.Option(
        "", "--instances", "-i", help="Components to simulate, comma separated. q3d_cmatrix: qubits and/or their "
        "readout routes (Q1,R1), resonators cut to a stub port; eigenmode / driven: exactly these components (plus the "
        "routes joining them and the pads at a selected line's ends), lines leaving the box end in 50 ohm"
    ),
    default: bool = typer.Option(False, "--default", help="No --instances: the first qubit with its readout"),
    whole: bool = typer.Option(False, "--whole", help="The whole chip (slow, memory hungry)"),
    out: Path = typer.Option(None, "-o", help="Job folder (one box) or the folder that holds one job per box"),
    analysis: str = typer.Option(
        "q3d_cmatrix", "--analysis", "-a", help="q3d_cmatrix (cheap, fills the LOM) | eigenmode_epr | "
        "hfss_eigenmode | hfss_driven"
    ),
    fast: bool = typer.Option(True, "--fast/--full", help="Fast solver settings (default) or the analysis defaults"),
    margin: float = typer.Option(300.0, help="Margin (um) around the selection"),
    name: str = typer.Option("gui_sim", help="Name of the sim group(s) written into the design"),
    write_group: bool = typer.Option(True, "--write-group/--no-write-group", help="Store the sim group in the design"),
    group: str = typer.Option(None, "--group", "-g", help="Export a saved sim_groups entry as it is (writes nothing)"),
    set_: list[str] = typer.Option(None, "--set", help="Solver setting key=value, repeatable (with --full: on top of "
                                   "the analysis defaults), e.g. --set maximum_passes=12 --set percent_error=1"),
):
    """Export the job folder of a subset (no solve): geometry, AEDT scripts, job.json, README.md (what to run and
    what to bring back) and results_template.json. Solve it by hand or elsewhere; read it back with ``qcc results
    import``."""
    from quantcore_circuits import guiflow  # pylint: disable=import-outside-toplevel

    try:
        guiflow.export_manual(
            design, [n.strip() for n in instances.split(",") if n.strip()], default, whole, out, analysis, name,
            margin, fast, write_group, say=typer.echo, settings=_settings(set_), group=group,
        )
    except (ValueError, FileExistsError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e


@sim_app.command("preview")
def sim_preview_cmd(
    design: Path,
    instances: str = typer.Option("", "--instances", "-i", help="Components, as for `qcc sim subset`"),
    default: bool = typer.Option(False, "--default", help="No --instances: the first qubit with its readout"),
    whole: bool = typer.Option(False, "--whole", help="The whole chip"),
    group: str = typer.Option(None, "--group", "-g", help="A saved sim_groups entry, as it is"),
    analysis: str = typer.Option(None, "--analysis", "-a", help="Default q3d_cmatrix; with --group the group's first"),
    margin: float = typer.Option(300.0, help="Margin (um) around the selection"),
    name: str = typer.Option("gui_sim", help="Name of the sim group(s) the export would write"),
):
    """Print as JSON what `qcc sim subset` would render (no file is written): the box, the components and routes in it
    and every port (50 ohm edge ports, cut stubs, junction ports) with its position. The KLayout plugin draws it."""
    import json  # pylint: disable=import-outside-toplevel

    from quantcore_circuits import guiflow  # pylint: disable=import-outside-toplevel

    try:
        out = guiflow.preview_groups(
            design, [n.strip() for n in instances.split(",") if n.strip()], default, whole,
            analysis or (None if group else "q3d_cmatrix"), margin, name, group,
        )
    except (ValueError, FileNotFoundError) as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(json.dumps(out))


@sim_app.command("auto")
def sim_auto_cmd(
    design: Path,
    instances: str = typer.Option("", "--instances", "-i", help="Qubits and/or readout routes, comma separated"),
    default: bool = typer.Option(False, "--default", help="No --instances: the first qubit with its readout"),
    whole: bool = typer.Option(False, "--whole", help="The whole chip (slow, memory hungry)"),
    analysis: str = typer.Option("q3d_cmatrix", "--analysis", "-a"),
    aedt: str = typer.Option("batch", "--aedt", help="batch (a new non-graphical AEDT, default) | gui (a new window)"),
    fast: bool = typer.Option(True, "--fast/--full", help="Fast solver settings (default)"),
    margin: float = typer.Option(300.0, help="Margin (um) around the selection"),
    name: str = typer.Option("gui_sim", help="Name of the sim group(s) written into the design"),
    timeout: float = typer.Option(3600.0, help="Seconds per solve before qcc stops the AEDT it started"),
    status: Path = typer.Option(None, help="Status file (JSON) the KLayout plugin polls"),
    set_: list[str] = typer.Option(None, "--set", help="Solver setting key=value, repeatable (with --full: on top of "
                                   "the analysis defaults), e.g. --set maximum_passes=12 --set percent_error=1"),
):
    """Automatic simulation: subset -> export -> solve in a NEW AEDT (never the one you have open) -> analyse. Fills
    the LOM of the simulated components; ``qcc analyse`` / the KLayout Results tab show it against the targets."""
    from quantcore_circuits import guiflow  # pylint: disable=import-outside-toplevel

    if aedt not in ("batch", "gui"):
        raise typer.BadParameter("--aedt is batch or gui (qcc sim auto never attaches to a window you have open)")
    try:
        out = guiflow.run_auto(
            design, [n.strip() for n in instances.split(",") if n.strip()], default, whole, analysis, name, margin,
            aedt, fast, timeout, status, say=typer.echo, settings=_settings(set_),
        )
    except Exception as e:  # noqa: BLE001
        typer.echo(f"error: {type(e).__name__}: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(f"done in {out['seconds']:.0f} s: {out['summary']}")


@sim_app.command("run")
def sim_run(job: Path, dry_run: bool = typer.Option(False, help="Only print the command")):
    """Run a job locally (AEDT / Elmer / Palace) and collect results."""
    from quantcore_circuits.sim_tools.runner import job_summary, run_job  # pylint: disable=import-outside-toplevel

    res = run_job(job, dry_run=dry_run)
    typer.echo(" ".join(res["command"]) if dry_run else job_summary(job))


@sim_app.command("submit")
def sim_submit(job: Path, queue: Path = typer.Option(..., help="Queue directory")):
    from quantcore_circuits.sim_tools.runner import submit  # pylint: disable=import-outside-toplevel

    typer.echo(f"queued {submit(job, queue)}")


@runner_app.command("serve")
def runner_serve(queue: Path, poll: float = 5.0, once: bool = False):
    """Process the filesystem queue (run on the lab server)."""
    from quantcore_circuits.sim_tools.runner import serve  # pylint: disable=import-outside-toplevel

    serve(queue, poll=poll, once=once)


@runner_app.command("status")
def runner_status(queue: Path):
    from quantcore_circuits.sim_tools.runner import queue_status  # pylint: disable=import-outside-toplevel

    typer.echo(json.dumps(queue_status(queue), indent=2))


# ---- results ------------------------------------------------------------------------------------------------------
@app.command()
def analyse(
    design: Path,
    job: Path,
    group: str = typer.Option(None, "--group", "-g", help="Sim group (default: the job's)"),
    run_dir: Path = typer.Option(None, help="Dashboard run directory (default build/<design name>)"),
    readout: bool = typer.Option(True, help="Simulate the readout (χ from transmission) with QuTiP"),
    propose: bool = typer.Option(False, "--feedback", help="Also propose the next design revision (surrogate)"),
):
    """Job results → circuit.json → Metal LOM / QuCat / SQcircuit / scqubits / QuTiP → consensus vs targets."""
    from quantcore_circuits import loop  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.circuit.consensus import report_markdown  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.track import Run  # pylint: disable=import-outside-toplevel

    run = Run(design, run_dir)
    an = loop.analyse(design, job, group, run=run, readout=readout, out_dir=run.dir)
    typer.echo(report_markdown(an.rows, f"Consensus {an.model.name}"))
    for note in an.filled.notes:
        typer.echo(f"note: {note}")
    if an.readout:
        typer.echo(
            f"readout chi {an.readout['chi_readout_MHz']:.4f} MHz vs eigen {an.readout['chi_eigen_MHz']:.4f} MHz"
        )
    typer.echo(f"goal: {an.goal['summary']}   (dashboard state: {run.path})")
    if propose:
        prop, rev, _ = loop.feedback(an, run, design)
        typer.echo(f"proposed {rev}: " + ", ".join(f"{k}={v:g}" for k, v in prop.knobs.items()))


@results_app.command("collect")
def results_collect(job: Path):
    """Parse solver outputs in JOB into results/results.json."""
    from quantcore_circuits.analysis.results import collect_results  # pylint: disable=import-outside-toplevel

    res = collect_results(job)
    typer.echo(json.dumps({k: v for k, v in res.items() if k != "raw_files"}, indent=2)[:4000])


@results_app.command("extract")
def results_extract(design: Path, job: Path, store: Path = typer.Option(None, help="Results store (sqlite)")):
    """Extract Hamiltonian parameters from JOB results and compare with design targets."""
    from quantcore_circuits.analysis.extract import compare, extract  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.analysis.results import collect_results  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import load_design  # pylint: disable=import-outside-toplevel

    d = load_design(design)
    res = collect_results(job)
    params = extract(d, res)
    for row in compare(d.targets, params):
        err = "" if row["error"] is None else f"{row['error']:+.4g}"
        typer.echo(
            f"  {row['instance']:6s} {row['quantity']:12s} target {row['target']:<10g} "
            f"got {row['value'] if row['value'] is not None else '-'!s:<22} {err}"
        )
    if store:
        from quantcore_circuits.analysis.store import ResultsStore  # pylint: disable=import-outside-toplevel

        rid = ResultsStore(store).put(
            res["design_hash"], res["group"], res["analysis"], params, design=d.name, job_dir=job
        )
        typer.echo(f"stored as #{rid} in {store}")


@results_app.command("import")
def results_import_cmd(
    design: Path,
    sources: list[Path] = typer.Argument(..., help="Solved job folder(s) or results.json file(s)"),
    group: str = typer.Option(None, "--group", "-g", help="Sim group the results belong to (default: from the job)"),
):
    """Read solved results back (a job folder, its results/ folder or a results.json: format in `qcc results
    template --format`), check them against the design and analyse them (the KLayout Results tab shows the outcome)."""
    from quantcore_circuits import guiflow  # pylint: disable=import-outside-toplevel

    try:
        out = guiflow.import_results(design, sources, group, say=typer.echo)
    except ValueError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(f"imported: {out['summary']}")


@results_app.command("template")
def results_template_cmd(
    design: Path,
    out: Path = typer.Option(None, "-o", help="Write the skeleton here (default: print it)"),
    group: str = typer.Option("chip", "--group", "-g"),
    analysis: str = typer.Option("q3d_cmatrix", "--analysis", "-a"),
    show_format: bool = typer.Option(False, "--format", help="Print the results.json format description instead"),
):
    """A results.json skeleton with this design's net names (with --format: the format description)."""
    from quantcore_circuits import guiflow  # pylint: disable=import-outside-toplevel

    if show_format:
        typer.echo(guiflow.RESULTS_FORMAT)
        return
    text = json.dumps(guiflow.results_template(design, group, analysis), indent=2)
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
        typer.echo(f"wrote {out}")
    else:
        typer.echo(text)


@results_app.command("propose")
def results_propose_cmd(
    design: Path,
    job: list[Path] = typer.Option(
        None, "--job", help="Job folder(s) to analyse (default: the last run's, else the layout estimates)"
    ),
    out: Path = typer.Option(None, "-o", help="Write the proposal (JSON) here"),
):
    """Propose the next design revision (loop.feedback: every qubit with a LOM model and a lambda/4 or lambda/2
    readout) as old -> new knob values; nothing is written to the design. ``qcc results apply`` sets them."""
    from quantcore_circuits import guiflow  # pylint: disable=import-outside-toplevel

    res = guiflow.propose(design, list(job) if job else None, out, say=typer.echo)
    typer.echo(f"basis: {res['basis']}")
    for k in res["knobs"]:
        typer.echo(f"  {k['knob']}: {k['old']:g} -> {k['new']:g}")
    for k in res["moved"]:
        typer.echo(f"  also moves {k['path']}: {k['old']} -> {k['new']}")
    for note in res.get("notes", []):
        typer.echo(f"  not tuned: {note}")
    typer.echo(res["message"])


@results_app.command("apply")
def results_apply_cmd(
    design: Path,
    proposal: Path = typer.Argument(..., help="proposal.json from `qcc results propose -o`"),
    out: Path = typer.Option(None, "-o", help="Write the new design here (default: overwrite DESIGN)"),
):
    """DESIGN with the proposal's knobs set (refuses when the design changed since the proposal)."""
    from quantcore_circuits import guiflow  # pylint: disable=import-outside-toplevel

    try:
        guiflow.apply_knobs(design, json.loads(Path(proposal).read_text(encoding="utf-8")), out or design)
    except ValueError as e:
        typer.echo(f"error: {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(f"wrote {out or design}")


@results_app.command("show")
def results_show(design: Path, store: Path = typer.Option(Path("results.sqlite"))):
    from quantcore_circuits.analysis.store import ResultsStore  # pylint: disable=import-outside-toplevel
    from quantcore_circuits.design import design_hash, load_design  # pylint: disable=import-outside-toplevel

    d = load_design(design)
    for row in ResultsStore(store).query(design_hash=design_hash(d)):
        typer.echo(f"#{row['id']} {row['created']} {row['group']}/{row['analysis']}: {json.dumps(row['data'])}")


if __name__ == "__main__":
    app()
