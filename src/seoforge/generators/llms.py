"""/llms.txt, /llms-full.txt and per-page Markdown mirrors (https://llmstxt.org/ proposal).

Adoption note: llms.txt is a community proposal. Major AI providers have not confirmed using
it, so treat it as a low-cost, low-certainty addition, not a ranking lever.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlsplit

from seoforge.analysis import pagetype as pt
from seoforge.config import Config
from seoforge.crawler.crawler import CrawlResult
from seoforge.generators.markdown import html_to_markdown
from seoforge.models import PageData

OPTIONAL_PATHS = re.compile(
    r"/(privacy|terms|legal|cookie|imprint|impressum|tos|careers|jobs)", re.I
)
MAX_FULL_BYTES = 2_000_000


@dataclass(slots=True)
class LlmsFiles:
    llms_txt: str
    llms_full_txt: str
    mirrors: dict[str, str]  # deploy path -> markdown


def mirror_path(url: str) -> str:
    """llmstxt.org convention: same URL with .md appended (index.html.md for directory URLs)."""
    path = urlsplit(url).path or "/"
    if path.endswith("/"):
        return path.lstrip("/") + "index.html.md"
    return path.lstrip("/") + ".md"


def _section_name(url: str) -> str:
    parts = [p for p in urlsplit(url).path.split("/") if p]
    if len(parts) <= 1:
        return "Main pages"
    return parts[0].replace("-", " ").replace("_", " ").title()


def _summary(page: PageData) -> str:
    text = page.meta_description or pt.first_paragraph(page) or ""
    return pt.trim_words(text, 160)


def _site_title(crawl: CrawlResult, config: Config) -> str:
    from seoforge.geo.entity import brand_name

    return brand_name(crawl, config.entity) or urlsplit(crawl.site).netloc


def key_pages(crawl: CrawlResult, limit: int = 200) -> list[PageData]:
    pages = [p for p in crawl.html_pages if p.is_indexable and p.word_count >= 30]
    inlinks: dict[str, int] = defaultdict(int)
    for src, targets in crawl.edges.items():
        for t in targets:
            if t != src:
                inlinks[t] += 1
    pages.sort(key=lambda p: (p.url != crawl.start_url, -inlinks[p.url], p.url))
    return pages[:limit]


def generate(crawl: CrawlResult, config: Config, md_links: bool = False) -> LlmsFiles:
    title = _site_title(crawl, config)
    home = crawl.pages.get(crawl.start_url)
    summary = config.entity.description or (home.meta_description if home else None) or ""
    pages = key_pages(crawl)

    custom = {
        name: [re.compile(p) for p in pats] for name, pats in config.geo.llms_txt_sections.items()
    }
    sections: dict[str, list[PageData]] = defaultdict(list)
    optional: list[PageData] = []
    for p in pages:
        name = next((n for n, pats in custom.items() if any(r.search(p.url) for r in pats)), None)
        if name:
            sections[name].append(p)
        elif OPTIONAL_PATHS.search(urlsplit(p.url).path):
            optional.append(p)
        else:
            sections[_section_name(p.url)].append(p)

    def line(p: PageData) -> str:
        label = (p.h1s[0] if p.h1s else p.title) or urlsplit(p.url).path
        link = f"{crawl.site}/{mirror_path(p.url)}" if md_links else p.url
        desc = _summary(p)
        return f"- [{label}]({link})" + (f": {desc}" if desc else "")

    out = [f"# {title}", ""]
    if summary:
        out += [f"> {summary}", ""]
    facts = [f"Website: {crawl.site}"]
    if config.entity.category:
        facts.append(f"Category: {config.entity.category}")
    if config.entity.city:
        facts.append(f"Location: {config.entity.city}")
    out += [*facts, ""]
    order = sorted(sections, key=lambda n: (n != "Main pages", n))
    for name in order:
        out += [f"## {name}", ""] + [line(p) for p in sections[name]] + [""]
    if optional:
        out += ["## Optional", ""] + [line(p) for p in optional] + [""]

    mirrors: dict[str, str] = {}
    full = [f"# {title}", "", f"> {summary}" if summary else "", ""]
    size = 0
    for p in pages:
        md = html_to_markdown(p.html, p.final_url, p.title, p.url)
        if not md.strip():
            continue
        mirrors[mirror_path(p.url)] = md
        if size + len(md) <= MAX_FULL_BYTES:
            full += ["---", "", md]
            size += len(md)
    return LlmsFiles("\n".join(out).rstrip() + "\n", "\n".join(full).rstrip() + "\n", mirrors)
