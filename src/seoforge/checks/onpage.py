"""On-page checks: titles, meta descriptions, headings, content depth, anchors, social tags."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator

from seoforge import sources
from seoforge.checks.base import AuditContext, check
from seoforge.models import Category, Effort, Issue, PageData, Severity

OP = Category.ONPAGE
SPA_ROOT = re.compile(r'id=["\'](root|app|__next|__nuxt|svelte|main-app)["\']', re.I)
GENERIC_ANCHORS = {
    "click here",
    "here",
    "read more",
    "more",
    "learn more",
    "this",
    "link",
    "this page",
    "continue",
    "details",
    "go",
    "click",
}


def _dupes(pages: list[PageData], key: str) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for p in pages:
        value = getattr(p, key)
        if value:
            groups[value.strip().lower()].append(p.url)
    return {k: sorted(v) for k, v in groups.items() if len(v) > 1}


@check("titles", OP)
def titles(ctx: AuditContext) -> Iterator[Issue]:
    pages = [p for p in ctx.pages if p.is_indexable]
    missing = sorted(p.url for p in pages if not p.title)
    if missing:
        yield Issue(
            "title-missing",
            f"{len(missing)} page(s) have no <title>",
            Severity.HIGH,
            OP,
            "The title is the main input for the search result headline and a key relevance signal.",
            "Write a unique, descriptive title (roughly 30-60 characters) leading with the page topic.",
            urls=missing,
            source=sources.TITLE,
        )
    long = {p.url: len(p.title) for p in pages if p.title and len(p.title) > 60}
    if long:
        yield Issue(
            "title-too-long",
            f"{len(long)} title(s) longer than ~60 characters",
            Severity.LOW,
            OP,
            "Google truncates titles by pixel width (~600px); beyond ~60 characters truncation is "
            "likely. This is a heuristic, not a rule.",
            "Front-load the important words; trim brand suffixes or filler.",
            urls=sorted(long),
            evidence=long,
            source=sources.TITLE,
            estimate=True,
        )
    short = {p.url: p.title for p in pages if p.title and len(p.title) < 15}
    if short:
        yield Issue(
            "title-too-short",
            f"{len(short)} title(s) shorter than 15 characters",
            Severity.LOW,
            OP,
            "Very short titles waste the most visible slot in search results.",
            "Describe the page's specific topic and value in the title.",
            urls=sorted(short),
            evidence=short,
            source=sources.TITLE,
        )
    dupes = _dupes(pages, "title")
    if dupes:
        yield Issue(
            "title-duplicate",
            f"{len(dupes)} title(s) are shared by multiple pages",
            Severity.MEDIUM,
            OP,
            "Duplicate titles make pages hard to tell apart and can signal duplicate content.",
            "Give every indexable page a unique title reflecting its unique content.",
            urls=[u for g in dupes.values() for u in g],
            evidence=dupes,
            source=sources.TITLE,
        )
    multi = sorted(p.url for p in pages if p.titles_count > 1)
    if multi:
        yield Issue(
            "title-multiple",
            f"{len(multi)} page(s) have more than one <title>",
            Severity.LOW,
            OP,
            "Multiple title elements are invalid HTML; engines pick one unpredictably.",
            "Keep exactly one <title> inside <head>.",
            urls=multi,
            source=sources.TITLE,
        )


@check("meta-descriptions", OP)
def meta_descriptions(ctx: AuditContext) -> Iterator[Issue]:
    pages = [p for p in ctx.pages if p.is_indexable]
    missing = sorted(p.url for p in pages if not p.meta_description)
    if missing:
        yield Issue(
            "meta-description-missing",
            f"{len(missing)} page(s) lack a meta description",
            Severity.LOW,
            OP,
            "Search engines often use the meta description as the result snippet; without one "
            "they pick text from the page.",
            "Write a unique 1-2 sentence summary (roughly 70-160 characters) per page.",
            urls=missing,
            source=sources.SNIPPET,
        )
    long = {
        p.url: len(p.meta_description)
        for p in pages
        if p.meta_description and len(p.meta_description) > 160
    }
    if long:
        yield Issue(
            "meta-description-long",
            f"{len(long)} meta description(s) longer than ~160 characters",
            Severity.LOW,
            OP,
            "Long descriptions are usually truncated in results (heuristic).",
            "Put the key message in the first ~150 characters.",
            urls=sorted(long),
            evidence=long,
            source=sources.SNIPPET,
            estimate=True,
        )
    dupes = _dupes(pages, "meta_description")
    if dupes:
        yield Issue(
            "meta-description-duplicate",
            f"{len(dupes)} meta description(s) reused across pages",
            Severity.LOW,
            OP,
            "Boilerplate descriptions get replaced by engines and help no page.",
            "Write page-specific descriptions or omit them on low-value pages.",
            urls=[u for g in dupes.values() for u in g],
            evidence=dupes,
            source=sources.SNIPPET,
        )


@check("headings", OP)
def headings(ctx: AuditContext) -> Iterator[Issue]:
    pages = [p for p in ctx.pages if p.is_indexable]
    no_h1 = sorted(p.url for p in pages if not p.h1s)
    if no_h1:
        yield Issue(
            "h1-missing",
            f"{len(no_h1)} page(s) have no H1",
            Severity.MEDIUM,
            OP,
            "A clear main heading tells users and engines what the page is about.",
            "Add one descriptive <h1> matching the page's main topic.",
            urls=no_h1,
            source=sources.STARTER_GUIDE,
        )
    multi = {p.url: p.h1s for p in pages if len(p.h1s) > 1}
    if multi:
        yield Issue(
            "h1-multiple",
            f"{len(multi)} page(s) have multiple H1s",
            Severity.LOW,
            OP,
            "Multiple H1s are valid HTML5 and not penalized, but a single clear H1 makes the "
            "page topic unambiguous for snippet and answer extraction.",
            "Use one H1 for the page topic and H2/H3 for sections.",
            urls=sorted(multi),
            evidence=multi,
            source=sources.STARTER_GUIDE,
        )
    skipped: dict[str, str] = {}
    for p in pages:
        last = 0
        for h in p.headings:
            if last and h.level > last + 1:
                skipped[p.url] = f"H{last} -> H{h.level} ('{h.text[:60]}')"
                break
            last = h.level
    if skipped:
        yield Issue(
            "heading-skip",
            f"{len(skipped)} page(s) skip heading levels",
            Severity.LOW,
            OP,
            "Skipped levels (e.g. H2 -> H4) weaken the document outline used by assistive tech "
            "and passage extraction.",
            "Nest headings sequentially (H1 > H2 > H3).",
            urls=sorted(skipped),
            evidence=skipped,
            source=sources.STARTER_GUIDE,
        )
    empty = sorted(p.url for p in pages if any(not h.text for h in p.headings))
    if empty:
        yield Issue(
            "heading-empty",
            f"{len(empty)} page(s) contain empty headings",
            Severity.LOW,
            OP,
            "Empty heading tags add noise to the outline.",
            "Remove empty heading elements or give them text.",
            urls=empty,
            source=sources.STARTER_GUIDE,
        )


@check("content-depth", OP)
def content_depth(ctx: AuditContext) -> Iterator[Issue]:
    thin = {
        p.url: p.word_count
        for p in ctx.pages
        if p.is_indexable and p.word_count < 200 and p.url != ctx.crawl.start_url
    }
    if thin:
        yield Issue(
            "thin-content",
            f"{len(thin)} indexable page(s) have under 200 words of main content",
            Severity.MEDIUM,
            OP,
            "There is no minimum word count in Google's guidelines; this flags pages that may not "
            "satisfy the searcher. Judge each one by usefulness, not length.",
            "Expand pages that should rank with substantive, original information - or noindex/"
            "merge low-value pages.",
            effort=Effort.HIGH,
            urls=sorted(thin, key=lambda u: thin[u]),
            evidence=thin,
            source=sources.HELPFUL_CONTENT,
            estimate=True,
        )
    shells = sorted(
        p.url
        for p in ctx.pages
        if not p.rendered
        and p.word_count < 30
        and p.html.count("<script") >= 1
        and SPA_ROOT.search(p.html)
    )
    if shells:
        yield Issue(
            "js-app-shell",
            f"{len(shells)} page(s) look like empty JavaScript app shells",
            Severity.HIGH,
            OP,
            "The raw HTML has almost no text but contains an app mount point (e.g. #root, #app, "
            "#__next). Crawlers that do not run JavaScript - including most AI crawlers - see an "
            "empty page. Re-run with --render to measure the rendered content.",
            "Server-side render or pre-render these routes (Next.js/Nuxt/Astro SSR or SSG, or a "
            "prerendering service).",
            effort=Effort.HIGH,
            urls=shells,
            source=sources.JS_SEO,
            estimate=True,
        )
    js_dependent = {
        p.url: {"raw_words": p.raw_word_count, "rendered_words": p.word_count}
        for p in ctx.pages
        if p.rendered
        and p.raw_word_count is not None
        and p.word_count > 50
        and p.raw_word_count < p.word_count * 0.5
    }
    if js_dependent:
        yield Issue(
            "js-dependent-content",
            f"{len(js_dependent)} page(s) need JavaScript for most content",
            Severity.HIGH,
            OP,
            "Over half the main text appears only after JavaScript runs. Google renders JS with a "
            "delay; most AI crawlers (GPTBot, ClaudeBot, PerplexityBot...) do not execute JS at all.",
            "Server-side render or pre-render the main content (SSR/SSG).",
            effort=Effort.HIGH,
            urls=sorted(js_dependent),
            evidence=js_dependent,
            source=sources.JS_SEO,
        )


@check("anchors", OP)
def anchors(ctx: AuditContext) -> Iterator[Issue]:
    generic: dict[str, list[str]] = defaultdict(list)
    empty: dict[str, list[str]] = defaultdict(list)
    for p in ctx.pages:
        for link in p.internal_links:
            text = link.text.strip().lower()
            if not text:
                empty[p.url].append(link.url)
            elif text in GENERIC_ANCHORS:
                generic[p.url].append(f"'{link.text}' -> {link.url}")
    if generic:
        yield Issue(
            "anchor-generic",
            f"Generic anchor text on {len(generic)} page(s)",
            Severity.LOW,
            OP,
            "Anchors like 'click here' tell engines nothing about the target page.",
            "Use descriptive anchor text naming the destination's topic.",
            urls=sorted(generic),
            evidence={k: v[:5] for k, v in generic.items()},
            source=sources.LINKS,
        )
    if empty:
        yield Issue(
            "anchor-empty",
            f"Links without accessible text on {len(empty)} page(s)",
            Severity.LOW,
            OP,
            "Links with no text, aria-label or image alt give no context to crawlers or screen readers.",
            "Add text, aria-label, or alt text on linked images.",
            urls=sorted(empty),
            evidence={k: v[:5] for k, v in empty.items()},
            source=sources.LINKS,
        )


@check("internal-linking", OP)
def internal_linking(ctx: AuditContext) -> Iterator[Issue]:
    inlinks = ctx.inlinks
    weak = {
        p.url: inlinks.get(p.url, 0)
        for p in ctx.pages
        if p.is_indexable and inlinks.get(p.url, 0) == 1 and p.url != ctx.crawl.start_url
    }
    if weak:
        yield Issue(
            "weak-internal-links",
            f"{len(weak)} page(s) have only one internal link pointing to them",
            Severity.LOW,
            OP,
            "Pages with a single inbound internal link receive little internal authority.",
            "Link to them contextually from related pages.",
            effort=Effort.MEDIUM,
            urls=sorted(weak),
            source=sources.LINKS,
            estimate=True,
        )
    dead_ends = sorted(p.url for p in ctx.pages if p.is_indexable and not p.internal_links)
    if dead_ends:
        yield Issue(
            "no-outlinks",
            f"{len(dead_ends)} page(s) have no internal links",
            Severity.LOW,
            OP,
            "Dead-end pages stop crawlers and users from moving on through the site.",
            "Add navigation or contextual links to related pages.",
            urls=dead_ends,
            source=sources.LINKS,
        )


@check("social-tags", OP)
def social_tags(ctx: AuditContext) -> Iterator[Issue]:
    missing = sorted(
        p.url
        for p in ctx.pages
        if p.is_indexable and not {"og:title", "og:description", "og:image"} <= set(p.open_graph)
    )
    if missing:
        yield Issue(
            "open-graph-missing",
            f"{len(missing)} page(s) lack complete Open Graph tags",
            Severity.LOW,
            OP,
            "og:title/og:description/og:image control link previews on social apps, chat apps and "
            "some AI assistants. Not a ranking factor.",
            "Add og:title, og:description, og:image and og:url (`seoforge fix` generates them).",
            urls=missing,
            source=sources.OPEN_GRAPH,
        )
