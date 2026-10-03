"""Citation-friendliness score: a transparent heuristic for how easy a page is for AI answer
engines to retrieve, quote and attribute. It is an estimate, not a measurement of any AI system.

Components (max points):
  quotable statements   20  self-contained factual sentences (definitions, numbers)
  sourced statistics    15  numbers backed by outbound source links
  freshness             15  visible/structured modified or published date in the last 12 months
  authorship            10  identifiable author (or organization for non-articles)
  structure             15  question headings, H2 sections, lists/tables
  answer blocks         10  at least one concise answer under a question heading
  server-rendered text  10  main content present without JavaScript
  structured data        5  any valid JSON-LD
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from seoforge.analysis import pagetype as pt
from seoforge.analysis.aeo import PageAEO
from seoforge.models import PageData

NUMBER = re.compile(r"\b\d[\d,.]*\s?(%|percent|million|billion|thousand|k\b|x\b)?", re.I)
DEFINITIONAL = re.compile(r"\b(is|are|was|refers to|means|consists of|includes)\b", re.I)
SPA_ROOT = re.compile(r'id=["\'](root|app|__next|__nuxt)["\']', re.I)


@dataclass(slots=True)
class CitationScore:
    url: str
    score: int
    components: dict[str, int] = field(default_factory=dict)
    quotable_examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "score": self.score,
            "components": self.components,
            "quotable_examples": self.quotable_examples,
            "estimate": True,
        }


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")[:25]).date()
    except ValueError:
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
        return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def quotable_sentences(page: PageData) -> list[str]:
    out = []
    for block in page.blocks:
        for s in pt.sentences(block):
            n = len(s.split())
            if (
                8 <= n <= 35
                and s.endswith((".", "!"))
                and (DEFINITIONAL.search(s) or NUMBER.search(s))
                and not s.lower().startswith(("click", "subscribe", "sign up", "cookie"))
            ):
                out.append(s)
    return out


def score_page(page: PageData, aeo: PageAEO | None, today: date | None = None) -> CitationScore:
    today = today or datetime.now(UTC).date()
    c: dict[str, int] = {}
    quotable = quotable_sentences(page)
    c["quotable"] = min(20, len(quotable) * 4)

    stats = [s for s in quotable if NUMBER.search(s) and re.search(r"\d", s)]
    cites = pt.citations(page)
    if stats and cites:
        c["sourced_stats"] = 15
    elif stats:
        c["sourced_stats"] = 4
    else:
        c["sourced_stats"] = 7  # neutral: no statistics to source

    when = _parse_date(pt.modified_date(page)) or _parse_date(pt.published_date(page))
    if when is None:
        c["freshness"] = 0
    else:
        age = (today - when).days
        c["freshness"] = 15 if age <= 365 else 8 if age <= 730 else 3

    if pt.author_name(page):
        c["authorship"] = 10
    elif not pt.is_article(page) and any(
        n.get("@type") in ("Organization", "LocalBusiness") for n in pt.json_ld_nodes(page)
    ):
        c["authorship"] = 6
    else:
        c["authorship"] = 0

    h2 = sum(1 for h in page.headings if h.level == 2)
    structure = 0
    structure += 6 if aeo and aeo.questions else 0
    structure += 5 if h2 >= 2 else 2 if h2 == 1 else 0
    structure += 4 if page.lists_count or page.tables_count else 0
    c["structure"] = structure

    c["answer_blocks"] = 10 if aeo and aeo.answer_blocks else 0

    if page.rendered and page.raw_word_count is not None:
        ratio = page.raw_word_count / max(page.word_count, 1)
        c["server_rendered"] = 10 if ratio >= 0.8 else 5 if ratio >= 0.5 else 0
    else:
        c["server_rendered"] = 0 if (page.word_count < 30 and SPA_ROOT.search(page.html)) else 10

    c["structured_data"] = 5 if pt.json_ld_nodes(page) else 0
    return CitationScore(page.url, sum(c.values()), c, quotable[:3])


def score_pages(pages: list[PageData], aeo_pages: dict[str, PageAEO]) -> list[CitationScore]:
    scores = [score_page(p, aeo_pages.get(p.url)) for p in pages if p.is_indexable]
    return sorted(scores, key=lambda s: s.score)
