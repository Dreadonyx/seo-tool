"""Content gap against user-supplied competitor URLs (fetched politely, robots.txt respected)."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from seoforge.analysis.keywords import STOPWORDS, page_terms
from seoforge.crawler.parser import parse_html
from seoforge.http import PoliteClient, RobotsDisallowed
from seoforge.models import PageData
from seoforge.urls import normalize


@dataclass(slots=True)
class GapReport:
    competitors: dict[str, str] = field(default_factory=dict)  # url -> status/error
    gaps: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "competitors": self.competitors,
            "gaps": self.gaps,
            "note": "Terms that appear prominently on competitor pages you supplied but nowhere "
            "on your crawled pages. Relevance is for you to judge; no volumes implied.",
        }


async def fetch_page(client: PoliteClient, url: str) -> tuple[PageData | None, str]:
    target = normalize(url)
    if target is None:
        return None, "invalid URL"
    try:
        result = await client.fetch(target)
    except RobotsDisallowed:
        return None, "blocked by robots.txt (respected)"
    if result.error or result.status != 200:
        return None, result.error or f"HTTP {result.status}"
    page = PageData(
        url=target,
        final_url=result.final_url,
        status=200,
        headers=result.headers,
        content_type=result.headers.get("content-type", ""),
    )
    if not page.is_html:
        return None, "not HTML"
    return parse_html(page, result.text, target), "ok"


async def content_gap(
    client: PoliteClient, own_pages: list[PageData], competitor_urls: list[str], top: int = 80
) -> GapReport:
    report = GapReport()
    own: Counter[str] = Counter()
    for p in own_pages:
        own.update(page_terms(p))
    weights: dict[str, float] = defaultdict(float)
    seen_in: Counter[str] = Counter()
    for url in competitor_urls:
        page, status = await fetch_page(client, url)
        report.competitors[url] = status
        if page is None:
            continue
        terms = page_terms(page)
        total = sum(terms.values()) or 1
        for term, count in terms.items():
            if term in own or count < 2:
                continue
            words = term.split()
            if len(words) == 1 and (len(term) < 4 or term in STOPWORDS):
                continue
            weights[term] += count / total * 1000 * (1 + 0.5 * (len(words) - 1))
            seen_in[term] += 1
    ranked = sorted(weights, key=lambda t: (-seen_in[t], -weights[t]))
    # Drop sub-phrases already covered by a higher-ranked longer phrase.
    chosen: list[str] = []
    for term in ranked:
        if any(term in longer and term != longer for longer in chosen):
            continue
        chosen.append(term)
        if len(chosen) >= top:
            break
    report.gaps = [
        {"term": t, "competitors": seen_in[t], "score": round(weights[t], 2)} for t in chosen
    ]
    return report
