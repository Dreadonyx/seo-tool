"""Network-touching analyses, using the local test site or httpx.MockTransport (no real APIs)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from seoforge.analysis.competitors import content_gap
from seoforge.analysis.suggest import expand_seeds, suggestions
from seoforge.config import Config
from seoforge.crawler.crawler import Crawler
from seoforge.crawler.renderer import Renderer, RendererUnavailable
from seoforge.http import PoliteClient
from seoforge.storage import Store


def test_competitor_gap_respects_robots_and_finds_terms(
    audited, site_url: str, config: Config
) -> None:  # type: ignore[no-untyped-def]
    _, ctx = audited
    own = [p for p in ctx.pages if not p.url.endswith("/orphan")]  # pretend we lack this page

    async def go():  # type: ignore[no-untyped-def]
        async with PoliteClient(config.crawl) as client:
            return await content_gap(
                client, own, [f"{site_url}/orphan", f"{site_url}/private/secret"]
            )

    report = asyncio.run(go())
    assert report.competitors[f"{site_url}/private/secret"].startswith("blocked by robots.txt")
    assert any("calibration" in g["term"] for g in report.gaps)


def test_autosuggest_cached_and_polite(tmp_path) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params["q"]
        calls.append(q)
        return httpx.Response(200, json=[q, [q, f"{q} free", f"{q} tutorial"]])

    store = Store(tmp_path / "db.sqlite")

    async def go() -> dict[str, list[str]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            import seoforge.analysis.suggest as s

            s.MIN_INTERVAL = 0  # keep the test fast
            return await suggestions(client, store, ["widget testing"], max_queries=2)

    first = asyncio.run(go())
    assert first["widget testing"] == ["widget testing free", "widget testing tutorial"]
    n = len(calls)
    asyncio.run(go())
    assert len(calls) == n  # served from cache
    assert expand_seeds(["x"])[:3] == ["x", "how to x", "what is x"]


def test_autosuggest_stops_on_rate_limit(tmp_path) -> None:  # type: ignore[no-untyped-def]
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429)

    async def go() -> dict[str, list[str]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await suggestions(client, Store(tmp_path / "d.sqlite"), ["a", "b"])

    assert asyncio.run(go()) == {} and len(calls) == 1


def _chromium_available() -> bool:
    async def probe() -> bool:
        try:
            async with Renderer("test"):
                return True
        except RendererUnavailable:
            return False

    return asyncio.run(probe())


@pytest.mark.skipif(not _chromium_available(), reason="playwright chromium not installed")
def test_js_rendering_reveals_content(site_url: str, config: Config) -> None:
    config.crawl.render_js = True
    config.crawl.include = [r"/js-app$", r"/$"]
    store = Store(config.db_path)
    result = asyncio.run(Crawler(config.crawl, store).crawl(site_url))
    page = result.pages[f"{site_url}/js-app"]
    assert page.rendered and page.h1s == ["Dashboard"]
    assert page.raw_word_count is not None and page.raw_word_count < 5 < page.word_count
