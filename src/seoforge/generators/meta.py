"""Meta tag suggestions built from each page's own headings and text."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from html import escape

from seoforge.analysis import pagetype as pt
from seoforge.crawler.crawler import CrawlResult
from seoforge.models import PageData

TITLE_MAX = 60
DESC_MAX = 155


@dataclass(slots=True)
class MetaSuggestion:
    url: str
    reasons: list[str] = field(default_factory=list)
    title: str | None = None
    description: str | None = None
    canonical: str | None = None
    viewport: bool = False
    og: dict[str, str] = field(default_factory=dict)
    todo: list[str] = field(default_factory=list)

    def html(self) -> str:
        lines = [f"<!-- {self.url}: {', '.join(self.reasons)} -->"]
        if self.viewport:
            lines.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
        if self.title:
            lines.append(f"<title>{escape(self.title)}</title>")
        if self.description:
            lines.append(f'<meta name="description" content="{escape(self.description)}">')
        if self.canonical:
            lines.append(f'<link rel="canonical" href="{escape(self.canonical)}">')
        for prop, content in self.og.items():
            lines.append(f'<meta property="{prop}" content="{escape(content)}">')
        lines.extend(f"<!-- TODO: {t} -->" for t in self.todo)
        return "\n".join(lines) + "\n"


def suggest_title(page: PageData, brand: str | None) -> str | None:
    base = page.h1s[0] if page.h1s else None
    if not base:
        return None
    base = pt.trim_words(base, TITLE_MAX)
    if brand and brand.lower() not in base.lower() and len(base) + len(brand) + 3 <= TITLE_MAX:
        return f"{base} | {brand}"
    return base


def suggest_description(page: PageData) -> str | None:
    para = pt.first_paragraph(page, min_words=12)
    if not para:
        return None
    out = ""
    for sentence in pt.sentences(para):
        if len(out) + len(sentence) + 1 > DESC_MAX:
            break
        out = f"{out} {sentence}".strip()
    return out or pt.trim_words(para, DESC_MAX)


def generate_meta(crawl: CrawlResult, brand: str | None) -> list[MetaSuggestion]:
    pages = [p for p in crawl.html_pages if p.is_indexable]
    title_counts = Counter((p.title or "").lower() for p in pages if p.title)
    desc_counts = Counter((p.meta_description or "").lower() for p in pages if p.meta_description)
    out = []
    for p in pages:
        s = MetaSuggestion(url=p.url)
        title_bad = (
            not p.title
            or len(p.title) > TITLE_MAX
            or len(p.title) < 15
            or title_counts[p.title.lower()] > 1
        )
        if title_bad:
            s.reasons.append("title " + ("missing" if not p.title else "needs work"))
            s.title = suggest_title(p, brand)
            if s.title is None or s.title == p.title:
                s.title = None
                s.todo.append("write a unique, descriptive <title> (about 30-60 characters)")
        desc_bad = (
            not p.meta_description
            or len(p.meta_description) > 160
            or desc_counts[p.meta_description.lower()] > 1
        )
        if desc_bad:
            s.reasons.append(
                "meta description " + ("missing" if not p.meta_description else "needs work")
            )
            s.description = suggest_description(p)
            if s.description is None or s.description == p.meta_description:
                s.description = None
                s.todo.append("write a unique meta description (about 70-155 characters)")
        if p.canonical is None:
            s.reasons.append("no canonical")
            s.canonical = p.url
        if not p.viewport:
            s.reasons.append("no viewport")
            s.viewport = True
        missing_og = {"og:title", "og:description", "og:url", "og:type"} - set(p.open_graph)
        if missing_og or "og:image" not in p.open_graph:
            s.reasons.append("incomplete Open Graph")
            values = {
                "og:title": s.title or p.title,
                "og:description": s.description or p.meta_description,
                "og:url": p.url,
                "og:type": "article" if pt.is_article(p) else "website",
            }
            for prop in sorted(missing_og):
                if values.get(prop):
                    s.og[prop] = str(values[prop])
            if "og:image" not in p.open_graph:
                image = next(
                    (i.src for i in p.images if i.src.startswith("http") and i.width), None
                )
                if image:
                    s.og["og:image"] = image
                else:
                    s.todo.append("og:image: add a 1200x630 share image")
        if s.reasons:
            out.append(s)
    return out
