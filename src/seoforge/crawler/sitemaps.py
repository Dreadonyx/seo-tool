"""Sitemap discovery and parsing (XML urlset, sitemap index, gzip, plain text)."""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from seoforge.http import PoliteClient, RobotsDisallowed

NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
MAX_URLS = 50_000
MAX_BYTES = 50 * 1024 * 1024


@dataclass(slots=True)
class SitemapEntry:
    loc: str
    lastmod: str | None = None


@dataclass(slots=True)
class Sitemap:
    url: str
    status: int
    entries: list[SitemapEntry] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    is_index: bool = False


@dataclass(slots=True)
class SitemapReport:
    sitemaps: list[Sitemap] = field(default_factory=list)

    @property
    def urls(self) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for sm in self.sitemaps:
            for entry in sm.entries:
                out.setdefault(entry.loc, entry.lastmod)
        return out

    @property
    def found(self) -> bool:
        return any(sm.status == 200 and not sm.errors for sm in self.sitemaps)


def parse_sitemap(url: str, status: int, body: bytes) -> Sitemap:
    sm = Sitemap(url=url, status=status)
    if status != 200:
        sm.errors.append(f"HTTP {status}")
        return sm
    if body[:2] == b"\x1f\x8b":
        try:
            body = gzip.decompress(body)
        except OSError as exc:
            sm.errors.append(f"Invalid gzip: {exc}")
            return sm
    if len(body) > MAX_BYTES:
        sm.errors.append("Sitemap exceeds 50 MB uncompressed limit")
    stripped = body.lstrip()
    if not stripped.startswith(b"<"):
        # Plain-text sitemap: one URL per line
        sm.entries = [
            SitemapEntry(line.strip())
            for line in body.decode("utf-8", "replace").splitlines()
            if line.strip().startswith("http")
        ]
        return sm
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        sm.errors.append(f"XML parse error: {exc}")
        return sm
    tag = root.tag.replace(NS, "")
    if NS not in root.tag:
        sm.errors.append("Missing sitemaps.org 0.9 namespace")
    if tag == "sitemapindex":
        sm.is_index = True
        for node in root.iter():
            if node.tag.endswith("loc") and node.text:
                sm.children.append(node.text.strip())
    elif tag == "urlset":
        for url_node in root:
            loc = url_node.find(f"{NS}loc")
            if loc is None:
                loc = url_node.find("loc")
            if loc is None or not loc.text:
                sm.errors.append("<url> without <loc>")
                continue
            lastmod = url_node.find(f"{NS}lastmod")
            if lastmod is None:
                lastmod = url_node.find("lastmod")
            sm.entries.append(
                SitemapEntry(
                    loc.text.strip(),
                    lastmod.text.strip() if lastmod is not None and lastmod.text else None,
                )
            )
    else:
        sm.errors.append(f"Unexpected root element <{tag}>")
    if len(sm.entries) > MAX_URLS:
        sm.errors.append(f"{len(sm.entries)} URLs exceeds the 50,000 per-sitemap limit")
    return sm


async def discover_sitemaps(
    client: PoliteClient, site: str, max_sitemaps: int = 50
) -> SitemapReport:
    robots = await client.robots(site)
    queue = list(dict.fromkeys(robots.sitemaps or [f"{site.rstrip('/')}/sitemap.xml"]))
    report = SitemapReport()
    seen: set[str] = set()
    while queue and len(seen) < max_sitemaps:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            result = await client.fetch(url)
        except RobotsDisallowed:
            report.sitemaps.append(Sitemap(url, 0, errors=["Blocked by robots.txt"]))
            continue
        if result.error:
            report.sitemaps.append(Sitemap(url, 0, errors=[result.error]))
            continue
        sm = parse_sitemap(url, result.status, result.body)
        report.sitemaps.append(sm)
        queue.extend(child for child in sm.children if child not in seen)
    return report
