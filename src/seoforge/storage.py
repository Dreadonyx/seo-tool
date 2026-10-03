"""SQLite persistence: HTTP cache, resumable crawl frontier, API caches/quotas, AI visibility log."""

from __future__ import annotations

import json
import sqlite3
import time
import zlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS http_cache (
    url TEXT PRIMARY KEY,
    status INTEGER NOT NULL,
    headers TEXT NOT NULL,
    body BLOB,
    elapsed_ms REAL NOT NULL,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS crawl_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL
);
CREATE TABLE IF NOT EXISTS frontier (
    run_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    depth INTEGER NOT NULL,
    parent TEXT,
    state TEXT NOT NULL DEFAULT 'queued',
    PRIMARY KEY (run_id, url)
);
CREATE TABLE IF NOT EXISTS kv_cache (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    stored_at REAL NOT NULL,
    PRIMARY KEY (namespace, key)
);
CREATE TABLE IF NOT EXISTS api_quota (
    api TEXT NOT NULL,
    day TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (api, day)
);
CREATE TABLE IF NOT EXISTS vis_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'custom',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS vis_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id INTEGER NOT NULL REFERENCES vis_prompts(id),
    engine TEXT NOT NULL,
    observed_at REAL NOT NULL,
    mentioned INTEGER NOT NULL,
    cited INTEGER NOT NULL DEFAULT 0,
    position INTEGER,
    cited_url TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    notes TEXT
);
"""


@dataclass(slots=True)
class CachedResponse:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes
    elapsed_ms: float
    fetched_at: float


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ---- HTTP cache -------------------------------------------------------------------------
    def get_response(self, url: str, max_age_s: float) -> CachedResponse | None:
        row = self.conn.execute("SELECT * FROM http_cache WHERE url = ?", (url,)).fetchone()
        if row is None or time.time() - row["fetched_at"] > max_age_s:
            return None
        body = zlib.decompress(row["body"]) if row["body"] else b""
        return CachedResponse(
            url=row["url"],
            status=row["status"],
            headers=json.loads(row["headers"]),
            body=body,
            elapsed_ms=row["elapsed_ms"],
            fetched_at=row["fetched_at"],
        )

    def put_response(self, resp: CachedResponse) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO http_cache VALUES (?, ?, ?, ?, ?, ?)",
                (
                    resp.url,
                    resp.status,
                    json.dumps(resp.headers),
                    zlib.compress(resp.body),
                    resp.elapsed_ms,
                    resp.fetched_at,
                ),
            )

    # ---- Resumable frontier -----------------------------------------------------------------
    def open_run(self, site: str, resume: bool) -> tuple[int, bool]:
        """Return (run_id, resumed). Resumes the latest unfinished run for this site."""
        if resume:
            row = self.conn.execute(
                "SELECT id FROM crawl_runs WHERE site = ? AND finished_at IS NULL "
                "ORDER BY id DESC LIMIT 1",
                (site,),
            ).fetchone()
            if row is not None:
                return int(row["id"]), True
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO crawl_runs (site, started_at) VALUES (?, ?)", (site, time.time())
            )
        return int(cur.lastrowid or 0), False

    def finish_run(self, run_id: int) -> None:
        with self.tx() as c:
            c.execute("UPDATE crawl_runs SET finished_at = ? WHERE id = ?", (time.time(), run_id))

    def enqueue(self, run_id: int, url: str, depth: int, parent: str | None) -> bool:
        with self.tx() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO frontier (run_id, url, depth, parent) VALUES (?, ?, ?, ?)",
                (run_id, url, depth, parent),
            )
        return cur.rowcount > 0

    def mark_done(self, run_id: int, url: str) -> None:
        with self.tx() as c:
            c.execute(
                "UPDATE frontier SET state = 'done' WHERE run_id = ? AND url = ?", (run_id, url)
            )

    def frontier(self, run_id: int, state: str) -> list[tuple[str, int]]:
        rows = self.conn.execute(
            "SELECT url, depth FROM frontier WHERE run_id = ? AND state = ? ORDER BY depth, rowid",
            (run_id, state),
        ).fetchall()
        return [(r["url"], int(r["depth"])) for r in rows]

    # ---- Generic cache ----------------------------------------------------------------------
    def kv_get(self, namespace: str, key: str, max_age_s: float | None = None) -> Any | None:
        row = self.conn.execute(
            "SELECT value, stored_at FROM kv_cache WHERE namespace = ? AND key = ?",
            (namespace, key),
        ).fetchone()
        if row is None or (max_age_s is not None and time.time() - row["stored_at"] > max_age_s):
            return None
        return json.loads(row["value"])

    def kv_set(self, namespace: str, key: str, value: Any) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO kv_cache VALUES (?, ?, ?, ?)",
                (namespace, key, json.dumps(value), time.time()),
            )

    # ---- API quotas -------------------------------------------------------------------------
    @staticmethod
    def _today() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def quota_used(self, api: str) -> int:
        row = self.conn.execute(
            "SELECT used FROM api_quota WHERE api = ? AND day = ?", (api, self._today())
        ).fetchone()
        return int(row["used"]) if row else 0

    def quota_add(self, api: str, n: int = 1) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO api_quota (api, day, used) VALUES (?, ?, ?) "
                "ON CONFLICT(api, day) DO UPDATE SET used = used + excluded.used",
                (api, self._today(), n),
            )
