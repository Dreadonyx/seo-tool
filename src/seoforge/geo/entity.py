"""Entity building: sameAs graph, brand-consistency checks, fact sheet and a Wikidata draft.

Nothing here creates accounts or edits Wikidata. It reports what exists, what is missing and
drafts statements for a human to review against Wikidata's notability policy.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from seoforge.analysis import pagetype as pt
from seoforge.config import EntityConfig
from seoforge.crawler.crawler import CrawlResult
from seoforge.urls import bare_host

WIKIDATA_API = "https://www.wikidata.org/w/api.php"

# platform -> (host suffixes, why it matters)
PLATFORMS: dict[str, tuple[tuple[str, ...], str]] = {
    "Wikidata": (
        ("wikidata.org",),
        "Machine-readable knowledge base used by search engines and LLM pipelines.",
    ),
    "Wikipedia": (
        ("wikipedia.org",),
        "Only if independently notable - never write your own article (COI).",
    ),
    "LinkedIn": (("linkedin.com",), "Company page: official name, logo, website, size."),
    "GitHub": (
        ("github.com",),
        "Organization profile with website and description (for software).",
    ),
    "Crunchbase": (("crunchbase.com",), "Company profile: founders, funding, HQ - widely scraped."),
    "X / Twitter": (("twitter.com", "x.com"), "Official handle with website link."),
    "Facebook": (("facebook.com",), "Page with consistent name/address (local businesses)."),
    "Instagram": (("instagram.com",), "Bio with website link."),
    "YouTube": (("youtube.com",), "Channel 'About' with links."),
    "Reddit": (
        ("reddit.com",),
        "Participate genuinely; a profile/subreddit helps brand disambiguation.",
    ),
    "Quora": (("quora.com",), "Answer questions in your expertise with disclosure."),
    "Product Hunt": (("producthunt.com",), "Product page (for launches)."),
    "Google Business Profile": (
        ("g.page", "business.google.com", "maps.google.com", "goo.gl"),
        "Essential for local businesses (free).",
    ),
    "Bing Places": (("bingplaces.com",), "Free; feeds Bing/Copilot local answers."),
    "Apple Business Connect": (("businessconnect.apple.com",), "Free; Apple Maps/Siri."),
    "G2 / Capterra": (
        ("g2.com", "capterra.com"),
        "Software review profiles (never buy or gate reviews).",
    ),
    "Trustpilot": (
        ("trustpilot.com",),
        "Review profile (follow its guidelines; no incentivized reviews).",
    ),
    "Medium / Dev.to / Substack": (
        ("medium.com", "dev.to", "substack.com"),
        "Syndicated expert content with canonical links.",
    ),
}

PLATFORM_PROPS = {  # Wikidata identifier properties derivable from profile URLs
    "github.com": ("P2037", r"github\.com/([^/?#]+)"),
    "twitter.com": ("P2002", r"twitter\.com/([^/?#]+)"),
    "x.com": ("P2002", r"x\.com/([^/?#]+)"),
    "linkedin.com": ("P4264", r"linkedin\.com/company/([^/?#]+)"),
    "crunchbase.com": ("P2088", r"crunchbase\.com/organization/([^/?#]+)"),
    "reddit.com": ("P3984", r"reddit\.com/r/([^/?#]+)"),
    "youtube.com": ("P2397", r"youtube\.com/channel/([^/?#]+)"),
    "instagram.com": ("P2003", r"instagram\.com/([^/?#]+)"),
    "facebook.com": ("P2013", r"facebook\.com/([^/?#]+)"),
}
INSTANCE_OF = {
    "Organization": "Q43229",
    "Corporation": "Q4830453",
    "LocalBusiness": "Q4830453",
    "Person": "Q5",
    "SoftwareApplication": "Q7397",
}


@dataclass(slots=True)
class EntityReport:
    name: str | None
    same_as: list[str] = field(default_factory=list)
    platforms: dict[str, str | None] = field(default_factory=dict)  # platform -> URL or None
    name_variants: dict[str, int] = field(default_factory=dict)
    logo_variants: list[str] = field(default_factory=list)
    missing_facts: list[str] = field(default_factory=list)
    wikidata_candidates: list[dict[str, str]] = field(default_factory=list)
    wikidata_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "same_as": self.same_as,
            "platforms": self.platforms,
            "name_variants": self.name_variants,
            "logo_variants": self.logo_variants,
            "missing_facts": self.missing_facts,
            "wikidata_candidates": self.wikidata_candidates,
            "wikidata_error": self.wikidata_error,
        }


def _org_nodes(crawl: CrawlResult) -> list[dict[str, Any]]:
    nodes = []
    for page in crawl.html_pages:
        for node in pt.json_ld_nodes(page):
            if node.get("@type") in (
                "Organization",
                "Corporation",
                "LocalBusiness",
                "Person",
                "WebSite",
            ):
                nodes.append(node)
    return nodes


def collect_same_as(crawl: CrawlResult, entity: EntityConfig) -> list[str]:
    urls = list(entity.same_as)
    for node in _org_nodes(crawl):
        same = node.get("sameAs") or []
        urls.extend(str(u) for u in (same if isinstance(same, list) else [same]))
    return list(dict.fromkeys(u for u in urls if u.startswith("http")))


def name_variants(crawl: CrawlResult, entity: EntityConfig) -> Counter[str]:
    """Brand names used across og:site_name, schema names and title suffixes."""
    counts: Counter[str] = Counter()
    for page in crawl.html_pages:
        if page.open_graph.get("og:site_name"):
            counts[page.open_graph["og:site_name"].strip()] += 1
        if page.title:
            parts = re.split(r"\s[|\-–—:·]\s", page.title)
            if len(parts) > 1:
                counts[parts[-1].strip()] += 1
    for node in _org_nodes(crawl):
        if node.get("@type") != "Person" and node.get("name"):
            counts[str(node["name"]).strip()] += 1
    if entity.name:
        counts[entity.name] += 1
    return counts


def brand_name(crawl: CrawlResult, entity: EntityConfig) -> str | None:
    """Config name > og:site_name > Organization/WebSite markup > shared title affix."""
    if entity.name:
        return entity.name
    home = crawl.pages.get(crawl.start_url)
    if home is not None and home.open_graph.get("og:site_name"):
        return home.open_graph["og:site_name"].strip()
    for node in _org_nodes(crawl):
        if node.get("@type") != "Person" and node.get("name"):
            return str(node["name"]).strip()
    affixes: Counter[str] = Counter()
    for page in crawl.html_pages:
        parts = re.split(r"\s[|\-–—:·]\s", page.title or "")
        if len(parts) > 1:
            affixes.update({parts[0].strip(), parts[-1].strip()})
    common = [a for a, n in affixes.most_common() if n > 1]
    return common[0] if common else None


def analyze(crawl: CrawlResult, entity: EntityConfig) -> EntityReport:
    variants = name_variants(crawl, entity)
    name = brand_name(crawl, entity)
    report = EntityReport(name=name, same_as=collect_same_as(crawl, entity))
    hosts = {bare_host(u): u for u in report.same_as}
    for platform, (suffixes, _) in PLATFORMS.items():
        report.platforms[platform] = next(
            (u for h, u in hosts.items() if any(h == s or h.endswith("." + s) for s in suffixes)),
            None,
        )
    # Keep only names that look like the same brand written differently.
    if name:
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        report.name_variants = {
            v: c
            for v, c in variants.items()
            if key[:4] and key[:4] in re.sub(r"[^a-z0-9]", "", v.lower())
        }
    logos = set()
    for node in _org_nodes(crawl):
        logo = node.get("logo")
        if isinstance(logo, dict):
            logo = logo.get("url")
        if logo:
            logos.add(str(logo))
    report.logo_variants = sorted(logos)
    required = {
        "name": name,
        "description": entity.description,
        "logo": entity.logo or (sorted(logos)[0] if logos else None),
        "founded": entity.founded,
        "category": entity.category,
    }
    report.missing_facts = [k for k, v in required.items() if not v]
    return report


async def wikidata_search(
    client: httpx.AsyncClient, name: str, lang: str = "en"
) -> list[dict[str, str]]:
    resp = await client.get(
        WIKIDATA_API,
        params={
            "action": "wbsearchentities",
            "search": name,
            "language": lang,
            "format": "json",
            "type": "item",
            "limit": 7,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return [
        {
            "id": r.get("id", ""),
            "label": r.get("label", ""),
            "description": r.get("description", ""),
            "url": f"https://www.wikidata.org/wiki/{r.get('id', '')}",
        }
        for r in resp.json().get("search", [])
    ]


def wikidata_draft(
    entity: EntityConfig, site: str, same_as: list[str], name: str | None = None
) -> tuple[str, str]:
    """Return (QuickStatements v1 commands, Markdown guide). Unknown values become TODOs in the
    guide only, so the .qs file contains nothing but valid commands."""
    name = entity.name or name or "TODO name"
    qs = ["CREATE", f'LAST\tLen\t"{name}"']
    notes = [
        "# Wikidata draft (review before use)",
        "",
        "1. **Search first** - the entity may already exist (see candidates in `seoforge geo entity`).",
        "2. **Check notability**: https://www.wikidata.org/wiki/Wikidata:Notability - an item needs a "
        "Wikipedia sitelink, OR serious, publicly available independent references, OR a structural "
        "need. Promotional items get deleted.",
        "3. **Disclose** any conflict of interest on your Wikidata user page.",
        "4. **Reference** every statement (P854 reference URL to an independent source where possible).",
        "5. Paste `wikidata.qs` into https://quickstatements.toolforge.org/ (needs a Wikidata account), "
        "or enter statements manually.",
        "",
        "## Statements in wikidata.qs",
        "",
        "| Property | Value | Note |",
        "|---|---|---|",
        f"| label (en) | {name} | |",
    ]
    todo: list[str] = []
    if entity.description:
        desc = entity.description.rstrip(".")
        if len(desc) <= 250:
            desc = desc[0].lower() + desc[1:]
            qs.append(f'LAST\tDen\t"{desc}"')
            notes.append(
                f"| description (en) | {desc} | Wikidata descriptions are short, lowercase, neutral |"
            )
    else:
        todo.append('description: short neutral phrase, e.g. "software company based in Chennai"')
    instance = INSTANCE_OF.get(entity.type, "Q43229")
    qs.append(f"LAST\tP31\t{instance}")
    notes.append(f"| P31 instance of | {instance} | verify the most specific class |")
    website = entity.url or site
    qs.append(f'LAST\tP856\t"{website}"')
    notes.append(f"| P856 official website | {website} | |")
    if entity.founded and re.match(r"^\d{4}", entity.founded):
        qs.append(f"LAST\tP571\t+{entity.founded[:4]}-00-00T00:00:00Z/9")
        notes.append(f"| P571 inception | {entity.founded[:4]} | year precision |")
    else:
        todo.append("P571 inception: founding year")
    for url in same_as:
        host = bare_host(url)
        for domain, (prop, pattern) in PLATFORM_PROPS.items():
            if host == domain or host.endswith("." + domain):
                m = re.search(pattern, url)
                if m:
                    qs.append(f'LAST\t{prop}\t"{m.group(1)}"')
                    notes.append(f"| {prop} | {m.group(1)} | from {url} |")
    todo += [f"P112 founded by: item ID for '{f}' (only if they have one)" for f in entity.founders]
    if entity.city:
        todo.append(f"P159 headquarters location: item ID for '{entity.city}'")
    if todo:
        notes += ["", "## Still to do (needs your input)", ""] + [f"- {t}" for t in todo]
    return "\n".join(qs) + "\n", "\n".join(notes) + "\n"


def fact_sheet(
    crawl: CrawlResult, entity: EntityConfig, report: EntityReport, topics: list[str] | None = None
) -> tuple[str, dict[str, Any]]:
    """Markdown + JSON fact sheet. Only facts from config or the crawl are included."""
    facts: dict[str, Any] = {
        "name": report.name,
        "legal_name": entity.legal_name,
        "type": entity.type,
        "description": entity.description,
        "website": entity.url or crawl.start_url,
        "category": entity.category,
        "location": entity.city,
        "address": entity.address or None,
        "founded": entity.founded,
        "founders": entity.founders or None,
        "email": entity.email,
        "telephone": entity.telephone,
        "logo": entity.logo or (report.logo_variants[0] if report.logo_variants else None),
        "official_profiles": report.same_as or None,
        "wikidata": f"https://www.wikidata.org/wiki/{entity.wikidata_id}"
        if entity.wikidata_id
        else None,
        "topics": topics or None,
    }
    facts = {k: v for k, v in facts.items() if v}
    lines = [
        f"# {report.name or urlsplit(crawl.site).netloc}: fact sheet",
        "",
        "Verified facts maintained by the site owner. Cite this page for accurate details.",
        "",
    ]
    for key, value in facts.items():
        label = key.replace("_", " ").capitalize()
        if isinstance(value, list):
            lines.append(f"- **{label}:** " + ", ".join(str(v) for v in value))
        elif isinstance(value, dict):
            lines.append(f"- **{label}:** " + ", ".join(str(v) for v in value.values()))
        else:
            lines.append(f"- **{label}:** {value}")
    if report.missing_facts:
        lines += [
            "",
            "<!-- TODO (not published until you fill them in seoforge.yaml): "
            + ", ".join(report.missing_facts)
            + " -->",
        ]
    return "\n".join(lines) + "\n", facts


def entity_json(facts: dict[str, Any]) -> str:
    return json.dumps(facts, indent=2, ensure_ascii=False) + "\n"
