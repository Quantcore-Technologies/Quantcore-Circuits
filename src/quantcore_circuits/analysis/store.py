"""Results store: SQLite table keyed by (design hash, sim group, analysis); each row holds the result JSON."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_STORE = Path(os.environ.get("QCC_RESULTS_STORE", "results.sqlite"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    design_hash TEXT NOT NULL,
    design TEXT,
    grp TEXT NOT NULL,
    analysis TEXT NOT NULL,
    kind TEXT NOT NULL,            -- 'sim' (parsed solver output) or 'params' (extracted Hamiltonian params)
    created TEXT NOT NULL,
    job_dir TEXT,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_key ON results (design_hash, grp, analysis, kind);
"""


class ResultsStore:
    def __init__(self, path: str | Path = DEFAULT_STORE):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(_SCHEMA)

    def _connect(self):
        return sqlite3.connect(self.path)

    def put(self, design_hash, group, analysis, data: dict, kind="params", design=None, job_dir=None) -> int:
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO results (design_hash, design, grp, analysis, kind, created, job_dir, data) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    design_hash,
                    design,
                    group,
                    analysis,
                    kind,
                    datetime.now(UTC).isoformat(timespec="seconds"),
                    None if job_dir is None else str(job_dir),
                    json.dumps(data, default=float),
                ),
            )
            return int(cur.lastrowid)

    def latest(self, design_hash, group=None, analysis=None, kind="params") -> dict | None:
        rows = self.query(design_hash=design_hash, group=group, analysis=analysis, kind=kind, limit=1)
        return rows[0] if rows else None

    def query(self, design_hash=None, group=None, analysis=None, kind=None, design=None, limit=100) -> list[dict]:
        sql, args = "SELECT id, design_hash, design, grp, analysis, kind, created, job_dir, data FROM results", []
        cond = []
        for col, val in (
            ("design_hash", design_hash),
            ("grp", group),
            ("analysis", analysis),
            ("kind", kind),
            ("design", design),
        ):
            if val is not None:
                cond.append(f"{col} = ?")
                args.append(val)
        if cond:
            sql += " WHERE " + " AND ".join(cond)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._connect() as con:
            rows = con.execute(sql, args).fetchall()
        keys = ("id", "design_hash", "design", "group", "analysis", "kind", "created", "job_dir", "data")
        return [{**dict(zip(keys, r)), "data": json.loads(r[-1])} for r in rows]
