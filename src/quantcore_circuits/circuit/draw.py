"""Matplotlib schematic of a LOM circuit (``circuit.json``) with the element values that went into the simulation.

QuCat's own ``Network.show()`` only works for networks made in its GUI, so this draws the lumped circuit directly:
a ground rail at the bottom, one bus per conductor (node), elements to ground hanging down from it, and elements
between two conductors drawn between (or arching over) the buses. Used by ``qcc circuit simulate --png`` and shown in
the KLayout plugin's LOM tab. Needs matplotlib only (imported when drawing).
"""

from __future__ import annotations

from pathlib import Path

_COLORS = {
    "C": "#1f77b4",
    "L": "#2ca02c",
    "JJ": "#d62728",
    "SQUID": "#d62728",
    "TLres": "#9467bd",
    "R": "#7f7f7f",
    "HANGER": "#ff7f0e",
}
_NICE = {"JJ": "JJ", "SQUID": "SQUID", "TLres": "λ/4", "HANGER": "hanger", "R": "R", "L": "L", "C": "C"}


def value_text(v, unit: str = "", fmt: str = ".3g") -> str:
    """A netlist value with its unit. A pair (e.g. a resonator's C and L, ``unit`` "fF, nH") reads "302 fF ‖ 1.49 nH":
    the comma-separated units go one per value."""
    if isinstance(v, (list, tuple)):
        units = [u.strip() for u in (unit or "").split(",")]
        if len(units) != len(v):
            units = [unit] * len(v) if len(units) == 1 else [""] * len(v)
        return " ‖ ".join(f"{x:{fmt}} {u}".strip() if isinstance(x, (int, float)) else f"{x} {u}".strip()
                          for x, u in zip(v, units))
    if isinstance(v, (int, float)):
        return f"{v:{fmt}} {unit}".strip()
    return str(v)


def _label(name: str, row: dict | None, btype: str) -> str:
    if not row:
        return name
    v, unit = row.get("value"), row.get("unit", "")
    if isinstance(v, (list, tuple)):
        txt = value_text(v, unit)
    elif isinstance(v, (int, float)):
        txt = value_text(v, unit)
    else:
        txt = btype
    return f"{name}\n{txt}"


def _symbol(ax, kind: str, x: float, y: float, vertical: bool, color: str) -> None:
    """A small schematic symbol centred at (x, y)."""
    w, h = (0.16, 0.30) if vertical else (0.30, 0.16)
    if kind == "C":  # two plates
        if vertical:
            for dy in (-0.05, 0.05):
                ax.plot([x - w, x + w], [y + dy, y + dy], color=color, lw=2.2, solid_capstyle="butt")
        else:
            for dx in (-0.05, 0.05):
                ax.plot([x + dx, x + dx], [y - h, y + h], color=color, lw=2.2, solid_capstyle="butt")
        return
    from matplotlib.patches import Rectangle  # pylint: disable=import-outside-toplevel

    ax.add_patch(Rectangle((x - w, y - h), 2 * w, 2 * h, fc="white", ec=color, lw=1.8, zorder=3))
    if kind in ("JJ", "SQUID"):  # a cross in the box
        ax.plot([x - w, x + w], [y - h, y + h], color=color, lw=1.8, zorder=4)
        ax.plot([x - w, x + w], [y + h, y - h], color=color, lw=1.8, zorder=4)
    elif kind == "R":  # zigzag
        xs = (
            [x - w + i * 2 * w / 6 for i in range(7)]
            if not vertical
            else [x + (0.07 if i % 2 else -0.07) for i in range(7)]
        )
        ys = (
            [y + (0.06 if i % 2 else -0.06) for i in range(7)]
            if not vertical
            else [y - h + i * 2 * h / 6 for i in range(7)]
        )
        ax.plot(xs, ys, color=color, lw=1.5, zorder=4)


def draw_circuit(model, netlist: list[dict] | None, path: str | Path, title: str = "") -> Path:
    """Draw ``model`` (a :class:`CircuitModel`) to the PNG ``path``; ``netlist`` rows (``LomResult.netlist``) give
    the values printed next to each element."""
    import matplotlib  # pylint: disable=import-outside-toplevel

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # pylint: disable=import-outside-toplevel

    rows = {r["element"]: r for r in (netlist or [])}
    ground = {n for n, s in model.nodes.items() if s.ground}
    nodes = [n for n in model.nodes if n not in ground]
    to_ground, between = {n: [] for n in nodes}, []
    for name, b in model.branches.items():
        a, c = b.nodes
        if a in ground and c in ground:
            continue
        if a in ground or c in ground:
            to_ground[c if a in ground else a].append((name, b))
        else:
            between.append((name, b, a, c))
    # order the conductors so that coupled ones sit next to each other (walk the node-to-node branches)
    adj = {n: [] for n in nodes}
    for _, _, a, c in between:
        adj[a].append(c)
        adj[c].append(a)
    order, seen = [], set()
    for start in nodes:
        stack = [start]
        while stack:
            n = stack.pop(0)
            if n in seen:
                continue
            seen.add(n)
            order.append(n)
            stack = [m for m in adj[n] if m not in seen] + stack
    # columns: width from the number of elements hanging off a node
    xs, x = {}, 0.0
    for n in order:
        width = max(1, len(to_ground[n])) * 2.1  # room for a 9 pt label beside each element
        xs[n] = (x, x + width)
        x += width + 2.0
    total = max(x - 2.0, 3.0)
    ytop, ybase = 3.0, 0.0
    fig_w = min(max(7.0, total * 0.9), 18.0)
    fig, ax = plt.subplots(figsize=(fig_w, 4.2), dpi=110)
    ax.axhline(ybase, xmin=0, xmax=1, color="black", lw=2.5)
    ax.text(-0.2, ybase - 0.25, "ground", ha="left", va="top", fontsize=9)
    for n in order:
        x0, x1 = xs[n]
        ax.plot([x0, x1], [ytop, ytop], color="black", lw=3, solid_capstyle="round")
        ax.text((x0 + x1) / 2, ytop + 0.12, n, ha="center", va="bottom", fontsize=12, weight="bold")
        for i, (name, b) in enumerate(to_ground[n]):
            bx = x0 + 0.75 + i * 2.1
            color = _COLORS.get(b.type, "black")
            mid = (ytop + ybase) / 2
            ax.plot([bx, bx], [ytop, mid + 0.35], color="black", lw=1.2)
            ax.plot([bx, bx], [mid - 0.35, ybase], color="black", lw=1.2)
            _symbol(ax, b.type, bx, mid, True, color)
            ax.text(
                bx + 0.28,
                mid,
                _label(name, rows.get(name), _NICE.get(b.type, b.type)),
                fontsize=9,
                va="center",
                color=color,
            )
    levels = {}
    for name, b, a, c in between:
        ax0, cx0 = xs[a][0], xs[c][0]
        left, right = (a, c) if ax0 < cx0 else (c, a)
        gap = abs(order.index(a) - order.index(c))
        color = _COLORS.get(b.type, "black")
        if gap == 1:
            xa, xb = xs[left][1], xs[right][0]
            xm = (xa + xb) / 2
            levels[(left, right)] = levels.setdefault((left, right), 0) + 1
            ax.plot([xa, xm - 0.35], [ytop, ytop], color="black", lw=1.2)
            ax.plot([xm + 0.35, xb], [ytop, ytop], color="black", lw=1.2)
            _symbol(ax, b.type, xm, ytop, False, color)
            ax.text(
                xm,
                ytop - 0.4 - 0.55 * (levels[(left, right)] - 1),
                _label(name, rows.get(name), _NICE.get(b.type, b.type)),
                fontsize=9,
                ha="center",
                va="top",
                color=color,
            )
        else:  # an arch over the buses in between
            n_same = levels.setdefault(("arch", gap), 0)
            h = ytop + 0.9 + 0.9 * (gap - 1) + 0.5 * n_same
            levels[("arch", gap)] = n_same + 1
            xa, xb = xs[left][1] - 0.3, xs[right][0] + 0.3
            ax.plot([xa, xa, xb, xb], [ytop, h, h, ytop], color="black", lw=1.2)
            _symbol(ax, b.type, (xa + xb) / 2, h, False, color)
            ax.text(
                (xa + xb) / 2,
                h + 0.25,
                _label(name, rows.get(name), _NICE.get(b.type, b.type)),
                fontsize=9,
                ha="center",
                va="bottom",
                color=color,
            )
    top = ytop + 0.8 + (max((g for (k, g) in levels if k == "arch"), default=0) * 0.9 if levels else 0)
    ax.set_xlim(-0.6, total + 0.6)
    ax.set_ylim(ybase - 0.9, top + 0.2)
    ax.set_aspect("auto")
    ax.axis("off")
    if title:
        ax.set_title(title, fontsize=11)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight", pad_inches=0.15)  # no empty margins: the KLayout panel shows it small
    plt.close(fig)
    return out
