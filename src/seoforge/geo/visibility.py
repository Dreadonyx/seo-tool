"""AI-visibility tracker: a prompt set and a log of whether AI assistants mention/cite you.

Data entry is manual (you ask the assistant, record what happened) or scripted through a
command YOU provide that prints an answer for a prompt - e.g. a wrapper around an API whose
free tier you are allowed to use. SEOForge never automates consumer chat UIs.
"""

from __future__ import annotations

import csv
import re
import shlex
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from seoforge.config import EntityConfig
from seoforge.storage import Store

ENGINES = ("chatgpt", "claude", "gemini", "perplexity", "copilot", "brave-leo", "other")


def default_prompts(entity: EntityConfig, topics: list[str] | None = None) -> list[tuple[str, str]]:
    """(prompt, kind) pairs built from your entity config and site topics."""
    out: list[tuple[str, str]] = []
    if entity.name:
        out += [
            (f"What is {entity.name}?", "brand"),
            (f"Is {entity.name} legit?", "brand"),
            (f"What are the best alternatives to {entity.name}?", "brand"),
            (f"Who founded {entity.name}?", "brand"),
        ]
    if entity.category:
        out.append((f"What is the best {entity.category}?", "category"))
        out.append((f"Recommend a {entity.category}", "category"))
        if entity.city:
            out.append((f"Best {entity.category} in {entity.city}", "local"))
    for topic in (topics or [])[:5]:
        out.append((f"What is {topic}?", "topic"))
    return out


def add_prompts(store: Store, prompts: list[tuple[str, str]]) -> int:
    added = 0
    with store.tx() as c:
        for text, kind in prompts:
            cur = c.execute(
                "INSERT OR IGNORE INTO vis_prompts (text, kind, created_at) VALUES (?, ?, ?)",
                (text, kind, time.time()),
            )
            added += cur.rowcount
    return added


def list_prompts(store: Store) -> list[dict[str, Any]]:
    rows = store.conn.execute("SELECT id, text, kind FROM vis_prompts ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@dataclass(slots=True)
class Observation:
    prompt_id: int
    engine: str
    mentioned: bool
    cited: bool = False
    position: int | None = None
    cited_url: str | None = None
    source: str = "manual"
    notes: str | None = None
    observed_at: float | None = None


def log(store: Store, obs: Observation) -> None:
    if obs.engine not in ENGINES:
        raise ValueError(f"engine must be one of {', '.join(ENGINES)}")
    with store.tx() as c:
        if c.execute("SELECT 1 FROM vis_prompts WHERE id = ?", (obs.prompt_id,)).fetchone() is None:
            raise ValueError(f"no prompt with id {obs.prompt_id}")
        c.execute(
            "INSERT INTO vis_observations (prompt_id, engine, observed_at, mentioned, cited, position, "
            "cited_url, source, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                obs.prompt_id,
                obs.engine,
                obs.observed_at or time.time(),
                int(obs.mentioned),
                int(obs.cited),
                obs.position,
                obs.cited_url,
                obs.source,
                obs.notes,
            ),
        )


def import_csv(store: Store, path: Path) -> int:
    """CSV columns: prompt,engine,date(YYYY-MM-DD),mentioned(yes/no),cited_url,position,notes"""
    n = 0
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            prompt = (row.get("prompt") or "").strip()
            if not prompt:
                continue
            add_prompts(store, [(prompt, "imported")])
            pid = store.conn.execute(
                "SELECT id FROM vis_prompts WHERE text = ?", (prompt,)
            ).fetchone()["id"]
            when = row.get("date")
            ts = (
                datetime.strptime(when, "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
                if when
                else None
            )
            cited_url = (row.get("cited_url") or "").strip() or None
            pos = (row.get("position") or "").strip()
            log(
                store,
                Observation(
                    prompt_id=int(pid),
                    engine=(row.get("engine") or "other").strip().lower(),
                    mentioned=(row.get("mentioned") or "").strip().lower()
                    in ("yes", "y", "true", "1"),
                    cited=bool(cited_url),
                    position=int(pos) if pos.isdigit() else None,
                    cited_url=cited_url,
                    source="csv",
                    notes=row.get("notes") or None,
                    observed_at=ts,
                ),
            )
            n += 1
    return n


def detect(
    answer: str, brand_terms: list[str], domain: str | None
) -> tuple[bool, bool, str | None]:
    """(mentioned, cited, cited_url) from an answer's text."""
    text = answer.lower()
    mentioned = any(re.search(rf"\b{re.escape(t.lower())}\b", text) for t in brand_terms if t)
    cited_url = None
    if domain:
        bare = domain.removeprefix("www.")
        m = re.search(rf"https?://(?:www\.)?{re.escape(bare)}[^\s)\]>\"']*", answer, re.I)
        if m:
            cited_url = m.group(0)
        elif bare in text:
            cited_url = bare
    return mentioned or cited_url is not None, cited_url is not None, cited_url


def run_command(
    store: Store,
    engine: str,
    command: str,
    entity: EntityConfig,
    site: str | None,
    timeout: float = 120,
) -> list[Observation]:
    """Run a user-supplied command once per prompt. `{prompt}` in the command is replaced by
    the prompt text (passed as a single argument, no shell)."""
    if "{prompt}" not in command:
        raise ValueError("command must contain {prompt}")
    domain = urlsplit(site).netloc if site else None
    terms = [t for t in [entity.name, entity.legal_name] if t]
    results = []
    for prompt in list_prompts(store):
        args = [a.replace("{prompt}", prompt["text"]) for a in shlex.split(command)]
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        if proc.returncode != 0:
            obs = Observation(
                prompt["id"],
                engine,
                False,
                source="script",
                notes=f"command failed: {proc.stderr.strip()[:200]}",
            )
        else:
            mentioned, cited, url = detect(proc.stdout, terms, domain)
            obs = Observation(
                prompt["id"], engine, mentioned, cited, cited_url=url, source="script"
            )
        log(store, obs)
        results.append(obs)
    return results


def summary(store: Store) -> dict[str, Any]:
    rows = store.conn.execute(
        "SELECT o.*, p.text FROM vis_observations o JOIN vis_prompts p ON p.id = o.prompt_id "
        "ORDER BY o.observed_at"
    ).fetchall()
    by_engine_month: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(lambda: [0, 0, 0])
    )
    latest: dict[tuple[int, str], dict[str, Any]] = {}
    for r in rows:
        month = datetime.fromtimestamp(r["observed_at"], UTC).strftime("%Y-%m")
        bucket = by_engine_month[r["engine"]][month]
        bucket[0] += 1
        bucket[1] += r["mentioned"]
        bucket[2] += r["cited"]
        latest[(r["prompt_id"], r["engine"])] = {
            "prompt": r["text"],
            "engine": r["engine"],
            "mentioned": bool(r["mentioned"]),
            "cited": bool(r["cited"]),
            "cited_url": r["cited_url"],
            "position": r["position"],
            "date": datetime.fromtimestamp(r["observed_at"], UTC).strftime("%Y-%m-%d"),
            "source": r["source"],
        }
    trend = {
        engine: [
            {
                "month": m,
                "checks": v[0],
                "mention_rate": round(v[1] / v[0], 2),
                "citation_rate": round(v[2] / v[0], 2),
            }
            for m, v in sorted(months.items())
        ]
        for engine, months in by_engine_month.items()
    }
    return {"observations": len(rows), "trend": trend, "latest": list(latest.values())}
