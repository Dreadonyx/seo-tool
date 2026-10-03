"""Unlinked brand mention finder using free, public APIs:

- Hacker News search (Algolia API, no key)
- Wikipedia search API (no key)

Candidate pages are then fetched politely (robots.txt respected) to see whether they already
link to your domain. Search-engine result pages are never scraped; instead SEOForge prints
manual search links you can open yourself.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import quote_plus, urlsplit

import httpx

from seoforge.analysis.competitors import fetch_page
from seoforge.http import PoliteClient
from seoforge.urls import bare_host

HN = "https://hn.algolia.com/api/v1/search"
WIKIPEDIA = "https://en.wikipedia.org/w/api.php"


@dataclass(slots=True)
class Mention:
    source: str
    title: str
    url: str
    linked: bool | None = None  # None = could not check (robots/HTTP error)
    note: str = ""


@dataclass(slots=True)
class MentionReport:
    brand: str
    domain: str
    mentions: list[Mention] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    manual_searches: list[str] = field(default_factory=list)

    @property
    def unlinked(self) -> list[Mention]:
        return [m for m in self.mentions if m.linked is False]

    def to_dict(self) -> dict[str, Any]:
        return {
            "brand": self.brand,
            "domain": self.domain,
            "mentions": [asdict(m) for m in self.mentions],
            "errors": self.errors,
            "manual_searches": self.manual_searches,
        }


async def hacker_news(api: httpx.AsyncClient, brand: str, limit: int = 20) -> list[Mention]:
    resp = await api.get(HN, params={"query": f'"{brand}"', "hitsPerPage": limit}, timeout=20)
    resp.raise_for_status()
    out = []
    for hit in resp.json().get("hits", []):
        item = f"https://news.ycombinator.com/item?id={hit.get('story_id') or hit.get('objectID')}"
        url = hit.get("url") or item
        title = hit.get("title") or hit.get("story_title") or "(comment)"
        out.append(Mention("hacker-news", title, url, note=f"discussion: {item}"))
    return out


async def wikipedia(api: httpx.AsyncClient, brand: str, limit: int = 10) -> list[Mention]:
    resp = await api.get(
        WIKIPEDIA,
        params={
            "action": "query",
            "list": "search",
            "srsearch": f'"{brand}"',
            "format": "json",
            "srlimit": limit,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return [
        Mention(
            "wikipedia",
            r["title"],
            f"https://en.wikipedia.org/wiki/{quote_plus(r['title'].replace(' ', '_'))}",
            note="Wikipedia links require independent reliable sources; never add your own (COI).",
        )
        for r in resp.json().get("query", {}).get("search", [])
    ]


def manual_searches(brand: str, domain: str) -> list[str]:
    q = quote_plus(f'"{brand}" -site:{domain}')
    return [
        f"https://www.google.com/search?q={q}",
        f"https://www.bing.com/search?q={q}",
        f"https://search.brave.com/search?q={q}",
        f"https://www.reddit.com/search/?q={quote_plus(brand)}",
    ]


def links_to(html_links: list[str], domain: str) -> bool:
    target = domain.removeprefix("www.")
    return any(bare_host(u) == target or bare_host(u).endswith("." + target) for u in html_links)


async def find_mentions(
    client: PoliteClient, api: httpx.AsyncClient, brand: str, site: str, check_pages: int = 25
) -> MentionReport:
    domain = urlsplit(site).hostname or site
    report = MentionReport(
        brand=brand, domain=domain, manual_searches=manual_searches(brand, domain)
    )
    for name, fn in (("hacker-news", hacker_news), ("wikipedia", wikipedia)):
        try:
            report.mentions.extend(await fn(api, brand))
        except (httpx.HTTPError, ValueError) as exc:
            report.errors[name] = str(exc)
    own = domain.removeprefix("www.")
    seen: set[str] = set()
    for m in report.mentions:
        if bare_host(m.url) == own:
            m.linked = True  # the mention points at your own site
            continue
        if m.url in seen or len(seen) >= check_pages:
            continue
        seen.add(m.url)
        page, status = await fetch_page(client, m.url)
        if page is None:
            m.note = f"{m.note} | not checked: {status}".strip(" |")
            continue
        mentioned = re.search(re.escape(brand), page.text, re.I) is not None
        m.linked = links_to([link.url for link in page.links], domain)
        if not mentioned and not m.linked:
            m.linked = None
            m.note = f"{m.note} | brand not found in page text".strip(" |")
    return report
