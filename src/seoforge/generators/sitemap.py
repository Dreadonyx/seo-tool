"""XML sitemap generator from crawled, indexable, canonical URLs."""

from __future__ import annotations

import re
from email.utils import parsedate_to_datetime
from xml.sax.saxutils import escape

from seoforge.analysis import pagetype as pt
from seoforge.crawler.crawler import CrawlResult
from seoforge.models import PageData

MAX_URLS = 50_000
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def lastmod(page: PageData, sitemap_lastmod: str | None) -> str | None:
    """Best real modification date: schema dateModified > existing sitemap > Last-Modified."""
    modified = pt.modified_date(page)
    if modified and ISO_DATE.match(modified):
        return modified[:10]
    if sitemap_lastmod and ISO_DATE.match(sitemap_lastmod):
        return sitemap_lastmod[:10]
    header = page.headers.get("last-modified")
    if header:
        try:
            return parsedate_to_datetime(header).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            return None
    return None


def sitemap_entries(crawl: CrawlResult) -> list[tuple[str, str | None]]:
    existing = crawl.sitemaps.urls
    pages = [p for p in crawl.html_pages if p.is_indexable]
    pages.sort(key=lambda p: (p.url != crawl.start_url, p.url.count("/"), p.url))
    seen: set[str] = set()
    entries = []
    for p in pages:
        if p.url in seen:
            continue
        seen.add(p.url)
        entries.append((p.url, lastmod(p, existing.get(p.url))))
    return entries


def render_urlset(entries: list[tuple[str, str | None]]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc, mod in entries:
        lines.append(
            f"  <url><loc>{escape(loc)}</loc>"
            + (f"<lastmod>{mod}</lastmod>" if mod else "")
            + "</url>"
        )
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def generate_sitemaps(crawl: CrawlResult) -> dict[str, str]:
    """Return {filename: xml}. Splits into a sitemap index above 50,000 URLs."""
    entries = sitemap_entries(crawl)
    if len(entries) <= MAX_URLS:
        return {"sitemap.xml": render_urlset(entries)}
    files: dict[str, str] = {}
    names = []
    for i in range(0, len(entries), MAX_URLS):
        name = f"sitemap-{i // MAX_URLS + 1}.xml"
        files[name] = render_urlset(entries[i : i + MAX_URLS])
        names.append(name)
    index = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    index += [f"  <sitemap><loc>{escape(crawl.site)}/{n}</loc></sitemap>" for n in names]
    index.append("</sitemapindex>")
    files["sitemap.xml"] = "\n".join(index) + "\n"
    return files
