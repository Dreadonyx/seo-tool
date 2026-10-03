"""Crawl-graph checks: broken links, redirects, orphans, depth, duplicates, soft 404s."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator

from seoforge import sources
from seoforge.checks.base import AuditContext, check
from seoforge.crawler.parser import hamming
from seoforge.models import Category, Effort, Issue, Severity

C = Category.CRAWL
SOFT_404_TITLE = re.compile(
    r"\b(404|not found|page (?:does not|doesn't) exist|no longer available)\b", re.I
)


def _linking_pages(ctx: AuditContext, target: str) -> list[str]:
    return sorted(src for src, targets in ctx.crawl.edges.items() if target in targets)


@check("broken-internal-links", C)
def broken_internal_links(ctx: AuditContext) -> Iterator[Issue]:
    broken = {
        p.url: p.status for p in ctx.all_pages if p.status >= 400 or (p.status == 0 and p.error)
    }
    linked = {url: _linking_pages(ctx, url) for url in broken}
    linked = {url: srcs for url, srcs in linked.items() if srcs}
    if linked:
        server_errors = [u for u in linked if broken[u] >= 500 or broken[u] == 0]
        yield Issue(
            "broken-internal-links",
            f"{len(linked)} internal URL(s) linked from your pages return errors",
            Severity.HIGH if not server_errors else Severity.CRITICAL,
            C,
            "Internal links point to URLs that return 4xx/5xx or fail to load. Users hit dead "
            "ends and crawlers waste crawl budget.",
            "Update each link to the correct live URL, or 301-redirect the dead URL to its "
            "closest replacement. Restore pages that should exist.",
            impact="Lost link equity and crawl budget; poor user experience.",
            effort=Effort.LOW,
            urls=sorted(linked),
            evidence={
                u: {"status": broken[u], "linked_from": linked[u][:10]} for u in sorted(linked)
            },
            source=sources.HTTP_ERRORS,
        )


@check("fetch-errors", C)
def fetch_errors(ctx: AuditContext) -> Iterator[Issue]:
    errors = {p.url: p.error for p in ctx.all_pages if p.error and p.status == 0}
    if errors:
        yield Issue(
            "fetch-errors",
            f"{len(errors)} URL(s) could not be fetched",
            Severity.HIGH,
            C,
            "Timeouts, DNS, TLS, or connection errors prevented fetching these URLs.",
            "Check server logs and uptime for these URLs; verify TLS certificates and DNS.",
            impact="Crawlers that cannot fetch a page cannot index it.",
            urls=sorted(errors),
            evidence=errors,
            source=sources.HTTP_ERRORS,
        )


@check("redirect-chains", C)
def redirect_chains(ctx: AuditContext) -> Iterator[Issue]:
    chains = {p.url: p for p in ctx.all_pages if len(p.redirect_chain) > 1}
    if chains:
        yield Issue(
            "redirect-chains",
            f"{len(chains)} redirect chain(s) with more than one hop",
            Severity.MEDIUM,
            C,
            "Each extra hop adds latency and Googlebot follows at most 10 hops per attempt.",
            "Point the first URL directly at the final destination with a single 301. "
            "`seoforge fix` generates collapsed redirect rules.",
            impact="Slower page loads and diluted crawl efficiency.",
            urls=sorted(chains),
            evidence={
                u: [f"{h.status} {h.url}" for h in p.redirect_chain] + [p.final_url]
                for u, p in chains.items()
            },
            source=sources.REDIRECTS,
        )
    loops = [p.url for p in ctx.all_pages if p.error in ("redirect loop", "too many redirects")]
    if loops:
        yield Issue(
            "redirect-loops",
            f"{len(loops)} redirect loop(s)",
            Severity.CRITICAL,
            C,
            "These URLs redirect in a loop (or more than 10 times) and never resolve.",
            "Fix the redirect rules so each URL resolves to a 200 page in one hop.",
            impact="Pages are unreachable for users and crawlers.",
            urls=loops,
            source=sources.REDIRECTS,
        )
    temporary = sorted(
        p.url
        for p in ctx.all_pages
        if p.redirect_chain
        and all(h.status in (302, 303, 307) for h in p.redirect_chain)
        and _linking_pages(ctx, p.url)
    )
    if temporary:
        yield Issue(
            "temporary-redirects",
            f"{len(temporary)} internally linked URL(s) use temporary redirects",
            Severity.LOW,
            C,
            "302/307 redirects signal a temporary move; for permanent moves Google recommends 301/308.",
            "Use 301 (or 308) for permanent moves and update internal links to the destination.",
            urls=temporary,
            source=sources.REDIRECTS,
        )


@check("links-to-redirects", C)
def links_to_redirects(ctx: AuditContext) -> Iterator[Issue]:
    redirecting = {p.url for p in ctx.all_pages if p.redirect_chain}
    hits: dict[str, list[str]] = defaultdict(list)
    for src, targets in ctx.crawl.edges.items():
        for target in targets & redirecting:
            hits[target].append(src)
    if hits:
        yield Issue(
            "links-to-redirects",
            f"Internal links point to {len(hits)} redirecting URL(s)",
            Severity.LOW,
            C,
            "Linking to a URL that redirects costs an extra request for users and crawlers.",
            "Update internal links to point straight at the final URL.",
            urls=sorted(hits),
            evidence={k: sorted(v)[:10] for k, v in hits.items()},
            source=sources.REDIRECTS,
        )


@check("orphan-pages", C)
def orphan_pages(ctx: AuditContext) -> Iterator[Issue]:
    inlinks = ctx.inlinks
    orphans = sorted(
        p.url
        for p in ctx.pages
        if p.url != ctx.crawl.start_url and inlinks.get(p.url, 0) == 0 and p.is_indexable
    )
    if orphans:
        yield Issue(
            "orphan-pages",
            f"{len(orphans)} orphan page(s) with no internal links",
            Severity.MEDIUM,
            C,
            "These pages were found (via sitemap or redirects) but no crawled page links to them. "
            "Crawlers discover and value pages largely through links.",
            "Link to each page from a relevant hub, category, or navigation page - or remove it "
            "from the sitemap if it should not exist.",
            impact="Orphans are crawled less often and receive no internal link equity.",
            effort=Effort.MEDIUM,
            urls=orphans,
            source=sources.LINKS,
        )


@check("deep-pages", C)
def deep_pages(ctx: AuditContext) -> Iterator[Issue]:
    depths = ctx.click_depths
    deep = sorted(p.url for p in ctx.pages if depths.get(p.url, 0) > 3 and p.is_indexable)
    if deep:
        yield Issue(
            "deep-pages",
            f"{len(deep)} page(s) are more than 3 clicks from the start page",
            Severity.LOW,
            C,
            "Pages buried deep in the link graph tend to be crawled less often. The 3-click "
            "threshold is a common heuristic, not a search engine rule.",
            "Add links from shallower hub pages, breadcrumbs, or related-content modules.",
            effort=Effort.MEDIUM,
            urls=deep,
            evidence={u: depths[u] for u in deep},
            source=sources.LINKS,
            estimate=True,
        )


@check("nofollow-internal", C)
def nofollow_internal(ctx: AuditContext) -> Iterator[Issue]:
    hits = sorted({p.url for p in ctx.pages if any(link.nofollow for link in p.internal_links)})
    if hits:
        yield Issue(
            "nofollow-internal",
            f"{len(hits)} page(s) use rel=nofollow on internal links",
            Severity.LOW,
            C,
            "nofollow on internal links withholds discovery signals from your own pages.",
            "Remove rel=nofollow from internal links (use noindex on the target page if it "
            "should not be indexed).",
            urls=hits,
            source=sources.LINKS,
        )


@check("duplicate-content", C)
def duplicate_content(ctx: AuditContext) -> Iterator[Issue]:
    groups: dict[str, list[str]] = defaultdict(list)
    for p in ctx.pages:
        if p.content_hash and p.word_count >= 20:
            groups[p.content_hash].append(p.url)
    exact = [sorted(g) for g in groups.values() if len(g) > 1]
    canon_ok = {
        p.url for p in ctx.pages if p.canonical and p.canonical.rstrip("/") != p.url.rstrip("/")
    }
    exact = [g for g in exact if len([u for u in g if u not in canon_ok]) > 1]
    if exact:
        yield Issue(
            "duplicate-content",
            f"{len(exact)} group(s) of exact-duplicate pages",
            Severity.HIGH,
            C,
            "Different URLs serve identical main content without canonicalizing to one version.",
            "Pick one URL per group; 301-redirect the others or add rel=canonical pointing to it.",
            impact="Search engines split signals across duplicates and may index the wrong URL.",
            urls=[u for g in exact for u in g],
            evidence={"groups": exact},
            source=sources.CANONICAL,
        )
    near: list[list[str]] = []
    pages = [p for p in ctx.pages if p.word_count >= 100 and p.simhash]
    used: set[str] = {u for g in exact for u in g}
    for i, a in enumerate(pages):
        if a.url in used:
            continue
        group = [a.url]
        for b in pages[i + 1 :]:
            if b.url not in used and hamming(a.simhash, b.simhash) <= 3:
                group.append(b.url)
                used.add(b.url)
        if len(group) > 1:
            used.add(a.url)
            near.append(group)
    if near:
        yield Issue(
            "near-duplicate-content",
            f"{len(near)} group(s) of near-duplicate pages",
            Severity.MEDIUM,
            C,
            "These pages share almost all of their text (SimHash distance <= 3 of 64 bits).",
            "Merge thin variants, differentiate their content, or canonicalize to the best one.",
            effort=Effort.MEDIUM,
            urls=[u for g in near for u in g],
            evidence={"groups": near},
            source=sources.CANONICAL,
            estimate=True,
        )


@check("soft-404", C)
def soft_404(ctx: AuditContext) -> Iterator[Issue]:
    probe = ctx.crawl.probes.get("missing_page")
    if probe is not None and probe.status == 200:
        yield Issue(
            "soft-404-sitewide",
            "Non-existent URLs return HTTP 200 (soft 404)",
            Severity.HIGH,
            C,
            f"A request for a random non-existent URL ({probe.url}) returned 200 instead of 404.",
            "Configure the server/framework to return a real 404 (or 410) status for missing "
            "pages while still showing a helpful error page.",
            impact="Search engines may index error pages and waste crawl budget on infinite URLs.",
            urls=[probe.url],
            source=sources.SOFT_404,
        )
    suspects = sorted(
        p.url
        for p in ctx.pages
        if (p.title and SOFT_404_TITLE.search(p.title))
        or any(SOFT_404_TITLE.search(h) for h in p.h1s)
    )
    if suspects:
        yield Issue(
            "soft-404-pages",
            f"{len(suspects)} page(s) look like error pages but return 200",
            Severity.MEDIUM,
            C,
            "The title or H1 suggests 'not found', yet the HTTP status is 200 (heuristic).",
            "Return 404/410 for missing content, or fix the page content if it is real.",
            urls=suspects,
            source=sources.SOFT_404,
            estimate=True,
        )


@check("broken-external-links", C)
def broken_external(ctx: AuditContext) -> Iterator[Issue]:
    bad = {
        u: s
        for u, s in ctx.crawl.external_status.items()
        if s >= 400 and s not in (401, 403, 429, 999)
    }
    if bad:
        sources_map = {
            u: sorted(p.url for p in ctx.pages if any(link.url == u for link in p.external_links))[
                :10
            ]
            for u in bad
        }
        yield Issue(
            "broken-external-links",
            f"{len(bad)} outbound link(s) are broken",
            Severity.LOW,
            C,
            "Outbound links return 4xx/5xx (401/403/429 are excluded since sites often block bots).",
            "Replace dead links with a live source or an archived copy (web.archive.org).",
            urls=sorted(bad),
            evidence={u: {"status": s, "linked_from": sources_map[u]} for u, s in bad.items()},
            source=sources.LINKS,
        )


@check("robots-blocked-urls", C)
def robots_blocked(ctx: AuditContext) -> Iterator[Issue]:
    in_sitemap = set(ctx.crawl.sitemaps.urls)
    blocked_in_sitemap = sorted(u for u in ctx.crawl.blocked if u in in_sitemap)
    if blocked_in_sitemap:
        yield Issue(
            "sitemap-urls-blocked",
            f"{len(blocked_in_sitemap)} sitemap URL(s) are blocked by robots.txt",
            Severity.HIGH,
            C,
            "Your sitemap asks engines to crawl URLs that robots.txt forbids - a contradiction.",
            "Either allow these paths in robots.txt or remove them from the sitemap.",
            urls=blocked_in_sitemap,
            source=sources.SITEMAPS,
        )
