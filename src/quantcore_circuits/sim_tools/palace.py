"""Palace adapter: KQC Elmer export + KQC gmsh mesher → Palace config.

``export_palace`` writes a normal KQC Elmer job (geometry, layer stack, ports, mesh sizes and KQC's
``scripts/gmsh_helpers.py``) and adds:

* ``palace_job.json`` — what to generate (``Electrostatic`` or ``Eigenmode``) and solver settings,
* ``run_palace.sh`` — ``python -m quantcore_circuits.sim_tools.palace prepare .`` then ``mpirun palace palace.json``.

``prepare`` (run where gmsh is available, usually the Linux server) meshes with KQC's ``produce_mesh`` in MSH 2.2
(required by MFEM/Palace), reads the physical groups and writes ``palace.json``:

* volumes → ``Domains.Materials`` (permittivity / loss tangent from the KQC ``material_dict``; vacuum ε=1),
* Electrostatic: ``Ground`` = ``excitation_0_boundary``, ``Terminal`` k = ``excitation_k_boundary`` (same order as
  Q3D ``Net<k>`` / Elmer capacitance bodies, so C-matrix labels from ``job.json`` apply unchanged),
* Eigenmode: ``PEC`` = all metal boundaries + outer box; junction ports → ``LumpedPort`` with ``L = Lj``,
  ``C = Cj``; other internal ports → 50 Ω ``LumpedPort`` (gives κ in ``port-Q.csv``).

Lengths stay in µm (``Model.L0 = 1e-6``).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

PALACE_JOB = "palace_job.json"


def export_palace(setup, job_dir: Path, **cfg) -> Path:
    from kqcircuits.simulations.export.elmer.elmer_export import export_elmer  # pylint: disable=C0415
    from kqcircuits.simulations.export.elmer.mesh_size_helpers import refine_metal_edges  # pylint: disable=C0415

    eig = setup.analysis == "palace_eig"
    mesh_size = {"global_max": cfg.get("mesh_global_max", 100.0), **refine_metal_edges(cfg.get("mesh_edge", 4.0))}
    common = {
        "mesh_size": mesh_size,
        "mesh_options": {"Mesh.MshFileVersion": 2.2},
        "workflow": {"run_gmsh_gui": False, "run_elmergrid": False, "run_elmer": False, "run_paraview": False},
    }
    if eig:
        # wave_equation makes KQC's mesher create port surfaces (needed for the junction LumpedPort)
        export_elmer(
            [setup.simulation], path=job_dir, tool="wave_equation", frequency=cfg.get("target_GHz", 3.0), **common
        )
    else:
        export_elmer([setup.simulation], path=job_dir, tool="capacitance", **common)
    spec = {
        "problem": "Eigenmode" if eig else "Electrostatic",
        "order": cfg.get("order", 2),
        "n_modes": cfg.get("n_modes", 2),
        "target_GHz": cfg.get("target_GHz", 3.0),
        "simulation": setup.simulation.name.lower().replace(".", "-"),
        "mpi_processes": cfg.get("mpi_processes", 8),
    }
    (job_dir / PALACE_JOB).write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    sh = job_dir / "run_palace.sh"
    sh.write_text(
        '#!/bin/bash\nset -e\ncd "$(dirname "$0")"\n'
        f"${{QCC_PYTHON:-python3}} -m quantcore_circuits.sim_tools.palace prepare .\n"
        f"${{QCC_MPIRUN:-mpirun}} -np ${{QCC_NP:-{spec['mpi_processes']}}} ${{QCC_PALACE:-palace}} palace.json\n",
        encoding="utf-8",
        newline="\n",
    )
    return job_dir


def read_physical_names(msh_path: Path) -> dict[str, tuple[int, int]]:
    """``$PhysicalNames`` of an ASCII .msh → {name: (dim, tag)}."""
    text = Path(msh_path).read_text(encoding="utf-8", errors="replace")
    block = re.search(r"\$PhysicalNames\s*\n(\d+)\s*\n(.*?)\$EndPhysicalNames", text, re.S)
    if not block:
        raise ValueError(f"{msh_path}: no $PhysicalNames section")
    out = {}
    for line in block.group(2).strip().splitlines():
        m = re.match(r'\s*(\d+)\s+(\d+)\s+"(.*)"', line)
        if m:
            out[m.group(3)] = (int(m.group(1)), int(m.group(2)))
    return out


def _axis_direction(v) -> str | list:
    x, y = v[0], v[1]
    if abs(x) < 1e-12 and abs(y) > 0:
        return "+Y" if y > 0 else "-Y"
    if abs(y) < 1e-12 and abs(x) > 0:
        return "+X" if x > 0 else "-X"
    n = (x * x + y * y) ** 0.5
    return [x / n, y / n, 0.0]


def palace_config(sim_json: dict, physical: dict[str, tuple[int, int]], spec: dict, mesh_file: str) -> dict:
    """Palace configuration dict from a KQC simulation JSON and mesh physical groups."""
    materials_db = sim_json.get("material_dict", {})
    if isinstance(materials_db, str):
        import ast  # pylint: disable=import-outside-toplevel

        materials_db = ast.literal_eval(materials_db)
    volumes = {n: t for n, (d, t) in physical.items() if d == 3}
    surfaces = {n: t for n, (d, t) in physical.items() if d == 2}

    materials = []
    layers = sim_json["layers"]
    for name, tag in volumes.items():
        layer = layers.get(name, {})
        mat = layer.get("material", "vacuum")
        if mat == "pec":
            continue
        props = materials_db.get(mat, {})
        entry = {"Attributes": [tag], "Permeability": 1.0, "Permittivity": props.get("permittivity", 1.0)}
        if props.get("dielectric_loss_tangent"):
            entry["LossTan"] = props["dielectric_loss_tangent"]
        materials.append(entry)

    exc = {}
    for n, t in surfaces.items():
        m = re.fullmatch(r"excitation_(\d+)_boundary", n)
        if m:
            exc[int(m.group(1))] = t
    boundaries: dict = {}
    if spec["problem"] == "Electrostatic":
        boundaries["Ground"] = {"Attributes": [exc[0]]} if 0 in exc else {"Attributes": []}
        boundaries["Terminal"] = [{"Index": k, "Attributes": [t]} for k, t in sorted(exc.items()) if k > 0]
        solver = {"Order": spec["order"], "Device": "CPU", "Electrostatic": {"Save": 0}}
    else:
        pec = sorted(exc.values()) + ([surfaces["domain_boundary"]] if "domain_boundary" in surfaces else [])
        boundaries["PEC"] = {"Attributes": pec}
        ports = []
        for port in sim_json.get("ports", []):
            name = f"port_{port['number']}"
            if name not in surfaces:
                continue
            sig, gnd = port.get("signal_location"), port.get("ground_location")
            direction = _axis_direction([sig[0] - gnd[0], sig[1] - gnd[1]]) if sig and gnd else "+Y"
            entry = {"Index": port["number"], "Attributes": [surfaces[name]], "Direction": direction}
            if port.get("junction"):
                entry["L"] = port.get("inductance", 0.0)
                if port.get("capacitance"):
                    entry["C"] = port["capacitance"]
            else:
                entry["R"] = port.get("resistance", 50.0)
            ports.append(entry)
        if ports:
            boundaries["LumpedPort"] = ports
        solver = {
            "Order": spec["order"],
            "Device": "CPU",
            "Eigenmode": {"N": spec["n_modes"], "Target": spec["target_GHz"], "Save": spec["n_modes"], "Tol": 1e-8},
        }
    solver["Linear"] = {"Type": "Default", "KSPType": "Default", "Tol": 1e-8, "MaxIts": 500}
    return {
        "Problem": {"Type": spec["problem"], "Verbose": 2, "Output": "postpro"},
        "Model": {"Mesh": mesh_file, "L0": 1e-6},
        "Domains": {"Materials": materials},
        "Boundaries": boundaries,
        "Solver": solver,
    }


def prepare(job_dir: str | Path) -> Path:
    """Mesh (KQC ``produce_mesh``, MSH 2.2) and write ``palace.json`` in ``job_dir``."""
    job_dir = Path(job_dir).resolve()
    spec = json.loads((job_dir / PALACE_JOB).read_text(encoding="utf-8"))
    sim_json_path = job_dir / f"{spec['simulation']}.json"
    if not sim_json_path.exists():  # KQC may have adjusted the name; take the single simulation json
        candidates = [
            p
            for p in job_dir.glob("*.json")
            if p.name not in (PALACE_JOB, "job.json") and not p.name.endswith("_VERSIONS.json")
        ]
        sim_json_path = candidates[0]
    sim_json = json.loads(sim_json_path.read_text(encoding="utf-8"))
    sys.path.insert(0, str(job_dir / "scripts"))
    from gmsh_helpers import produce_mesh  # pylint: disable=import-outside-toplevel,import-error

    mesh_name = sim_json.get("mesh_name", sim_json_path.stem)
    msh = job_dir / f"{mesh_name}.msh"
    cwd = os.getcwd()
    try:
        os.chdir(job_dir)
        produce_mesh(sim_json, msh)
    finally:
        os.chdir(cwd)
    config = palace_config(sim_json, read_physical_names(msh), spec, msh.name)
    out = job_dir / "palace.json"
    out.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":  # python -m quantcore_circuits.sim_tools.palace prepare <job_dir>
    if len(sys.argv) >= 3 and sys.argv[1] == "prepare":
        print(prepare(sys.argv[2]))
    else:
        print("usage: python -m quantcore_circuits.sim_tools.palace prepare <job_dir>")
        sys.exit(2)
