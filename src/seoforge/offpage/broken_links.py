"""Broken-link-building finder: dead outbound links on resource pages YOU choose.

Every fetch goes through the polite, robots.txt-respecting client. The Wayback Machine
availability API (free) shows what the dead page used to contain, so you only suggest a
replacement that is genuinely equivalent.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from seoforge.analysis.competitors import fetch_page
from seoforge.http import PoliteClient, RobotsDisallowed

WAYBACK = "https://archive.org/wayback/available"
DEAD = {404, 410}


@dataclass(slots=True)
class DeadLink:
    resource_page: str
    url: str
    anchor: str
    status: int
    archived: str | None = None


@dataclass(slots=True)
class BrokenLinkReport:
    pages: dict[str, str] = field(default_factory=dict)  # resource page -> status
    dead: list[DeadLink] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"pages": self.pages, "dead": [asdict(d) for d in self.dead]}


async def link_status(client: PoliteClient, url: str) -> int | None:
    try:
        result = await client.fetch(url, method="HEAD")
        if result.status in (403, 405, 501) or result.error:
            result = await client.fetch(url)
    except RobotsDisallowed:
        return None  # not ours to probe
    return 0 if result.error else result.status


async def wayback(api: httpx.AsyncClient, url: str) -> str | None:
    try:
        resp = await api.get(WAYBACK, params={"url": url}, timeout=20)
        snap = resp.json().get("archived_snapshots", {}).get("closest", {})
        return str(snap["url"]) if snap.get("available") else None
    except (httpx.HTTPError, ValueError, KeyError):
        return None


async def find_broken_links(
    client: PoliteClient,
    resource_pages: list[str],
    *,
    api: httpx.AsyncClient | None = None,
    max_links_per_page: int = 150,
) -> BrokenLinkReport:
    report = BrokenLinkReport()
    checked: dict[str, int | None] = {}
    for page_url in resource_pages:
        page, status = await fetch_page(client, page_url)
        report.pages[page_url] = status
        if page is None:
            continue
        links = [link for link in page.external_links][:max_links_per_page]
        todo = [link.url for link in links if link.url not in checked]
        results = await asyncio.gather(*(link_status(client, u) for u in todo))
        checked.update(zip(todo, results, strict=True))
        for link in links:
            code = checked.get(link.url)
            if code in DEAD or code == 0:
                report.dead.append(DeadLink(page_url, link.url, link.text, code or 0))
    if api is not None:
        for d in report.dead:
            d.archived = await wayback(api, d.url)
    return report
