"""Dialogs that fit the screen.

A long dialog (route options, a component's parameters, Simulate) used to grow past the bottom of the screen, with its
OK button out of reach and no way to scroll or shrink it. Here:

* :class:`Rows` collects form rows like ``QFormLayout.addRow`` does, in sections, and lays them out in one column, or
  in two when one column would be taller than the screen allows (Settings ▸ "Long dialogs in two columns").
* :func:`fit` puts a dialog's body in a scroll area with the buttons below it (always visible), makes the dialog
  resizable (a size grip) and sizes it to its content, but never wider or taller than the free screen area.
* :func:`fit_window` caps a non-modal window (results text, the circuit picture) to the screen.

Only the layout changes: the widgets, their order and their labels are the dialogs' own.
"""

from __future__ import annotations

import pya  # type: ignore

from qcc_kplugin.session import CFG_DIALOG_COLUMNS, config, log

SCREEN_SHARE = (0.92, 0.88)  # the largest share of the free screen area (width, height) a dialog takes
TWO_COLUMNS_ABOVE = 0.6  # two columns when one would be taller than this share of the screen height
FALLBACK_SCREEN = (1280, 800)


def _v(x):
    """A pya getter that is a method in one binding and a property in another: its value."""
    return x() if callable(x) else x


def _is_layout(obj) -> bool:
    """A Qt layout (pya's classes are not always ``isinstance`` of ``QLayout``: go by the class name)."""
    return "Layout" in type(obj).__name__


def two_columns_enabled() -> bool:
    """Settings ▸ "Long dialogs in two columns" (on by default)."""
    return config(CFG_DIALOG_COLUMNS, "2").strip() != "1"


def available_size(widget=None) -> tuple[int, int]:
    """Width and height (logical pixels) of the free screen area (without the task bar) under ``widget``, else under
    KLayout's main window."""
    try:
        main = pya.Application.instance().main_window()
    except Exception:  # noqa: BLE001
        main = None
    target = widget if widget is not None else main
    getters = (
        lambda w: _v(w.screen).availableGeometry,  # Qt >= 5.14
        lambda w: pya.QApplication.desktop().availableGeometry(w),
        lambda w: pya.QGuiApplication.primaryScreen().availableGeometry,
    )
    for get in getters:
        try:
            g = _v(get(target if target is not None else main))
            w, h = int(_v(g.width)), int(_v(g.height))
            if w > 0 and h > 0:
                return w, h
        except Exception:  # noqa: BLE001  (the next way of asking)
            continue
    return FALLBACK_SCREEN


def _hint(obj) -> tuple[int, int]:
    """``sizeHint`` of a widget or a layout as ``(width, height)``; (0, 0) when it cannot be read."""
    try:
        s = _v(obj.sizeHint)
        return int(_v(s.width)), int(_v(s.height))
    except Exception:  # noqa: BLE001
        return 0, 0


def _row_height(args) -> int:
    """Estimated height of one form row (its tallest part plus the row spacing)."""
    parts = [a for a in args if not isinstance(a, str)]
    return max([_hint(a)[1] for a in parts] or [0]) + 6


class Rows:
    """Form rows in sections, laid out by :meth:`build`. ``addRow`` takes what ``QFormLayout.addRow`` takes (a label
    and a widget or layout, or one widget or layout spanning the row); :meth:`section` starts a new section (with an
    optional bold title). Two columns split only between sections (or, with a single section, between rows)."""

    def __init__(self, parent=None):
        self.parent = parent
        self.sections: list[list[tuple]] = [[]]
        self.columns = 1  # after build: how many were used (tests)

    def addRow(self, *args):  # noqa: N802  (the QFormLayout name, so helpers that fill a form fill this too)
        self.sections[-1].append(args)

    def section(self, title: str | None = None):
        """Start a section; ``title`` adds a bold label as its first row. Returns the label (or None)."""
        if self.sections[-1]:
            self.sections.append([])
        if not title:
            return None
        label = pya.QLabel(title, self.parent)
        label.wordWrap = True
        try:
            font = label.font
            font = _v(font)
            font.setBold(True)
            label.setFont(font)
        except Exception:  # noqa: BLE001  (an unstyled title is still a title)
            pass
        self.addRow(label)
        return label

    @staticmethod
    def _form(rows) -> pya.QFormLayout:
        form = pya.QFormLayout()
        for args in rows:
            form.addRow(*args)
        return form

    def units(self) -> list[list[tuple]]:
        sections = [s for s in self.sections if s]
        return sections if len(sections) > 1 else [[r] for r in (sections[0] if sections else [])]

    def split(self, columns: int | None = None) -> list[list[tuple]]:
        """The rows of each column: one, or two balanced by height when two are allowed and needed."""
        units = self.units()
        heights = [sum(_row_height(r) for r in u) for u in units]
        want = columns if columns is not None else (2 if two_columns_enabled() else 1)
        if want == 2 and len(units) > 1 and sum(heights) > available_size(self.parent)[1] * TWO_COLUMNS_ABOVE:
            best, k = None, 1
            for i in range(1, len(units)):
                tall = max(sum(heights[:i]), sum(heights[i:]))
                if best is None or tall < best:
                    best, k = tall, i
            parts = [units[:k], units[k:]]
        else:
            parts = [units]
        return [[r for u in part for r in u] for part in parts]

    def build(self, columns: int | None = None) -> pya.QWidget:
        """The dialog body: the rows in one or two columns (each a form, top-aligned)."""
        cols = self.split(columns)
        self.columns = len(cols)
        body = pya.QWidget(self.parent)
        row = pya.QHBoxLayout(body)
        row.setContentsMargins(0, 0, 0, 0)
        for i, rows in enumerate(cols):
            if i:
                row.addSpacing(18)
            col = pya.QVBoxLayout()
            col.addLayout(self._form(rows))
            col.addStretch(1)
            row.addLayout(col, 1)
        return body


def side_by_side(parent, left, right, columns: int | None = None) -> pya.QWidget:
    """Two layouts (or widgets) next to each other when two columns are on, else one under the other."""
    two = (columns if columns is not None else (2 if two_columns_enabled() else 1)) == 2
    body = pya.QWidget(parent)
    box = pya.QHBoxLayout(body) if two else pya.QVBoxLayout(body)
    box.setContentsMargins(0, 0, 0, 0)
    for i, part in enumerate((left, right)):
        if i and two:
            box.addSpacing(18)
        if _is_layout(part):
            box.addLayout(part, 1)
        else:
            box.addWidget(part, 1)
    body.qcc_columns = 2 if two else 1  # tests
    return body


def fit(dialog, body, buttons=None, want: tuple[int, int] | None = None) -> pya.QScrollArea:
    """Lay ``dialog`` out as ``body`` (a widget or layout) in a scroll area and ``buttons`` below it, resizable, sized
    to the content (at least ``want``) and at most :data:`SCREEN_SHARE` of the free screen area. Returns the area."""
    if _is_layout(body):
        holder = pya.QWidget(dialog)
        holder.setLayout(body)
        body = holder
    outer = pya.QVBoxLayout(dialog)
    area = pya.QScrollArea(dialog)
    area.setWidgetResizable(True)
    try:
        area.setFrameShape(pya.QFrame.NoFrame)
    except Exception:  # noqa: BLE001
        pass
    area.setWidget(body)
    outer.addWidget(area, 1)
    if buttons is not None:
        outer.addWidget(buttons)
    try:
        dialog.setSizeGripEnabled(True)
    except Exception:  # noqa: BLE001
        pass
    bw, bh = _hint(body)
    btn_h = _hint(buttons)[1] if buttons is not None else 0
    ww, wh = want or (0, 0)
    sw, sh = available_size(dialog)
    width = min(max(bw + 40, ww), int(sw * SCREEN_SHARE[0]))  # + the vertical scroll bar and the margins
    height = min(max(bh + btn_h + 40, wh), int(sh * SCREEN_SHARE[1]))
    dialog.resize(max(width, 200), max(height, 120))
    dialog.qcc_scroll = area  # tests
    log(f"dialog {_v(dialog.windowTitle)!r}: {width} x {height} px (content {bw} x {bh}, screen {sw} x {sh})")
    return area


def fit_window(window, width: int, height: int) -> None:
    """Resize a non-modal window to ``width`` x ``height``, but at most :data:`SCREEN_SHARE` of the screen."""
    sw, sh = available_size(window)
    window.resize(min(width, int(sw * SCREEN_SHARE[0])), min(height, int(sh * SCREEN_SHARE[1])))
