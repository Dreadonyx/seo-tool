"""Page classification and metadata helpers derived only from crawled data."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

from seoforge.models import PageData
from seoforge.urls import bare_host

ARTICLE_PATH = re.compile(
    r"/(blog|news|articles?|posts?|guides?|insights|stories|learn)/[^/]+", re.I
)
PRODUCT_PATH = re.compile(r"/(products?|shop|store|item|p)/[^/]+", re.I)
SOCIAL_HOSTS = (
    "facebook.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "instagram.com",
    "youtube.com",
    "tiktok.com",
    "pinterest.com",
    "reddit.com",
    "github.com",
    "t.me",
    "wa.me",
    "threads.net",
)


def json_ld_nodes(page: PageData) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            if "@type" in node:
                out.append(node)
            for v in node.values():
                if isinstance(v, dict | list):
                    walk(v)

    for raw in page.json_ld:
        try:
            walk(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def schema_types(page: PageData) -> set[str]:
    types: set[str] = set()
    for node in json_ld_nodes(page):
        t = node.get("@type")
        types.update(str(x) for x in (t if isinstance(t, list) else [t]))
    return types


def is_article(page: PageData) -> bool:
    types = schema_types(page)
    if types & {"Article", "NewsArticle", "BlogPosting", "TechArticle"}:
        return True
    if page.open_graph.get("og:type") == "article":
        return True
    has_byline = bool(author_name(page)) or bool(page.times)
    return bool(ARTICLE_PATH.search(urlsplit(page.url).path)) and (
        has_byline or page.word_count > 300
    )


def is_product(page: PageData) -> bool:
    if "Product" in schema_types(page) or page.open_graph.get("og:type") == "product":
        return True
    return bool(PRODUCT_PATH.search(urlsplit(page.url).path))


def author_name(page: PageData) -> str | None:
    for node in json_ld_nodes(page):
        author = node.get("author")
        if isinstance(author, dict) and author.get("name"):
            return str(author["name"])
        if isinstance(author, list) and author and isinstance(author[0], dict):
            return str(author[0].get("name") or "") or None
        if isinstance(author, str) and author:
            return author
    if page.meta.get("author"):
        return page.meta["author"]
    if page.open_graph.get("article:author") and not page.open_graph["article:author"].startswith(
        "http"
    ):
        return page.open_graph["article:author"]
    for link in page.links:
        if "author" in link.rel.lower().split() and link.text:
            return link.text
    return None


def author_url(page: PageData) -> str | None:
    for link in page.links:
        if "author" in link.rel.lower().split():
            return link.url
    for node in json_ld_nodes(page):
        author = node.get("author")
        if isinstance(author, dict) and author.get("url"):
            return str(author["url"])
    return None


def published_date(page: PageData) -> str | None:
    for node in json_ld_nodes(page):
        if node.get("datePublished"):
            return str(node["datePublished"])
    return page.open_graph.get("article:published_time") or (page.times[0] if page.times else None)


def modified_date(page: PageData) -> str | None:
    for node in json_ld_nodes(page):
        if node.get("dateModified"):
            return str(node["dateModified"])
    return (
        page.open_graph.get("article:modified_time")
        or page.open_graph.get("og:updated_time")
        or (page.times[-1] if len(page.times) > 1 else None)
    )


def citations(page: PageData) -> list[str]:
    """Outbound links that look like sources (not social profiles, not same site)."""
    return [
        link.url for link in page.external_links if not bare_host(link.url).endswith(SOCIAL_HOSTS)
    ]


def first_paragraph(page: PageData, min_words: int = 8) -> str | None:
    for tag, text in page.outline:
        if tag == "p" and len(text.split()) >= min_words:
            return text
    return page.paragraphs[0] if page.paragraphs else None


def trim_words(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1].rsplit(" ", 1)[0].rstrip(",;:-")
    return cut + "…"


def sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"“])", text) if s.strip()]
