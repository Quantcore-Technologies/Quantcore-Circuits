"""``circuit.json`` (schema version qcd/0.1 or later): the lumped model bound to a layout.

Nodes are conductors: ``ground`` or an island that matches FEM nets (``layout.island`` = the C-matrix label, e.g.
``"Q1.island"``, plus ``aliases`` when several layout nets are one conductor). Branches connect two nodes; their
``value`` holds an explicit number, a component ``estimate`` and/or where it is filled from (``"fem": "cmatrix"``,
``"source": "design"``). ``HANGER`` is a coupled-line section between a λ/4 resonator and a feedline (κ). A branch
may carry a ``knob`` linking it to a design.json parameter the optimiser may change. ``controls`` lists control
lines (flux bias). Validation: a ground exists, branches reference known nodes, no node floats
(every node is connected to ground through branches), and each island maps to exactly one node.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CIRCUIT_SCHEMA = "qcc-circuit/0.1"
BranchType = Literal["C", "L", "JJ", "SQUID", "TLres", "R", "HANGER"]


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class NodeSpec(_M):
    ground: bool = False
    layout: dict[str, Any] = Field(default_factory=dict)  # {"island": "Q1.island", "aliases": ["PAD_W.pad"]}

    @property
    def island(self) -> str | None:
        return self.layout.get("island")

    @property
    def nets(self) -> list[str]:
        """All FEM net labels of this conductor (main island + aliases)."""
        return ([self.island] if self.island else []) + list(self.layout.get("aliases", []))


class BranchSpec(_M):
    type: BranchType
    nodes: tuple[str, str]
    value: dict[str, Any] = Field(default_factory=dict)
    knob: dict[str, Any] | None = None  # {"param": "R1.length", "map": "..."}


class TargetSpec(_M):
    value: float | None = None
    tol: float | None = None
    min: float | None = None
    max: float | None = None


class CircuitModel(_M):
    schema_: str = Field(CIRCUIT_SCHEMA, alias="schema")
    name: str = "circuit"
    design: str | None = None
    group: str | None = None
    nodes: dict[str, NodeSpec]
    branches: dict[str, BranchSpec]
    knobs: dict[str, tuple[float, float]] = Field(default_factory=dict)
    targets: dict[str, TargetSpec] = Field(default_factory=dict)
    estimators: list[str] = Field(default_factory=lambda: ["metal_lom", "qucat", "sqcircuit", "scqubits"])
    truncation: dict[str, int] = Field(default_factory=lambda: {"qubit_levels": 8, "resonator_levels": 6})
    controls: dict[str, dict[str, Any]] = Field(default_factory=dict)  # control lines, e.g. flux bias of a SQUID

    @model_validator(mode="after")
    def _topology(self):
        grounds = [n for n, s in self.nodes.items() if s.ground]
        if not grounds:
            raise ValueError("circuit has no ground node")
        for bname, b in self.branches.items():
            for n in b.nodes:
                if n not in self.nodes:
                    raise ValueError(f"branch {bname}: unknown node {n!r}")
            if b.nodes[0] == b.nodes[1]:
                raise ValueError(f"branch {bname}: both ends on {b.nodes[0]!r}")
        reached = set(grounds)
        changed = True
        while changed:
            changed = False
            for b in self.branches.values():
                a, c = b.nodes
                if (a in reached) != (c in reached):
                    reached |= {a, c}
                    changed = True
        floating = sorted(set(self.nodes) - reached)
        if floating:
            raise ValueError(f"floating node(s) not connected to ground: {floating}")
        seen: dict[str, str] = {}
        for n, s in self.nodes.items():
            for net in s.nets:
                if net in seen:
                    raise ValueError(f"island {net!r} mapped to two nodes: {seen[net]}, {n}")
                seen[net] = n
        return self

    @property
    def ground(self) -> str:
        return next(n for n, s in self.nodes.items() if s.ground)

    def islands(self) -> dict[str, str]:
        """FEM net label → node (aliases included)."""
        return {net: n for n, s in self.nodes.items() for net in s.nets}

    def unmapped_nets(self, labels: list[str]) -> list[str]:
        """C-matrix nets with no node (the circuit ignores them; they are usually stubs or cut-off routes)."""
        known = self.islands()
        return [lab for lab in labels if lab not in known]

    def to_networkx(self):
        import networkx as nx  # pylint: disable=import-outside-toplevel

        g = nx.MultiGraph(name=self.name)
        for n, s in self.nodes.items():
            g.add_node(n, ground=s.ground, island=s.island)
        for bname, b in self.branches.items():
            g.add_edge(*b.nodes, key=bname, type=b.type, value=b.value)
        return g

    def to_json_dict(self) -> dict:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


def load_circuit(source) -> CircuitModel:
    if isinstance(source, CircuitModel):
        return source
    if isinstance(source, dict):
        return CircuitModel.model_validate(source)
    return CircuitModel.model_validate(json.loads(Path(source).read_text(encoding="utf-8")))


def save_circuit(model: CircuitModel, path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model.to_json_dict(), indent=2) + "\n", encoding="utf-8")
    return path
