"""Extension points for tool and solver adapters (Python entry points).

A plugin is a separately installable package (for example the ``qcc-sonnet`` adapter) that declares entry points:

``quantcore_circuits.analyses``
    an :class:`AnalysisPlugin` instance — a new ``sim_groups.*.analyses`` name, e.g. ``"sonnet_s"``. Its
    ``export(setup, job_dir, **settings)`` writes the solver input into the job directory; qcc adds ``job.json``.
``quantcore_circuits.cells``
    a module whose KQC Element classes are registered next to the built-in layouts (extra component libraries).

Example ``pyproject.toml`` of a plugin::

    [project.entry-points."quantcore_circuits.analyses"]
    sonnet_s = "qcc_sonnet:SONNET"
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from importlib.metadata import entry_points
from typing import Literal

ANALYSIS_GROUP = "quantcore_circuits.analyses"
CELL_GROUP = "quantcore_circuits.cells"


@dataclass(frozen=True)
class AnalysisPlugin:
    name: str
    kind: Literal["capacitance", "eigenmode", "driven"]
    solver: str
    export: Callable  # export(setup, job_dir, **settings) -> None
    defaults: dict = field(default_factory=dict)
    description: str = ""


@cache
def analysis_plugins() -> dict[str, AnalysisPlugin]:
    out = {}
    for ep in entry_points(group=ANALYSIS_GROUP):
        plugin = ep.load()
        if not isinstance(plugin, AnalysisPlugin):
            raise TypeError(f"entry point {ep.name!r} must load an AnalysisPlugin, got {type(plugin)}")
        out[plugin.name] = plugin
    return out


def register_cell_plugins() -> list[type]:
    """Import ``quantcore_circuits.cells`` entry points and register their PCells in the KQC libraries."""
    from kqcircuits.elements.element import Element  # pylint: disable=import-outside-toplevel

    from quantcore_circuits import layouts  # pylint: disable=import-outside-toplevel

    classes = []
    for ep in entry_points(group=CELL_GROUP):
        module = ep.load()
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                obj.__module__ == module.__name__
                and not name.startswith("_")
                and issubclass(obj, Element)
                and obj.build is not Element.build
            ):
                classes.append(obj)
    layouts.register_pcell_classes(classes)
    return classes
