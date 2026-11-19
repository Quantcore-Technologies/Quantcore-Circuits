"""Scripts that run *inside* AEDT (2024 R1/R2): batch ``ansysedt -ng -RunScriptAndExit``, a new window
``ansysedt -RunScript``, or ``oDesktop.RunScriptWithArguments`` in an attached session (:mod:`.aedt_session`). The
status file ends with ``end`` (a window / attached session stays open, so the process does not end with the run).

One source, two file names in the job's ``scripts/`` folder:

* ``qcc_render.py`` — import the KQC simulation (KQC ``import_simulation_geometry.py``), fix the ports KQC leaves
  unassigned, add the Q3D π-model and reports, save ``<sim>_project.aedt``. No solve.
* ``qcc_solve.py`` — the same, then ``AnalyzeAll``, KQC ``export_solution_data.py`` (C-matrix json, ``.eig``,
  Touchstone) and ``<sim>_project_qcc.json`` (excitation order, variables, convergence, and for eigenmode jobs with
  junction lines the pyEPR field integrals per mode).
* ``qcc_collect.py`` — no import, no solve: the exports of ``qcc_solve.py`` from the job's saved project as it is now
  (e.g. after the user changed the setup in AEDT and solved again there). In the user's open AEDT: *Tools ▸ Run
  Script…* ``scripts/qcc_collect.py`` (it finds the job from its own folder; the project open in that AEDT is used,
  and nothing is saved). Headless: ``qcc hfss collect JOB`` opens the saved project in a new non-graphical AEDT.

Port fix-ups (KQC's importer handles only junction ports in eigenmode, and makes every port a terminal port in a
driven design):

* eigenmode: every non-junction port with a resistance (the 50 Ω edge / pad terminations the builder adds) becomes a
  ``Lumped RLC`` boundary R = 50 Ω, so the eigenmode Q carries the external loss (κ);
* driven (HFSS terminal network): junction ports are deleted as excitations and become ``Lumped RLC`` L = ``Lj_<n>``,
  C = ``Cj_<n>`` (design variables), so the S-matrix has only the real (pad / wave) ports.

EPR (``eigenmode_epr``; KQC draws a ``Junction<n>`` line over each junction): per mode, pyEPR's own calculator stack
(``DistributedAnalysis.calc_energy_electric/_magnetic`` and ``calc_current_using_line_voltage``): U_E = ∫Re(E·εE*),
U_H = ∫Re(H·μH*), U_E per substrate volume, and the junction line voltage (real and imaginary parts). The
participations and the Hamiltonian are computed afterwards outside AEDT (:mod:`quantcore_circuits.analysis.epr`).
This replaces KQC's ``run_pyepr_t1_estimate.py``, which attaches to a *running* AEDT over COM and ends with
``QuitApplication()`` (it would close a user's open AEDT window).
"""

from __future__ import annotations

from pathlib import Path

RENDER_SCRIPT = "qcc_render.py"
SOLVE_SCRIPT = "qcc_solve.py"
COLLECT_SCRIPT = "qcc_collect.py"
STATUS_FILE = {"render": "qcc_render_status.txt", "solve": "qcc_solve_status.txt", "collect": "qcc_collect_status.txt"}
SCRIPT_MODE = {RENDER_SCRIPT: "render", SOLVE_SCRIPT: "solve", COLLECT_SCRIPT: "collect"}
EXTRAS_SUFFIX = "_project_qcc.json"

# IronPython 2.7 and CPython 3 compatible (AEDT's script engines): no f-strings, no keyword-only syntax.
AEDT_SOURCE = r'''# qcc: import a KQC simulation into AEDT; as qcc_solve.py also solve and export
# (quantcore_circuits.sim_tools.aedt_scripts). Sub-scripts are exec'd in-process so that their tracebacks
# land in the status file.
import json
import os
import sys
import time
import traceback

import ScriptEnv

ScriptEnv.Initialize("Ansoft.ElectronicsDesktop")
try:
    jsonfile = ScriptArgument or ""
except NameError:  # Tools > Run Script without arguments
    jsonfile = ""
MODE = None
if "|" in jsonfile:  # "<mode>|<sim json>" (optional; for script hosts that do not set __file__)
    MODE, jsonfile = jsonfile.split("|", 1)
try:
    scriptpath = os.path.dirname(os.path.abspath(__file__))
    _own = os.path.basename(__file__)
    MODE = MODE or ("solve" if _own.startswith("qcc_solve") else "collect" if _own.startswith("qcc_collect")
                    else "render")
except NameError:
    scriptpath = os.path.join(os.path.dirname(os.path.abspath(jsonfile)), "scripts")
    MODE = MODE or "solve"
if not jsonfile:  # the job's simulation json, from job.json next to the scripts folder
    with open(os.path.join(os.path.dirname(scriptpath), "job.json"), "r") as fp:
        jsonfile = os.path.join(os.path.dirname(scriptpath), json.load(fp)["simulation_name"] + ".json")
elif not os.path.isabs(jsonfile) and not os.path.exists(jsonfile):
    jsonfile = os.path.join(os.path.dirname(scriptpath), jsonfile)
path = os.path.abspath(os.path.dirname(jsonfile))
basename = os.path.splitext(os.path.basename(jsonfile))[0]
status = open(os.path.join(path, "qcc_%s_status.txt" % MODE), "w")


def log(msg):
    status.write(msg + "\n")
    status.flush()


def step(name, script, args=None):
    log("step " + name)
    t0 = time.time()
    env = {"__file__": os.path.join(scriptpath, script), "__name__": "__main__", "oDesktop": oDesktop}
    if args is not None:
        env["ScriptArgument"] = args
    with open(os.path.join(scriptpath, script)) as fp:
        code = compile(fp.read(), os.path.join(scriptpath, script), "exec")
    exec(code, env)
    log("ok %s %.1f s" % (name, time.time() - t0))


def coords(p, units):
    return ["%.32e%s" % (x, units) for x in p]


def add_variable(oDesign, name, value):
    oDesign.ChangeProperty(
        [
            "NAME:AllTabs",
            [
                "NAME:LocalVariableTab",
                ["NAME:PropServers", "LocalVariables"],
                ["NAME:NewProps", ["NAME:" + name, "PropType:=", "VariableProp", "UserDef:=", True, "Value:=", value]],
            ],
        ]
    )


def lumped_rlc(oDesign, port, units, name, r=None, l_var=None, c_var=None):
    oEditor = oDesign.SetActiveEditor("3D Modeler")
    poly = "Port%d" % port["number"]
    args = [
        "NAME:" + name,
        "Objects:=",
        [poly],
        [
            "NAME:CurrentLine",
            "Coordinate System:=",
            "Global",
            "Start:=",
            coords(port["signal_location"], units),
            "End:=",
            coords(port["ground_location"], units),
        ],
        "RLC Type:=",
        "Parallel",
        "UseResist:=",
        r is not None,
    ]
    if r is not None:
        args += ["Resistance:=", "%.12gohm" % r]
    args += ["UseInduct:=", l_var is not None]
    if l_var is not None:
        args += ["Inductance:=", l_var]
    args += ["UseCap:=", c_var is not None]
    if c_var is not None:
        args += ["Capacitance:=", c_var]
    args += ["Faces:=", [int(oEditor.GetFaceIDs(poly)[0])]]
    oDesign.GetModule("BoundarySetup").AssignLumpedRLC(args)


def boundaries(oDesign):
    try:
        return [str(b) for b in oDesign.GetModule("BoundarySetup").GetBoundaries()]
    except Exception:
        return []


def fix_ports(oDesign, data, tool, units):
    """Eigenmode: 50 ohm terminations as Lumped RLC; driven: junction ports -> Lumped RLC L/C (see module doc)."""
    oBoundary = oDesign.GetModule("BoundarySetup")
    for port in sorted(data.get("ports", []), key=lambda p: p["number"]):
        n = port["number"]
        if "polygon" not in port:
            continue
        if tool == "eigenmode" and not port.get("junction") and port.get("resistance"):
            lumped_rlc(oDesign, port, units, "LumpRLC_term_%d" % n, r=float(port["resistance"]))
            log("fix Port%d: 50 ohm termination (Lumped RLC R=%g ohm)" % (n, float(port["resistance"])))
        elif tool == "hfss" and port.get("junction"):
            before = boundaries(oDesign)
            try:
                oBoundary.DeleteBoundaries([str(n)])
            except Exception:
                log("warn could not delete excitation %d\n%s" % (n, traceback.format_exc()))
            add_variable(oDesign, "Lj_%d" % n, "%.32eH" % port["inductance"])
            add_variable(oDesign, "Cj_%d" % n, "%.32efarad" % port["capacitance"])
            lumped_rlc(oDesign, port, units, "LumpRLC_jj_%d" % n, l_var="Lj_%d" % n, c_var="Cj_%d" % n)
            log("fix Port%d: junction excitation -> Lumped RLC L=Lj_%d C=Cj_%d (boundaries before: %s)"
                % (n, n, n, ",".join(before)))


def variables(oDesign):
    out = []
    for v in oDesign.GetVariables():
        out += [str(v) + ":=", str(oDesign.GetVariableValue(v))]
    return out


def epr_energies(oDesign, data, setup="Setup1 : LastAdaptive"):
    """pyEPR's calculator stack per eigenmode (field energies, junction line voltages)."""
    calc = oDesign.GetModule("FieldsReporter")
    sols = oDesign.GetModule("Solutions")
    oEditor = oDesign.SetActiveEditor("3D Modeler")
    n_modes = int(data["analysis_setup"]["n_modes"])
    lv = variables(oDesign)
    juncs = [p for p in data.get("ports", []) if p.get("junction")]
    lines = [str(o) for o in oEditor.GetMatchedObjectName("Junction*")]
    volumes = [str(o) for o in oEditor.GetMatchedObjectName("substrate*")]

    def ev(stack):
        calc.CalcStack("clear")
        for fn, arg in stack:
            f = getattr(calc, fn)
            if isinstance(arg, (list, tuple)):
                f(*arg)
            else:
                f(arg)
        args = lv + ["Phase:=", "0deg"]
        calc.ClcEval(setup, args)
        val = float(calc.GetTopEntryValue(setup, args)[0])
        calc.CalcStack("clear")
        return val

    def energy(qty, material, volume):
        return ev([("EnterQty", qty), ("ClcMaterial", (material, "mult")), ("EnterQty", qty), ("CalcOp", "Conj"),
                   ("CalcOp", "Dot"), ("CalcOp", "Real"), ("EnterVol", volume), ("CalcOp", "Integrate")])

    def line_voltage(part, line):
        return ev([("EnterQty", "E"), ("CalcOp", part), ("EnterLine", line), ("CalcOp", "Tangent"),
                   ("CalcOp", "Dot"), ("EnterLine", line), ("CalcOp", "Integrate")])

    modes = []
    for m in range(1, n_modes + 1):
        sols.EditSources(
            [
                ["FieldType:=", "EigenPeakElectricField"],
                [
                    "Name:=",
                    "Modes",
                    "Magnitudes:=",
                    ["1" if i == m else "0" for i in range(1, n_modes + 1)],
                    "Phases:=",
                    ["0" for i in range(1, n_modes + 1)],
                ],
            ]
        )
        rec = {"mode": m, "junctions": {}, "U_E_volumes": {}}
        try:
            rec["freq_Hz"] = ev([("EnterOutputVar", ("Freq", "Complex")), ("CalcOp", "Real")])
        except Exception:
            log("warn mode %d: Freq output variable\n%s" % (m, traceback.format_exc()))
        rec["U_E"] = energy("E", "Permittivity (epsi)", "AllObjects")
        rec["U_H"] = energy("H", "Permeability (mu)", "AllObjects")
        for v in volumes:
            rec["U_E_volumes"][v] = energy("E", "Permittivity (epsi)", v)
        for p in juncs:
            line = "Junction%d" % p["number"]
            if line not in lines:
                continue
            rec["junctions"][str(p["number"])] = {
                "line": line,
                "V_re": line_voltage("Real", line),
                "V_im": line_voltage("Imag", line),
                "Lj_H": p.get("inductance"),
                "Cj_F": p.get("capacitance"),
            }
        modes.append(rec)
        log("epr mode %d: U_E %.5g U_H %.5g (%d junction lines)" % (m, rec["U_E"], rec["U_H"], len(rec["junctions"])))
    return {"setup": setup, "variables": lv, "lines": lines, "volumes": volumes, "modes": modes}


def export_convergence(oDesign, design_type, filename):
    # Q3D wants the solution kind ("CG" = capacitance/conductance), as pyaedt's export_convergence does
    tries = [("Setup1", "", filename)] if design_type == "HFSS" else [("Setup1", "", "CG", filename, True)]
    for args in tries:
        try:
            oDesign.ExportConvergence(*args)
            return True
        except Exception:
            continue
    return False


def export_convergence_reports(oDesign, prefix):
    """KQC's convergence reports (eigenmode: re(Mode(n)) per adaptive pass; driven: S per pass) as CSV files."""
    import re

    out = {}
    rs = oDesign.GetModule("ReportSetup")
    for name in rs.GetAllReportNames():
        name = str(name)
        if "onvergence" not in name:
            continue
        fn = os.path.join(path, prefix + "_" + re.sub("[^A-Za-z0-9]+", "_", name).strip("_") + ".csv")
        try:
            rs.ExportToFile(name, fn, False)
            out[name] = os.path.basename(fn)
        except Exception:
            log("warn report %s\n%s" % (name, traceback.format_exc()))
    return out


def messages(severity=1):
    """AEDT message-window lines (warnings and errors by default): batch mode has no window to read them in."""
    try:
        return [str(m).strip() for m in oDesktop.GetMessages("", "", severity)]
    except Exception:
        return []


extras = {"mode": MODE}
try:
    extras["python"] = sys.version.split()[0]
    extras["aedt"] = str(oDesktop.GetVersion())
    log("python %s | aedt %s | mode %s" % (extras["python"], extras["aedt"], MODE))
    with open(jsonfile, "r") as fp:
        data = json.load(fp)
    tool = data.get("ansys_tool", "hfss")
    units = data.get("units", "um")
    extras["tool"] = tool
    if MODE == "collect":  # the saved project as it is now: no import, no solve, nothing saved
        log("step open")
        project_name = basename + "_project"
        oProject = None
        for p in oDesktop.GetProjects():
            if str(p.GetName()) == project_name:
                oProject = p
        if oProject is None:
            oProject = oDesktop.OpenProject(os.path.join(path, project_name + ".aedt"))
        oDesktop.SetActiveProject(project_name)
        oDesign = oProject.GetActiveDesign()
        if oDesign is None:
            oDesign = oProject.SetActiveDesign(str(oProject.GetChildNames()[0]))
        log("ok open " + project_name)
        extras["collected"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    else:
        step("import", "import_simulation_geometry.py", jsonfile)
        oProject = oDesktop.GetActiveProject()
        oDesign = oProject.GetActiveDesign()
        fix_ports(oDesign, data, tool, units)
        if tool == "q3d" or data.get("capacitance_export", False):
            step("pi_model", "create_capacitive_pi_model.py")
        try:
            step("reports", "create_reports.py")
        except Exception:  # reports are optional
            log("warn reports\n" + traceback.format_exc())
        oProject.SaveAs(os.path.join(path, basename + "_project.aedt"), True)
        log("saved " + basename + "_project.aedt")
    extras["boundaries"] = boundaries(oDesign)
    if MODE in ("solve", "collect"):
        if MODE == "solve":
            log("step solve")
            t0 = time.time()
            try:
                oDesign.AnalyzeAll()
                log("ok solve %.1f s" % (time.time() - t0))
            except Exception:  # e.g. out of memory in a late pass: keep what the completed passes left
                extras["solve_error"] = [m for m in messages(2)]
                log("error solve %.1f s (exporting what exists)\n%s" % (time.time() - t0, traceback.format_exc()))
                for line in extras["solve_error"]:
                    log("aedt: " + line)
            extras["solve_seconds"] = round(time.time() - t0, 1)
            oProject.Save()
        try:
            extras["convergence_reports"] = export_convergence_reports(oDesign, basename + "_project")
        except Exception:
            log("warn convergence reports\n" + traceback.format_exc())
        step("export", "export_solution_data.py")
        design_type = str(oDesign.GetDesignType())
        extras["design_type"] = design_type
        try:
            extras["excitations"] = [str(x) for x in oDesign.GetModule("BoundarySetup").GetExcitations()]
        except Exception:
            log("warn excitations\n" + traceback.format_exc())
        extras["variables"] = variables(oDesign)
        conv = os.path.join(path, basename + "_project_convergence.txt")
        extras["convergence_file"] = os.path.basename(conv) if export_convergence(oDesign, design_type, conv) else None
        if tool == "eigenmode" and any(p.get("junction") for p in data.get("ports", [])):
            if "pyepr" in data.get("simulation_flags", []):
                try:
                    log("step epr")
                    t0 = time.time()
                    extras["epr"] = epr_energies(oDesign, data)
                    log("ok epr %.1f s" % (time.time() - t0))
                except Exception:
                    log("error epr\n" + traceback.format_exc())
        extras["messages"] = messages()
        with open(os.path.join(path, basename + "_project_qcc.json"), "w") as fp:
            json.dump(extras, fp, indent=1)
        if MODE == "solve":
            oProject.Save()
        log("wrote " + basename + "_project_qcc.json")
    log("done")
except Exception:
    log("error\n" + traceback.format_exc())
    for line in messages():
        log("aedt: " + line)
log("end")  # last line: a GUI / attached session stays open, so this marks the end of the run
status.close()
'''


def write_scripts(job_dir: str | Path) -> Path:
    """Write ``qcc_render.py``, ``qcc_solve.py`` and ``qcc_collect.py`` into ``job_dir/scripts`` (next to KQC's AEDT
    scripts)."""
    scripts = Path(job_dir) / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for name in (RENDER_SCRIPT, SOLVE_SCRIPT, COLLECT_SCRIPT):
        (scripts / name).write_text(AEDT_SOURCE, encoding="utf-8")
    return scripts
