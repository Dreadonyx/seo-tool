"""'Why isn't this URL indexed?' - checks every common technical blocker for one URL."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from seoforge.analysis import pagetype as pt
from seoforge.checks.onpage import SPA_ROOT
from seoforge.config import Config
from seoforge.crawler.crawler import Crawler
from seoforge.crawler.parser import parse_html
from seoforge.crawler.sitemaps import discover_sitemaps
from seoforge.http import PoliteClient, origin
from seoforge.indexing.gsc import Inspection
from seoforge.models import PageData
from seoforge.storage import Store
from seoforge.urls import normalize, same_site

Status = Literal["pass", "warn", "fail", "info"]


@dataclass(slots=True)
class Finding:
    check: str
    status: Status
    detail: str
    fix: str = ""


@dataclass(slots=True)
class Diagnosis:
    url: str
    findings: list[Finding] = field(default_factory=list)
    inspection: Inspection | None = None

    def add(self, check: str, status: Status, detail: str, fix: str = "") -> None:
        self.findings.append(Finding(check, status, detail, fix))

    @property
    def blockers(self) -> list[Finding]:
        return [f for f in self.findings if f.status == "fail"]


CLOSING_NOTE = (
    "If nothing technical blocks the URL, indexing is a choice the search engine makes based on "
    "perceived value, duplication and crawl priority. Strengthen internal links to it, make the "
    "content clearly unique and useful, keep it in the sitemap, and give it time. Resubmitting "
    "repeatedly does not help."
)


async def diagnose(
    url: str,
    config: Config,
    store: Store,
    *,
    crawl_pages: int = 0,
    client: PoliteClient | None = None,
) -> Diagnosis:
    target = normalize(url)
    if target is None:
        raise ValueError(f"Not an http(s) URL: {url}")
    result = Diagnosis(target)
    own = client is None
    client = client or PoliteClient(config.crawl, store)
    try:
        await _run(result, target, config, store, client, crawl_pages)
    finally:
        if own:
            await client.aclose()
    return result


async def _run(
    d: Diagnosis, target: str, config: Config, store: Store, client: PoliteClient, crawl_pages: int
) -> None:
    site = origin(target)
    robots = await client.robots(site)
    if robots.unreachable:
        d.add(
            "robots.txt",
            "fail",
            "robots.txt is unreachable (5xx/network). Google treats this as "
            "'disallow all' and may stop crawling.",
            "Make /robots.txt return 200 or 404.",
        )
    for bot in ("Googlebot", "Bingbot"):
        if robots.can_fetch(bot, target):
            d.add(f"robots.txt ({bot})", "pass", f"{bot} may crawl this URL.")
        else:
            rule = robots.matching_rule(bot, target)
            d.add(
                f"robots.txt ({bot})",
                "fail",
                f"Blocked by rule: {'Disallow' if rule else '?'}: {rule.path if rule else ''}",
                "Remove or narrow the Disallow rule.",
            )

    fetched = await client.fetch(target, check_robots=False)
    if fetched.error:
        d.add(
            "fetch",
            "fail",
            f"Could not fetch: {fetched.error}",
            "Check server availability/TLS/DNS.",
        )
        return
    if target.startswith("http://"):
        d.add("https", "warn", "URL uses HTTP.", "Serve over HTTPS and redirect HTTP to HTTPS.")
    if fetched.chain:
        hops = (
            " -> ".join(f"{h.status} {h.url}" for h in fetched.chain) + f" -> {fetched.final_url}"
        )
        d.add(
            "redirects",
            "fail" if len(fetched.chain) > 1 else "warn",
            f"URL redirects: {hops}. Engines index the destination, not this URL.",
            "Link to and submit the final URL instead.",
        )
    if fetched.status >= 400:
        d.add(
            "status",
            "fail",
            f"HTTP {fetched.status}.",
            "Return 200 for pages that should be indexed.",
        )
        return
    d.add("status", "pass", f"HTTP {fetched.status}.")
    page = PageData(
        url=target,
        final_url=fetched.final_url,
        status=fetched.status,
        headers=fetched.headers,
        content_type=fetched.headers.get("content-type", ""),
    )
    if not page.is_html:
        d.add("content type", "info", f"Not HTML ({page.content_type}).")
        return
    parse_html(page, fetched.text, site)

    if page.noindex:
        d.add(
            "noindex",
            "fail",
            f"noindex found (meta: '{page.meta_robots}', X-Robots-Tag: '{page.x_robots_tag}').",
            "Remove noindex if the page should be indexed.",
        )
    else:
        d.add("noindex", "pass", "No noindex directive.")
    if page.canonical and page.canonical.rstrip("/") != page.final_url.rstrip("/"):
        d.add(
            "canonical",
            "fail",
            f"Canonical points elsewhere: {page.canonical}. Engines will "
            "usually index that URL instead.",
            "Make the canonical self-referencing if this URL should rank.",
        )
    elif page.canonicals_count > 1:
        d.add(
            "canonical", "fail", "Multiple canonical tags; all may be ignored.", "Keep exactly one."
        )
    else:
        d.add("canonical", "pass", "Canonical is self-referencing or absent.")

    if page.word_count < 30 and "<script" in page.html and SPA_ROOT.search(page.html):
        d.add(
            "rendering",
            "warn",
            "Almost no text in the HTML; content likely needs JavaScript.",
            "Server-side render the main content.",
        )
    elif page.word_count < 150:
        d.add(
            "content",
            "warn",
            f"Only {page.word_count} words of main content (heuristic).",
            "Make sure the page offers unique, substantial value.",
        )
    else:
        d.add("content", "pass", f"{page.word_count} words of main content.")
    if any(t in (page.title or "").lower() for t in ("not found", "404", "error")):
        d.add(
            "soft 404",
            "fail",
            f"Title '{page.title}' looks like an error page served with 200.",
            "Return a real 404, or fix the content.",
        )

    sitemaps = await discover_sitemaps(client, site)
    in_sitemap = target in sitemaps.urls or target.rstrip("/") in sitemaps.urls
    d.add(
        "sitemap",
        "pass" if in_sitemap else "warn",
        "Listed in the XML sitemap." if in_sitemap else "Not found in any discovered sitemap.",
        "" if in_sitemap else "Add it to your sitemap (`seoforge fix`) and resubmit the sitemap.",
    )

    if crawl_pages > 0:
        cfg = config.model_copy(deep=True)
        cfg.crawl.max_pages = crawl_pages
        crawl = await Crawler(cfg.crawl, store, client=client).crawl(site)
        linking = sorted(
            src
            for src, targets in crawl.edges.items()
            if (target in targets or page.final_url in targets) and src != target
        )
        if linking:
            d.add(
                "internal links",
                "pass",
                f"{len(linking)} crawled page(s) link here, e.g. {linking[0]}.",
            )
        else:
            d.add(
                "internal links",
                "warn",
                f"No internal links found in the first {crawl_pages} crawled pages.",
                "Link to it from relevant pages (orphans are crawled rarely).",
            )

    links_out = [link for link in page.internal_links if same_site(link.url, site)]
    if not links_out:
        d.add("outgoing links", "info", "Page links to no other internal pages.")
    if pt.is_article(page) and not pt.author_name(page):
        d.add(
            "quality signals",
            "info",
            "Article without an identifiable author.",
            "Add a byline and author page.",
        )
