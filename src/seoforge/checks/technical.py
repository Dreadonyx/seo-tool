"""Technical SEO checks: HTTPS, robots.txt, sitemaps, canonicals, indexability, hreflang, mobile,
images, response time and security headers."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator
from urllib.parse import urlsplit

from seoforge import sources
from seoforge.checks.base import AuditContext, check
from seoforge.models import Category, Effort, Issue, PageData, Severity
from seoforge.urls import same_site

T = Category.TECHNICAL
S = Category.SECURITY
HREFLANG_RE = re.compile(r"^(x-default|[a-z]{2,3}(-[A-Za-z]{4})?(-([A-Za-z]{2}|\d{3}))?)$", re.I)


def _norm(url: str) -> str:
    return url.rstrip("/")


# ---- HTTPS ------------------------------------------------------------------------------------
@check("https", S)
def https_checks(ctx: AuditContext) -> Iterator[Issue]:
    if ctx.site.startswith("http://"):
        yield Issue(
            "no-https",
            "Site is served over plain HTTP",
            Severity.CRITICAL,
            S,
            "The site does not redirect to HTTPS. Browsers mark HTTP pages 'Not secure' and "
            "Google uses HTTPS as a page experience signal.",
            "Install a free TLS certificate (Let's Encrypt / your host / Cloudflare) and "
            "301-redirect all HTTP URLs to HTTPS.",
            effort=Effort.MEDIUM,
            urls=[ctx.site],
            source=sources.PAGE_EXPERIENCE,
        )
        return
    probe = ctx.crawl.probes.get("http_home")
    if probe is not None and probe.error is None and not probe.final_url.startswith("https://"):
        yield Issue(
            "http-not-redirected",
            "HTTP version of the site does not redirect to HTTPS",
            Severity.HIGH,
            S,
            f"{probe.url} returned {probe.status} without redirecting to HTTPS.",
            "Add a site-wide 301 redirect from http:// to https:// (see `seoforge fix`).",
            urls=[probe.url],
            source=sources.REDIRECTS,
        )
    home = ctx.crawl.pages.get(ctx.crawl.start_url)
    if home is not None and "strict-transport-security" not in home.headers:
        yield Issue(
            "missing-hsts",
            "No Strict-Transport-Security (HSTS) header",
            Severity.LOW,
            S,
            "Without HSTS, a first visit over HTTP can be downgraded or intercepted.",
            "Send `Strict-Transport-Security: max-age=31536000; includeSubDomains` once HTTPS "
            "works everywhere (add `preload` only after reading hstspreload.org).",
            urls=[home.url],
            source=sources.HSTS,
        )
    mixed = {p.url: p.mixed_content[:10] for p in ctx.pages if p.mixed_content}
    if mixed:
        yield Issue(
            "mixed-content",
            f"{len(mixed)} HTTPS page(s) load HTTP sub-resources",
            Severity.MEDIUM,
            S,
            "Browsers block or warn on insecure scripts, styles, images or iframes on HTTPS pages.",
            "Change sub-resource URLs to https:// (or protocol-relative to the same host).",
            urls=sorted(mixed),
            evidence=mixed,
            source=sources.MIXED_CONTENT,
        )


@check("host-consistency", T)
def host_consistency(ctx: AuditContext) -> Iterator[Issue]:
    probe = ctx.crawl.probes.get("alt_host_home")
    if probe is None or probe.error is not None or probe.status == 0:
        return
    if probe.status == 200 and urlsplit(probe.final_url).netloc != urlsplit(ctx.site).netloc:
        yield Issue(
            "www-not-canonicalized",
            "Both www and non-www hosts serve content",
            Severity.MEDIUM,
            T,
            f"{probe.url} returns 200 without redirecting to {ctx.site}.",
            "301-redirect the alternate host to your preferred host (see `seoforge fix`).",
            urls=[probe.url],
            source=sources.CANONICAL,
        )


# ---- robots.txt -------------------------------------------------------------------------------
@check("robots-txt", T)
def robots_txt(ctx: AuditContext) -> Iterator[Issue]:
    robots = ctx.crawl.robots
    url = robots.url or f"{ctx.site}/robots.txt"
    if robots.unreachable:
        yield Issue(
            "robots-unreachable",
            "robots.txt is unreachable (5xx or network error)",
            Severity.CRITICAL,
            T,
            "Per RFC 9309, crawlers treat an unreachable robots.txt as 'disallow everything'. "
            "Google may stop crawling the site after prolonged errors.",
            "Make /robots.txt return 200 (or 404 if you have no rules).",
            urls=[url],
            source=sources.ROBOTS_RFC,
        )
        return
    if robots.missing:
        yield Issue(
            "robots-missing",
            "No robots.txt file",
            Severity.LOW,
            T,
            "A missing robots.txt allows all crawling, which is fine, but you lose the place to "
            "declare your sitemap and AI-crawler preferences.",
            "Create /robots.txt with a Sitemap: line (`seoforge fix` generates one).",
            urls=[url],
            source=sources.ROBOTS_TXT,
        )
        return
    for agent in ("Googlebot", "Bingbot"):
        if robots.blocks_everything(agent):
            yield Issue(
                f"robots-blocks-{agent.lower()}",
                f"robots.txt blocks {agent} from the whole site",
                Severity.CRITICAL,
                T,
                f"Rules applying to {agent} disallow '/', so the site cannot be crawled.",
                "Remove `Disallow: /` from the group matching this crawler (common leftover "
                "from staging sites).",
                urls=[url],
                source=sources.ROBOTS_TXT,
            )
    if robots.warnings:
        yield Issue(
            "robots-syntax",
            f"robots.txt has {len(robots.warnings)} syntax warning(s)",
            Severity.LOW,
            T,
            "Invalid or unsupported lines are ignored by crawlers and may not do what you expect.",
            "Fix or remove the listed lines.",
            urls=[url],
            evidence={"warnings": [f"line {w.line}: {w.message}" for w in robots.warnings]},
            source=sources.ROBOTS_RFC,
        )
    if not robots.sitemaps:
        yield Issue(
            "robots-no-sitemap",
            "robots.txt does not reference a sitemap",
            Severity.LOW,
            T,
            "A Sitemap: line lets every crawler (including ones without a webmaster console) "
            "find your sitemap.",
            f"Add `Sitemap: {ctx.site}/sitemap.xml` to robots.txt.",
            urls=[url],
            source=sources.SITEMAPS,
        )
    # Resources needed for rendering should not be blocked.
    blocked_assets = sorted(
        {
            img.src
            for p in ctx.pages
            for img in p.images
            if img.src.startswith("http")
            and same_site(img.src, ctx.site)
            and not robots.can_fetch("Googlebot", img.src)
        }
    )[:20]
    if blocked_assets:
        yield Issue(
            "robots-blocks-resources",
            "robots.txt blocks images used on your pages",
            Severity.MEDIUM,
            T,
            "Blocked images cannot be indexed in image search or used for rendering.",
            "Allow the image directories in robots.txt unless you deliberately hide them.",
            urls=blocked_assets,
            source=sources.JS_SEO,
        )


# ---- Sitemaps ---------------------------------------------------------------------------------
@check("sitemaps", T)
def sitemap_checks(ctx: AuditContext) -> Iterator[Issue]:
    report = ctx.crawl.sitemaps
    if not report.sitemaps or not report.found:
        yield Issue(
            "sitemap-missing",
            "No valid XML sitemap found",
            Severity.MEDIUM,
            T,
            "No sitemap was found via robots.txt or /sitemap.xml (or it failed to parse).",
            "Generate one with `seoforge fix` and reference it in robots.txt; submit it in "
            "Google Search Console and Bing Webmaster Tools.",
            urls=[s.url for s in report.sitemaps] or [f"{ctx.site}/sitemap.xml"],
            evidence={s.url: s.errors for s in report.sitemaps},
            source=sources.SITEMAPS,
        )
    errors = {s.url: s.errors for s in report.sitemaps if s.errors and s.status == 200}
    if errors:
        yield Issue(
            "sitemap-errors",
            f"{len(errors)} sitemap file(s) have errors",
            Severity.MEDIUM,
            T,
            "Search engines may ignore malformed sitemaps or parts of them.",
            "Fix the listed problems; validate against the sitemaps.org protocol.",
            urls=sorted(errors),
            evidence=errors,
            source=sources.SITEMAP_PROTOCOL,
        )
    smap = report.urls
    if not smap:
        return
    pages = ctx.crawl.pages
    bad_status, redirected, noindexed, non_canonical, off_site = [], [], [], [], []
    for url in smap:
        if not same_site(url, ctx.site):
            off_site.append(url)
            continue
        page = pages.get(url) or pages.get(url.rstrip("/")) or pages.get(url + "/")
        if page is None:
            continue
        if page.redirect_chain:
            redirected.append(url)
        elif page.status != 200:
            bad_status.append(url)
        elif page.noindex:
            noindexed.append(url)
        elif page.canonical and _norm(page.canonical) != _norm(page.final_url):
            non_canonical.append(url)
    rows = [
        ("sitemap-non-200", bad_status, Severity.HIGH, "return 4xx/5xx"),
        ("sitemap-redirects", redirected, Severity.MEDIUM, "redirect"),
        ("sitemap-noindex", noindexed, Severity.HIGH, "are marked noindex"),
        ("sitemap-non-canonical", non_canonical, Severity.MEDIUM, "canonicalize to another URL"),
        ("sitemap-off-site", off_site, Severity.MEDIUM, "belong to another host"),
    ]
    for cid, urls, sev, what in rows:
        if urls:
            yield Issue(
                cid,
                f"{len(urls)} sitemap URL(s) {what}",
                sev,
                T,
                "Sitemaps should only list canonical, indexable URLs that return 200. Mixed "
                "signals reduce how much engines trust the sitemap.",
                "Regenerate the sitemap from indexable canonical URLs (`seoforge fix`).",
                urls=sorted(urls),
                source=sources.SITEMAPS,
            )
    crawled_indexable = {p.url for p in ctx.pages if p.is_indexable}
    missing = sorted(u for u in crawled_indexable if u not in smap and u.rstrip("/") not in smap)
    if missing and report.found:
        yield Issue(
            "not-in-sitemap",
            f"{len(missing)} indexable page(s) are missing from the sitemap",
            Severity.LOW,
            T,
            "Pages reachable by links but absent from the sitemap may be discovered more slowly.",
            "Regenerate the sitemap so it includes every indexable canonical URL.",
            urls=missing,
            source=sources.SITEMAPS,
        )


# ---- Canonicals & indexability ----------------------------------------------------------------
@check("canonicals", T)
def canonical_checks(ctx: AuditContext) -> Iterator[Issue]:
    pages = ctx.crawl.pages
    missing, multiple, broken, to_redirect, to_noindex, cross = [], [], {}, [], [], []
    for p in ctx.pages:
        if p.canonical is None:
            if not p.noindex:
                missing.append(p.url)
            continue
        if p.canonicals_count > 1:
            multiple.append(p.url)
        target = pages.get(p.canonical) or pages.get(p.canonical.rstrip("/"))
        if not same_site(p.canonical, ctx.site):
            cross.append(p.url)
        elif target is not None:
            if target.redirect_chain:
                to_redirect.append(p.url)
            elif target.status != 200:
                broken[p.url] = f"{p.canonical} -> {target.status}"
            elif target.noindex:
                to_noindex.append(p.url)
    if missing:
        yield Issue(
            "canonical-missing",
            f"{len(missing)} page(s) have no rel=canonical",
            Severity.LOW,
            T,
            "A self-referencing canonical helps consolidate URL variants (tracking parameters, "
            "trailing slashes, http/https).",
            'Add `<link rel="canonical" href="https://...this-page">` to each page.',
            urls=missing,
            source=sources.CANONICAL,
        )
    if multiple:
        yield Issue(
            "canonical-multiple",
            f"{len(multiple)} page(s) declare multiple canonicals",
            Severity.HIGH,
            T,
            "When several canonicals conflict, Google ignores all of them.",
            "Keep exactly one rel=canonical per page (check CMS + SEO plugin duplicates).",
            urls=multiple,
            source=sources.CANONICAL,
        )
    if broken:
        yield Issue(
            "canonical-broken",
            f"{len(broken)} canonical(s) point to error pages",
            Severity.HIGH,
            T,
            "The canonical target does not return 200.",
            "Point canonicals at live, indexable URLs.",
            urls=sorted(broken),
            evidence=broken,
            source=sources.CANONICAL,
        )
    if to_redirect:
        yield Issue(
            "canonical-to-redirect",
            f"{len(to_redirect)} canonical(s) point to redirecting URLs",
            Severity.MEDIUM,
            T,
            "Canonicals should reference the final URL, not one that redirects.",
            "Update the canonical href to the redirect destination.",
            urls=to_redirect,
            source=sources.CANONICAL,
        )
    if to_noindex:
        yield Issue(
            "canonical-to-noindex",
            f"{len(to_noindex)} canonical(s) point to noindex pages",
            Severity.HIGH,
            T,
            "Canonicalizing to a noindex page sends contradictory signals.",
            "Point the canonical to an indexable page or remove noindex from the target.",
            urls=to_noindex,
            source=sources.CANONICAL,
        )
    if cross:
        yield Issue(
            "canonical-cross-domain",
            f"{len(cross)} page(s) canonicalize to another domain",
            Severity.MEDIUM,
            T,
            "Cross-domain canonicals are valid for syndicated content but a common misconfiguration "
            "after migrations or staging copies.",
            "Confirm each is intentional; otherwise make the canonical self-referencing.",
            urls=cross,
            evidence={p.url: p.canonical for p in ctx.pages if p.url in cross},
            source=sources.CANONICAL,
        )


@check("indexability", T)
def indexability(ctx: AuditContext) -> Iterator[Issue]:
    noindex = sorted(p.url for p in ctx.pages if p.noindex)
    if noindex:
        home_blocked = ctx.crawl.start_url in noindex
        yield Issue(
            "noindex-pages",
            f"{len(noindex)} page(s) are excluded with noindex",
            Severity.CRITICAL if home_blocked else Severity.INFO,
            T,
            "These pages carry a noindex directive (meta robots or X-Robots-Tag). This is correct "
            "for thank-you pages, internal search, etc., but fatal on pages you want to rank.",
            "Review the list; remove noindex from any page that should appear in search.",
            urls=noindex,
            evidence={
                p.url: {"meta": p.meta_robots, "x-robots-tag": p.x_robots_tag}
                for p in ctx.pages
                if p.noindex
            },
            source=sources.NOINDEX,
        )
    nosnippet = sorted(p.url for p in ctx.pages if "nosnippet" in p.robots_directives)
    if nosnippet:
        yield Issue(
            "nosnippet",
            f"{len(nosnippet)} page(s) use nosnippet",
            Severity.MEDIUM,
            T,
            "nosnippet prevents text snippets and can exclude content from AI Overviews / "
            "featured snippets.",
            "Remove nosnippet unless you intentionally restrict snippets "
            "(use data-nosnippet on specific elements instead).",
            urls=nosnippet,
            source=sources.ROBOTS_META,
        )


# ---- hreflang ---------------------------------------------------------------------------------
@check("hreflang", T)
def hreflang_checks(ctx: AuditContext) -> Iterator[Issue]:
    pages = {p.url: p for p in ctx.pages}
    invalid: dict[str, list[str]] = defaultdict(list)
    no_return: dict[str, list[str]] = defaultdict(list)
    no_self: list[str] = []
    for p in ctx.pages:
        if not p.hreflangs:
            continue
        for h in p.hreflangs:
            if not HREFLANG_RE.match(h.lang):
                invalid[p.url].append(h.lang)
            target = pages.get(h.url)
            if (
                target is not None
                and target.url != p.url
                and not any(_norm(r.url) == _norm(p.url) for r in target.hreflangs)
            ):
                no_return[p.url].append(h.url)
        if not any(_norm(h.url) == _norm(p.url) for h in p.hreflangs):
            no_self.append(p.url)
    if invalid:
        yield Issue(
            "hreflang-invalid",
            f"{len(invalid)} page(s) use invalid hreflang codes",
            Severity.HIGH,
            T,
            "hreflang values must be ISO 639-1 language (+ optional ISO 3166-1 region) or x-default.",
            "Fix codes, e.g. 'en-GB' not 'en-UK', 'es-419' for Latin America.",
            urls=sorted(invalid),
            evidence=dict(invalid),
            source=sources.HREFLANG,
        )
    if no_return:
        yield Issue(
            "hreflang-no-return",
            f"{len(no_return)} page(s) have hreflang without return links",
            Severity.MEDIUM,
            T,
            "Alternate pages must link back to each other; one-way hreflang annotations are ignored.",
            "Add reciprocal hreflang tags on every alternate page.",
            urls=sorted(no_return),
            evidence=dict(no_return),
            source=sources.HREFLANG,
        )
    if no_self:
        yield Issue(
            "hreflang-no-self",
            f"{len(no_self)} page(s) lack a self-referencing hreflang",
            Severity.LOW,
            T,
            "Each page in an hreflang set should list itself.",
            "Add an hreflang entry for the page's own language/URL.",
            urls=no_self,
            source=sources.HREFLANG,
        )


# ---- Mobile & HTML basics --------------------------------------------------------------------
@check("mobile-html", T)
def mobile_html(ctx: AuditContext) -> Iterator[Issue]:
    no_viewport = sorted(p.url for p in ctx.pages if not p.viewport)
    if no_viewport:
        yield Issue(
            "missing-viewport",
            f"{len(no_viewport)} page(s) lack a viewport meta tag",
            Severity.HIGH,
            T,
            "Without a viewport tag, mobile browsers render a zoomed-out desktop layout. Google "
            "indexes the mobile version of pages.",
            'Add `<meta name="viewport" content="width=device-width, initial-scale=1">`.',
            urls=no_viewport,
            source=sources.MOBILE_FIRST,
        )
    zoom_blocked = sorted(
        p.url
        for p in ctx.pages
        if p.viewport
        and (
            "user-scalable=no" in p.viewport.replace(" ", "")
            or "maximum-scale=1" in p.viewport.replace(" ", "")
        )
    )
    if zoom_blocked:
        yield Issue(
            "viewport-zoom-disabled",
            f"{len(zoom_blocked)} page(s) disable pinch-zoom",
            Severity.LOW,
            T,
            "Disabling zoom is an accessibility failure (WCAG 1.4.4).",
            "Remove user-scalable=no / maximum-scale=1 from the viewport tag.",
            urls=zoom_blocked,
            source=sources.VIEWPORT,
        )
    no_lang = sorted(p.url for p in ctx.pages if not p.lang)
    if no_lang:
        yield Issue(
            "missing-lang",
            f"{len(no_lang)} page(s) lack <html lang>",
            Severity.LOW,
            T,
            "The lang attribute helps screen readers, translation and language detection.",
            'Add `<html lang="en">` (or the correct language code).',
            urls=no_lang,
            source=sources.LANG_ATTR,
        )


@check("images", T)
def image_checks(ctx: AuditContext) -> Iterator[Issue]:
    missing_alt: dict[str, list[str]] = {}
    no_dims: dict[str, int] = {}
    for p in ctx.pages:
        alts = [img.src for img in p.images if img.alt is None]
        if alts:
            missing_alt[p.url] = alts[:10]
        dims = sum(1 for img in p.images if not (img.width and img.height))
        if dims:
            no_dims[p.url] = dims
    if missing_alt:
        total = sum(len(v) for v in missing_alt.values())
        yield Issue(
            "img-missing-alt",
            f"{total}+ image(s) on {len(missing_alt)} page(s) lack alt text",
            Severity.MEDIUM,
            T,
            "Alt text is how search engines (and AI crawlers) understand images, and it is "
            'required for accessibility. Decorative images should use alt="".',
            'Write a short, descriptive alt for informative images; alt="" for decorative ones.',
            urls=sorted(missing_alt),
            evidence=missing_alt,
            source=sources.IMAGES,
        )
    if no_dims:
        yield Issue(
            "img-no-dimensions",
            f"Images without width/height on {len(no_dims)} page(s)",
            Severity.LOW,
            Category.PERFORMANCE,
            "Images without explicit dimensions cause layout shift (CLS) while loading.",
            "Add width and height attributes (or CSS aspect-ratio) to every <img>.",
            urls=sorted(no_dims),
            evidence=no_dims,
            source=sources.CORE_WEB_VITALS,
        )


@check("response-time", Category.PERFORMANCE)
def response_time(ctx: AuditContext) -> Iterator[Issue]:
    slow = {p.url: round(p.elapsed_ms) for p in ctx.pages if p.elapsed_ms > 800}
    if slow:
        yield Issue(
            "slow-response",
            f"{len(slow)} page(s) took over 800 ms to download",
            Severity.MEDIUM,
            Category.PERFORMANCE,
            "Measured from this crawler's location - a rough proxy for server response time. "
            "web.dev recommends a TTFB of 0.8 s or less.",
            "Add caching (CDN / full-page cache), optimize database queries, enable compression.",
            effort=Effort.MEDIUM,
            urls=sorted(slow, key=lambda u: -slow[u]),
            evidence=slow,
            source="https://web.dev/articles/ttfb",
            estimate=True,
        )
    heavy = {p.url: p.size_bytes for p in ctx.pages if p.size_bytes > 2_000_000}
    if heavy:
        yield Issue(
            "large-html",
            f"{len(heavy)} HTML document(s) exceed 2 MB",
            Severity.MEDIUM,
            Category.PERFORMANCE,
            "Very large HTML slows parsing; Googlebot only processes the first 15 MB of a file.",
            "Remove inlined data/images and paginate very long pages.",
            urls=sorted(heavy),
            evidence=heavy,
            source=sources.HTTP_ERRORS,
        )
    uncompressed = sorted(
        p.url for p in ctx.pages if p.size_bytes > 10_000 and not p.headers.get("content-encoding")
    )
    if uncompressed:
        yield Issue(
            "no-compression",
            f"{len(uncompressed)} page(s) served without compression",
            Severity.LOW,
            Category.PERFORMANCE,
            "HTML is served without gzip/brotli Content-Encoding.",
            "Enable gzip or brotli compression on the server or CDN.",
            urls=uncompressed,
            source="https://web.dev/articles/reduce-network-payloads-using-text-compression",
        )


SECURITY_HEADERS = {
    "content-security-policy": "Mitigates XSS and data injection.",
    "x-content-type-options": "Stops MIME sniffing (`nosniff`).",
    "referrer-policy": "Controls referrer leakage (e.g. `strict-origin-when-cross-origin`).",
    "permissions-policy": "Restricts powerful browser features.",
}


@check("security-headers", S)
def security_headers(ctx: AuditContext) -> Iterator[Issue]:
    home: PageData | None = ctx.crawl.pages.get(ctx.crawl.start_url)
    if home is None or home.status != 200:
        return
    missing = {h: why for h, why in SECURITY_HEADERS.items() if h not in home.headers}
    csp = home.headers.get("content-security-policy", "")
    if "x-frame-options" not in home.headers and "frame-ancestors" not in csp:
        missing["x-frame-options / frame-ancestors"] = "Prevents clickjacking."
    if missing:
        yield Issue(
            "security-headers",
            f"{len(missing)} recommended security header(s) missing",
            Severity.LOW,
            S,
            "Security headers do not directly affect rankings but protect users and site "
            "reputation (hacked sites get flagged in search results).",
            "Add the headers at the server/CDN level (`seoforge fix` emits snippets).",
            urls=[home.url],
            evidence=missing,
            source=sources.OWASP_HEADERS,
        )
