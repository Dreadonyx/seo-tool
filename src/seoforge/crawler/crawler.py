"""Async, robots-aware, resumable site crawler."""

from __future__ import annotations

import asyncio
import dataclasses
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from seoforge.config import CrawlConfig
from seoforge.crawler.parser import parse_html
from seoforge.crawler.renderer import Renderer, RendererUnavailable
from seoforge.crawler.sitemaps import SitemapReport, discover_sitemaps
from seoforge.http import FetchResult, PoliteClient, RobotsDisallowed, origin
from seoforge.models import PageData
from seoforge.robots import RobotsTxt
from seoforge.storage import Store
from seoforge.urls import is_asset, normalize, same_site

ProgressFn = Callable[[int, int, str], None]


@dataclass(slots=True)
class SiteProbe:
    url: str
    status: int
    final_url: str
    error: str | None = None


@dataclass(slots=True)
class CrawlResult:
    site: str
    start_url: str
    pages: dict[str, PageData] = field(default_factory=dict)
    robots: RobotsTxt = field(default_factory=RobotsTxt)
    sitemaps: SitemapReport = field(default_factory=SitemapReport)
    edges: dict[str, set[str]] = field(default_factory=dict)  # internal link graph
    blocked: list[str] = field(default_factory=list)  # disallowed by robots.txt
    excluded: list[str] = field(default_factory=list)
    external_status: dict[str, int] = field(default_factory=dict)
    probes: dict[str, SiteProbe] = field(default_factory=dict)
    render_error: str | None = None
    resumed: bool = False
    truncated: bool = False  # hit max_pages

    @property
    def html_pages(self) -> list[PageData]:
        return [
            p
            for p in self.pages.values()
            if p.is_html and p.status == 200 and not p.redirect_chain and not p.error
        ]


class Crawler:
    def __init__(
        self,
        config: CrawlConfig,
        store: Store,
        *,
        client: PoliteClient | None = None,
        progress: ProgressFn | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self._client = client
        self.progress = progress
        self._include = [re.compile(p) for p in config.include]
        self._exclude = [re.compile(p) for p in config.exclude]

    def _in_scope(self, url: str) -> bool:
        if self._include and not any(p.search(url) for p in self._include):
            return False
        return not any(p.search(url) for p in self._exclude)

    async def crawl(
        self, start_url: str, *, resume: bool = False, cached: bool = False
    ) -> CrawlResult:
        start = normalize(start_url)
        if start is None:
            raise ValueError(f"Not an http(s) URL: {start_url}")
        own_client = self._client is None
        client = self._client or PoliteClient(self.config, self.store, read_cache=resume or cached)
        try:
            return await self._crawl(client, start, resume)
        finally:
            if own_client:
                await client.aclose()

    async def _crawl(self, client: PoliteClient, start: str, resume: bool) -> CrawlResult:
        # Resolve the canonical origin (e.g. http -> https, apex -> www) from the start URL.
        first = await client.fetch(start, check_robots=False)
        if first.error is None and same_site(first.final_url, start):
            start = first.final_url
        site = origin(start)
        result = CrawlResult(site=site, start_url=start)
        result.robots = await client.robots(site)
        await self._probe_site(client, result)
        if self.config.use_sitemaps:
            result.sitemaps = await discover_sitemaps(client, site)

        run_id, result.resumed = self.store.open_run(site, resume)
        self.store.enqueue(run_id, start, 0, None)
        if self.config.use_sitemaps:
            for url in result.sitemaps.urls:
                loc = normalize(url)
                if loc and same_site(loc, site):
                    # Depth here only bounds the crawl; click depth is computed from the graph.
                    self.store.enqueue(run_id, loc, 1, None)

        renderer: Renderer | None = None
        if self.config.render_js:
            try:
                renderer = await Renderer(self.config.user_agent).__aenter__()
            except RendererUnavailable as exc:
                result.render_error = str(exc)

        queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        seen: set[str] = set()
        for url, depth in self.store.frontier(run_id, "done") + self.store.frontier(
            run_id, "queued"
        ):
            if url not in seen:
                seen.add(url)
                queue.put_nowait((url, depth))

        budget = [0]  # URLs started; reserved before awaiting so workers cannot overshoot

        async def worker() -> None:
            while True:
                url, depth = await queue.get()
                try:
                    if url in result.pages:  # already recorded as a redirect target
                        self.store.mark_done(run_id, url)
                        continue
                    if budget[0] >= self.config.max_pages:
                        result.truncated = True
                        continue
                    budget[0] += 1
                    for nxt in await self._visit(client, renderer, result, url, depth):
                        if nxt not in seen and depth + 1 <= self.config.max_depth:
                            seen.add(nxt)
                            self.store.enqueue(run_id, nxt, depth + 1, url)
                            queue.put_nowait((nxt, depth + 1))
                    self.store.mark_done(run_id, url)
                    if self.progress:
                        self.progress(len(result.pages), len(seen), url)
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(max(1, self.config.concurrency))]
        try:
            await queue.join()
        finally:
            for task in workers:
                task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            if renderer is not None:
                await renderer.__aexit__(None, None, None)

        if self.config.check_external:
            await self._check_external(client, result)
        if not result.truncated:
            self.store.finish_run(run_id)
        return result

    async def _visit(
        self,
        client: PoliteClient,
        renderer: Renderer | None,
        result: CrawlResult,
        url: str,
        depth: int,
    ) -> list[str]:
        if not self._in_scope(url):
            result.excluded.append(url)
            return []
        try:
            fetched = await client.fetch(url)
        except RobotsDisallowed:
            result.blocked.append(url)
            return []
        page = self._to_page(fetched, depth)
        result.pages[url] = page
        if (
            fetched.chain
            and page.final_url not in result.pages
            and same_site(page.final_url, result.site)
        ):
            # Record the redirect target as a page too, so link analysis sees it.
            target = self._to_page(fetched, depth)
            target.url = target.final_url
            target.redirect_chain = []
            result.pages[target.url] = target
            page = target
        if page.error or not page.is_html or page.status != 200:
            return []
        parse_html(page, fetched.text, result.site)
        if renderer is not None:
            await self._render(renderer, page, result.site)

        out: list[str] = []
        edges = result.edges.setdefault(page.url, set())
        for link in page.internal_links:
            edges.add(link.url)
            if link.nofollow and not self.config.follow_nofollow:
                continue
            if page.nofollow and not self.config.follow_nofollow:
                continue
            if not is_asset(link.url):
                out.append(link.url)
        extra = [page.canonical] + [h.url for h in page.hreflangs]
        out.extend(u for u in extra if u and same_site(u, result.site) and not is_asset(u))
        return out

    @staticmethod
    def _to_page(fetched: FetchResult, depth: int) -> PageData:
        return PageData(
            url=fetched.url,
            final_url=fetched.final_url,
            status=fetched.status,
            headers=dict(fetched.headers),
            redirect_chain=list(fetched.chain),
            content_type=fetched.headers.get("content-type", ""),
            elapsed_ms=fetched.elapsed_ms,
            size_bytes=len(fetched.body),
            depth=depth,
            error=fetched.error,
        )

    async def _render(self, renderer: Renderer, page: PageData, site: str) -> None:
        raw_words = page.word_count
        try:
            html = await renderer.render(page.final_url)
        except Exception as exc:  # rendering failures must not abort the crawl
            page.error = f"render failed: {exc}"
            return
        rendered = PageData(
            url=page.url,
            final_url=page.final_url,
            status=page.status,
            headers=page.headers,
            redirect_chain=page.redirect_chain,
            content_type=page.content_type,
            elapsed_ms=page.elapsed_ms,
            size_bytes=page.size_bytes,
            depth=page.depth,
        )
        parse_html(rendered, html, site)
        for f in dataclasses.fields(PageData):
            setattr(page, f.name, getattr(rendered, f.name))
        page.raw_word_count = raw_words
        page.rendered = True

    async def _probe_site(self, client: PoliteClient, result: CrawlResult) -> None:
        """Probe site-wide behaviours: missing-page status, HTTP->HTTPS, www consistency."""
        parts = urlsplit(result.site)
        missing = f"{result.site}/seoforge-404-probe-{secrets.token_hex(6)}"
        probes = {"missing_page": missing}
        if parts.scheme == "https":
            probes["http_home"] = urlunsplit(("http", parts.netloc, "/", "", ""))
        host = parts.netloc
        alt = host[4:] if host.startswith("www.") else f"www.{host}"
        if (
            "." in host
            and not host.replace(".", "").replace(":", "").isdigit()
            and host != "localhost"
        ):
            probes["alt_host_home"] = urlunsplit((parts.scheme, alt, "/", "", ""))
        for name, url in probes.items():
            fetched = await client.fetch(
                url, check_robots=False, method="HEAD" if name != "missing_page" else "GET"
            )
            result.probes[name] = SiteProbe(url, fetched.status, fetched.final_url, fetched.error)

    async def _check_external(self, client: PoliteClient, result: CrawlResult) -> None:
        targets = sorted({link.url for page in result.html_pages for link in page.external_links})[
            : self.config.max_external_checks
        ]

        async def check(url: str) -> None:
            try:
                fetched = await client.fetch(url, method="HEAD")
                if fetched.status in (403, 405, 501):  # many servers reject HEAD
                    fetched = await client.fetch(url)
            except RobotsDisallowed:
                return
            result.external_status[url] = fetched.status if not fetched.error else 0

        sem = asyncio.Semaphore(self.config.concurrency)

        async def bounded(url: str) -> None:
            async with sem:
                await check(url)

        await asyncio.gather(*(bounded(u) for u in targets))
