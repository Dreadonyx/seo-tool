"""JSON-LD generator. Fills values only from crawl data or seoforge.yaml; anything unknown is
left out and listed under `todo`, never invented."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from seoforge.analysis import aeo
from seoforge.analysis import pagetype as pt
from seoforge.config import EntityConfig
from seoforge.crawler.crawler import CrawlResult
from seoforge.models import PageData

CONTEXT = "https://schema.org"


@dataclass(slots=True)
class SchemaDoc:
    url: str
    kind: str
    data: dict[str, Any]
    todo: list[str] = field(default_factory=list)

    def script_tag(self) -> str:
        body = json.dumps(self.data, indent=2, ensure_ascii=False)
        return f'<script type="application/ld+json">\n{body}\n</script>\n'


def _site_name(crawl: CrawlResult, entity: EntityConfig) -> str | None:
    if entity.name:
        return entity.name
    home = crawl.pages.get(crawl.start_url)
    if home is None:
        return None
    if home.open_graph.get("og:site_name"):
        return home.open_graph["og:site_name"]
    for node in pt.json_ld_nodes(home):
        if node.get("@type") in ("Organization", "WebSite") and node.get("name"):
            return str(node["name"])
    return None


def _existing_org(crawl: CrawlResult) -> dict[str, Any]:
    home = crawl.pages.get(crawl.start_url)
    if home is None:
        return {}
    for node in pt.json_ld_nodes(home):
        if node.get("@type") in ("Organization", "LocalBusiness", "Corporation", "Person"):
            return node
    return {}


def _existing_logo(crawl: CrawlResult) -> str | None:
    home = crawl.pages.get(crawl.start_url)
    if home is None:
        return None
    for node in pt.json_ld_nodes(home):
        logo = node.get("logo")
        if isinstance(logo, str):
            return logo
        if isinstance(logo, dict) and logo.get("url"):
            return str(logo["url"])
    return None


def organization(crawl: CrawlResult, entity: EntityConfig) -> SchemaDoc:
    org_type = entity.type or "Organization"
    data: dict[str, Any] = {
        "@context": CONTEXT,
        "@type": org_type,
        "@id": f"{crawl.site}/#organization",
    }
    todo: list[str] = []
    existing = _existing_org(crawl)
    fields = {
        "name": _site_name(crawl, entity),
        "legalName": entity.legal_name,
        "url": entity.url or crawl.start_url,
        "logo": entity.logo or _existing_logo(crawl),
        "description": entity.description or existing.get("description"),
        "foundingDate": entity.founded or existing.get("foundingDate"),
        "email": entity.email,
        "telephone": entity.telephone,
    }
    for key, value in fields.items():
        if value:
            data[key] = value
        elif key in ("name", "logo", "description"):
            todo.append(f"{key}: set entity.{key} in seoforge.yaml")
    if entity.founders and org_type != "Person":
        data["founder"] = [{"@type": "Person", "name": n} for n in entity.founders]
    if entity.address:
        data["address"] = {"@type": "PostalAddress", **entity.address}
    elif org_type == "LocalBusiness" or org_type.endswith("Business"):
        todo.append(
            "address: required for LocalBusiness - set entity.address (streetAddress, addressLocality, postalCode, addressCountry)"
        )
    same_as = list(dict.fromkeys(entity.same_as + list(_existing_org(crawl).get("sameAs") or [])))
    if same_as:
        data["sameAs"] = same_as
    else:
        todo.append("sameAs: list your official profiles (entity.same_as)")
    return SchemaDoc(crawl.start_url, org_type, data, todo)


def website(crawl: CrawlResult, entity: EntityConfig) -> SchemaDoc:
    data: dict[str, Any] = {
        "@context": CONTEXT,
        "@type": "WebSite",
        "@id": f"{crawl.site}/#website",
        "url": crawl.start_url,
        "publisher": {"@id": f"{crawl.site}/#organization"},
    }
    todo = []
    name = _site_name(crawl, entity)
    if name:
        data["name"] = name
    else:
        todo.append("name: set entity.name")
    if entity.site_search_url and "{search_term_string}" in entity.site_search_url:
        data["potentialAction"] = {
            "@type": "SearchAction",
            "target": {"@type": "EntryPoint", "urlTemplate": entity.site_search_url},
            "query-input": "required name=search_term_string",
        }
        todo.append(
            "note: Google retired the sitelinks search box (Nov 2024); SearchAction "
            "remains valid schema.org for other consumers."
        )
    return SchemaDoc(crawl.start_url, "WebSite", data, todo)


def _title_for(crawl: CrawlResult, url: str) -> str | None:
    page = crawl.pages.get(url) or crawl.pages.get(url.rstrip("/")) or crawl.pages.get(url + "/")
    if page is None or page.status != 200:
        return None
    return (page.h1s[0] if page.h1s else None) or page.title


def breadcrumbs(crawl: CrawlResult, page: PageData) -> SchemaDoc | None:
    parts = [p for p in urlsplit(page.url).path.split("/") if p]
    if len(parts) < 2:
        return None
    items = [{"@type": "ListItem", "position": 1, "name": "Home", "item": crawl.start_url}]
    todo = []
    for i in range(1, len(parts) + 1):
        url = f"{crawl.site}/{'/'.join(parts[:i])}"
        if i < len(parts):
            # Intermediate levels: prefer the crawled page title for '/a/' or '/a'.
            name = _title_for(crawl, url + "/") or _title_for(crawl, url)
            if name is None:
                continue  # no real page at this level: skip rather than invent one
            item_url = url + "/" if (url + "/") in crawl.pages else url
        else:
            name = _title_for(crawl, page.url) or parts[-1]
            item_url = page.url
        items.append(
            {"@type": "ListItem", "position": len(items) + 1, "name": name, "item": item_url}
        )
    if len(items) < 2:
        return None
    todo.append("Only use this if the page shows matching visible breadcrumbs.")
    return SchemaDoc(
        page.url,
        "BreadcrumbList",
        {"@context": CONTEXT, "@type": "BreadcrumbList", "itemListElement": items},
        todo,
    )


def webpage(crawl: CrawlResult, page: PageData) -> SchemaDoc:
    data: dict[str, Any] = {
        "@context": CONTEXT,
        "@type": "WebPage",
        "@id": f"{page.url}#webpage",
        "url": page.url,
        "isPartOf": {"@id": f"{crawl.site}/#website"},
    }
    if page.title:
        data["name"] = page.title
    if page.meta_description:
        data["description"] = page.meta_description
    if page.lang:
        data["inLanguage"] = page.lang
    modified = pt.modified_date(page)
    if modified:
        data["dateModified"] = modified
    return SchemaDoc(page.url, "WebPage", data)


def article(crawl: CrawlResult, page: PageData, entity: EntityConfig) -> SchemaDoc:
    data: dict[str, Any] = {"@context": CONTEXT, "@type": "Article", "mainEntityOfPage": page.url}
    todo: list[str] = []
    headline = page.h1s[0] if page.h1s else page.title
    if headline:
        data["headline"] = headline[:110]
    author = pt.author_name(page)
    if author:
        data["author"] = {"@type": "Person", "name": author}
        if pt.author_url(page):
            data["author"]["url"] = pt.author_url(page)
    else:
        todo.append("author: add a visible byline, then author {name, url}")
    published, modified = pt.published_date(page), pt.modified_date(page)
    if published:
        data["datePublished"] = published
    else:
        todo.append("datePublished: show a publish date on the page and add it here (ISO 8601)")
    if modified:
        data["dateModified"] = modified
    image = page.open_graph.get("og:image") or next(
        (i.src for i in page.images if i.src.startswith("http")), None
    )
    if image:
        data["image"] = [image]
    else:
        todo.append("image: add a representative image (min 50K pixels)")
    name = _site_name(crawl, entity)
    if name:
        data["publisher"] = {
            "@type": "Organization",
            "name": name,
            "@id": f"{crawl.site}/#organization",
        }
    return SchemaDoc(page.url, "Article", data, todo)


def faq(page: PageData) -> SchemaDoc | None:
    """FAQPage from visible question headings and the text that follows them."""
    result = aeo.analyze_page(page, None, "unknown")
    pairs = [(q.question, q.answer) for q in result.qa if q.answer and q.words >= 5]
    if len(pairs) < 2:
        return None
    entities = [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
        for q, a in pairs
    ]
    return SchemaDoc(
        page.url,
        "FAQPage",
        {"@context": CONTEXT, "@type": "FAQPage", "mainEntity": entities},
        [
            "Google shows FAQ rich results only for well-known government/health sites; "
            "the markup still helps other engines. Keep questions visible on the page."
        ],
    )


HOWTO_HEADING = re.compile(r"^how (to|do you|do i|can i)\b", re.I)


def howto(page: PageData) -> SchemaDoc | None:
    steps: list[str] = []
    name = None
    capture = False
    for tag, text in page.outline:
        if tag.startswith("h"):
            if capture and steps:
                break
            capture = bool(HOWTO_HEADING.match(text))
            name = text if capture else name
        elif capture and tag == "li":
            steps.append(text)
    if len(steps) < 2 or not name:
        return None
    data = {
        "@context": CONTEXT,
        "@type": "HowTo",
        "name": name.rstrip("?"),
        "step": [{"@type": "HowToStep", "position": i + 1, "text": s} for i, s in enumerate(steps)],
    }
    return SchemaDoc(
        page.url,
        "HowTo",
        data,
        ["Google no longer shows HowTo rich results (2023); kept for other consumers."],
    )


def product(page: PageData) -> SchemaDoc:
    data: dict[str, Any] = {"@context": CONTEXT, "@type": "Product"}
    name = page.h1s[0] if page.h1s else page.title
    if name:
        data["name"] = name
    if page.meta_description:
        data["description"] = page.meta_description
    image = page.open_graph.get("og:image") or next(
        (i.src for i in page.images if i.src.startswith("http")), None
    )
    if image:
        data["image"] = [image]
    todo = [
        'offers: add {"@type": "Offer", "price": ..., "priceCurrency": ..., '
        '"availability": "https://schema.org/InStock", "url": ...} with your real price',
        "brand, sku/gtin: add if you have them",
        "aggregateRating/review: only with genuine reviews shown on the page (never fabricate)",
    ]
    return SchemaDoc(page.url, "Product", data, todo)


def person(name: str, url: str | None, same_as: list[str] | None = None) -> SchemaDoc:
    data: dict[str, Any] = {"@context": CONTEXT, "@type": "Person", "name": name}
    if url:
        data["url"] = url
    if same_as:
        data["sameAs"] = same_as
    return SchemaDoc(
        url or "",
        "Person",
        data,
        ["jobTitle, image, sameAs (LinkedIn, GitHub, etc.): add for author pages"],
    )


def _complete_product(page: PageData) -> bool:
    return any(
        n.get("@type") == "Product"
        and n.get("name")
        and (n.get("offers") or n.get("aggregateRating"))
        for n in pt.json_ld_nodes(page)
    )


def generate_all(crawl: CrawlResult, entity: EntityConfig) -> list[SchemaDoc]:
    docs: list[SchemaDoc] = [organization(crawl, entity), website(crawl, entity)]
    authors: dict[str, str | None] = {}
    for page in crawl.html_pages:
        if not page.is_indexable:
            continue
        existing = pt.schema_types(page)
        docs.append(webpage(crawl, page))
        crumb = breadcrumbs(crawl, page)
        if crumb and "BreadcrumbList" not in existing:
            docs.append(crumb)
        if pt.is_article(page) and not existing & {
            "Article",
            "BlogPosting",
            "NewsArticle",
            "TechArticle",
        }:
            docs.append(article(crawl, page, entity))
        if pt.is_product(page) and not _complete_product(page):
            docs.append(product(page))
        if "FAQPage" not in existing and (f := faq(page)):
            docs.append(f)
        if "HowTo" not in existing and (h := howto(page)):
            docs.append(h)
        if pt.is_article(page) and (name := pt.author_name(page)):
            authors.setdefault(name, pt.author_url(page))
    docs.extend(person(n, u) for n, u in authors.items())
    return docs
