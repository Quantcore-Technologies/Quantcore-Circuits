"""Edit-menu actions that change design.json parts the drawing tools do not reach: rename a component, chip settings
(label, die size), junction values (Lj, Cj) of a qubit, a lumped coupling between two components, and the PDK pad-edge
fix. The pure edits are in ``design_ops`` (unit-tested); this module is the dialogs and menu functions.

An exception never escapes into KLayout: it goes to the status bar and the log (``session.report_error``)."""

from __future__ import annotations

import pya  # type: ignore

from qcc_kplugin import actions, design_ops
from qcc_kplugin.session import SESSION, message, ok_cancel, report_error


def _num(v) -> str:
    return "" if v is None else format(float(v), ".12g")


def _form(title: str):
    dialog = pya.QDialog(pya.Application.instance().main_window())
    dialog.windowTitle = title
    return dialog, pya.QFormLayout(dialog)


def _float(text: str, what: str) -> float | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError as e:
        raise ValueError(f"{what}: {text!r} is not a number") from e


SQUARE_TEXT = "Square die (height = width)"


def die_size_rows(dialog, form, width: float, height: float):
    """Die width / height rows and a "square" checkbox (on: the height follows the width and is greyed out), for New
    design and Chip settings. Returns ``size()`` → (width, height) in µm; raises ValueError on a non-number."""
    e_w = pya.QLineEdit(_num(width), dialog)
    e_h = pya.QLineEdit(_num(height), dialog)
    e_sq = pya.QCheckBox(SQUARE_TEXT, dialog)
    e_sq.checked = abs(float(width) - float(height)) < 1e-9

    def follow(*_):
        e_h.enabled = not e_sq.checked
        if e_sq.checked:
            e_h.text = e_w.text

    e_sq.toggled(follow)
    e_w.textChanged(follow)
    follow()
    form.addRow("Die width µm", e_w)
    form.addRow("Die height µm", e_h)
    form.addRow(e_sq)

    def size():
        w = _float(e_w.text, "width")
        h = w if e_sq.checked else _float(e_h.text, "height")
        if w is None or h is None:
            raise ValueError("the die width and height are needed")
        if w <= 0 or h <= 0:
            raise ValueError("the die width and height must be positive")
        return w, h

    return size


def rename_instance(name: str | None = None) -> None:
    """Edit > Rename component…: the selected component (KLayout's selection, or under the Move/Snap cursor) gets a new
    name; routes, snaps, targets, sim groups and couplings that name it follow."""
    try:
        name = name or actions.selected_component()
        if name is None:
            message("select a component first (KLayout's select tool, or point at it in Move/Snap), then Rename")
            return
        dialog, form = _form(f"Rename {name}")
        e_new = pya.QLineEdit(name, dialog)
        form.addRow("New name", e_new)
        form.addRow(ok_cancel(dialog))
        if not dialog.exec_():
            return
        new = e_new.text.strip()
        if new == name:
            return
        design = SESSION.design()
        design_ops.rename_instance(design, name, new)
        SESSION.commit(design, f"renamed {name} to {new}")
    except ValueError as e:
        message(f"Rename: {e}", 8)
    except Exception:  # noqa: BLE001
        report_error("renaming the component")


def chip_settings() -> None:
    """Design > Chip settings…: the label on the die, the die width and height, the KQC ground grid, and the
    design's substrate (thickness, εr, loss tangent)."""
    try:
        design = SESSION.design()
        chip = design.get("chip", {})
        box = chip.get("box") or [0.0, 0.0, 7500.0, 7500.0]
        params = chip.get("params", {})
        dialog, form = _form("Chip settings")
        e_name = pya.QLineEdit(str(params.get("name_chip", "")), dialog)
        form.addRow("Label on the die", e_name)
        size_of = die_size_rows(dialog, form, box[2] - box[0], box[3] - box[1])
        e_grid = pya.QCheckBox("KQC ground-plane grid (with_grid); off = the PDK band", dialog)
        e_grid.checked = bool(params.get("with_grid", False))
        form.addRow(e_grid)
        pdk = (SESSION.data or {}).get("pdk", {})
        sub = design_ops.substrate_of(pdk)
        e_h = pya.QLineEdit(_num(sub["h"]), dialog)
        e_eps = pya.QLineEdit(_num(sub["eps_r"]), dialog)
        e_tand = pya.QLineEdit(_num(sub["tan_d"]), dialog)
        base = pdk.get("base_substrate") or sub
        e_h.toolTip = e_eps.toolTip = e_tand.toolTip = (
            f"This design's substrate ({pdk.get('substrate_material', 'sapphire')}); the PDK's: {base['h']:g} µm, "
            f"εr {base['eps_r']:g}, tan δ {base['tan_d']:g}. The LOM, the length estimates and the simulation "
            "exports use these")
        form.addRow("Substrate thickness µm", e_h)
        form.addRow("Substrate εr (dk)", e_eps)
        form.addRow("Substrate loss tangent tan δ", e_tand)
        form.addRow(ok_cancel(dialog))
        if not dialog.exec_():
            return
        size = size_of()
        done = design_ops.set_chip(design, e_name.text.strip(), bool(e_grid.checked), size)
        vals = [_float(w.text, what) for w, what in ((e_h, "thickness"), (e_eps, "εr"), (e_tand, "loss tangent"))]
        vals = [base[k] if v is None else v for k, v in zip(design_ops.SUBSTRATE_KEYS, vals)]  # empty: the PDK's
        changed = design_ops.set_substrate(design, base, *vals)
        if changed:
            done.append(changed)
        if done:
            SESSION.commit(design, "chip: " + ", ".join(done))
    except ValueError as e:
        message(f"Chip settings: {e}", 8)
    except Exception:  # noqa: BLE001
        report_error("chip settings")


def junction_values(name: str | None = None) -> None:
    """Edit > Junction values (L_J or I_c or R_n, and C_J)…: the lumped junction of the selected qubit that the LOM,
    the estimates and the simulations use (``junction`` in design.json: L_J and C_J); empty fields remove it."""
    try:
        name = name or actions.selected_component()
        if name is None:
            message("select a qubit first (KLayout's select tool, or point at it in Move/Snap), then Junction values")
            return
        design = SESSION.design()
        from qcc_kplugin import tools  # pylint: disable=import-outside-toplevel

        dialog, form = _form(f"Junction of {name}")
        entry = design["instances"][name]
        info = tools.junction_info(name)
        rows = tools.JunctionRows(dialog, form, entry.get("junction"), info, tools.drawn_junction_value(entry, info))
        form.addRow(ok_cancel(dialog))
        if not dialog.exec_():
            return
        vals = rows.values()
        if vals is None:
            message(f"{name} has several junctions (a list): edit them in design.json", 8)
            return
        if design_ops.set_junction(design, name, *vals):
            SESSION.commit(design, f"{name}: junction {design['instances'][name].get('junction') or 'removed'}")
    except ValueError as e:
        message(f"Junction values: {e}", 8)
    except Exception:  # noqa: BLE001
        report_error("junction values")


def add_coupling() -> None:
    """Edit > Add coupling…: a lumped C (fF) or L (nH) between two components or a route and a component, for the LOM
    (the layout implies it but no route carries it, e.g. two facing qubit arms)."""
    try:
        design = SESSION.design()
        ends = sorted(design.get("instances", {})) + sorted(design.get("routes", {}))
        if len(ends) < 2:
            message("a coupling needs two components or routes")
            return
        dialog, form = _form("Add coupling")
        e_name = pya.QLineEdit(f"C_{len(design.get('couplings') or {}) + 1}", dialog)
        e_a = pya.QComboBox(dialog)
        e_a.setEditable(True)
        e_a.addItems(ends)
        e_b = pya.QComboBox(dialog)
        e_b.setEditable(True)
        e_b.addItems(ends)
        e_b.setCurrentIndex(1)
        e_type = pya.QComboBox(dialog)
        e_type.addItems(["C", "L", "wire"])
        e_val = pya.QLineEdit("", dialog)
        e_val.toolTip = "fF for C, nH for L; empty = no value yet (a FEM result fills it)"
        e_note = pya.QLineEdit("", dialog)
        form.addRow("Name", e_name)
        form.addRow("Between", e_a)
        form.addRow("and", e_b)
        form.addRow("Type", e_type)
        form.addRow("Value (fF / nH, empty = none)", e_val)
        form.addRow("Note", e_note)
        form.addRow(ok_cancel(dialog))
        if not dialog.exec_():
            return
        name = e_name.text.strip()
        if not name:
            raise ValueError("the coupling needs a name")
        design_ops.set_coupling(design, name, e_a.currentText.strip(), e_b.currentText.strip(), e_type.currentText,
                                _float(e_val.text, "value"), e_note.text.strip())
        SESSION.commit(design, f"coupling {name}: {e_a.currentText} - {e_b.currentText} ({e_type.currentText})")
    except ValueError as e:
        message(f"Add coupling: {e}", 8)
    except Exception:  # noqa: BLE001
        report_error("adding the coupling")


def fix_pad_edges() -> None:
    """Check and LOM > Fix pad edge warnings: ``place.edge = "auto"`` on every pad the PDK pad-edge rule flags (the
    build then puts its outer edge the PDK distance from the die edge, the position along the edge stays)."""
    try:
        if SESSION.data is None:
            SESSION.attach_view()
        names = design_ops.pad_edge_instances((SESSION.data or {}).get("drc", []))
        if not names:
            message("no pad-edge warnings: nothing to fix (run Check first if the design changed)")
            return
        design = SESSION.design()
        done = design_ops.apply_pad_edge(design, names)
        if not done:
            message("the flagged pads cannot be moved by the edge rule (snapped placements)", 8)
            return
        SESSION.commit(design, f"pad edge rule (edge = auto): {', '.join(done)}")
    except Exception:  # noqa: BLE001
        report_error("the pad edge fix")
