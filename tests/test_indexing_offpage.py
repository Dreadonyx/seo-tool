"""Indexing (IndexNow, GSC, Bing) via MockTransport, diagnose and off-page against the test site."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from seoforge.cli import app
from seoforge.config import Config
from seoforge.http import PoliteClient
from seoforge.indexing import indexnow as ix
from seoforge.indexing.bing import BingClient, BingError
from seoforge.indexing.diagnose import diagnose
from seoforge.indexing.gsc import GSCAuthError, GSCClient, get_token, property_url
from seoforge.offpage.broken_links import find_broken_links
from seoforge.offpage.checklist import checklist_markdown
from seoforge.offpage.mentions import find_mentions
from seoforge.storage import Store
from serve_site import INDEXNOW_KEY


def mock_client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---- IndexNow --------------------------------------------------------------------------------
def test_indexnow_key_and_filtering() -> None:
    key = ix.generate_key()
    assert ix.valid_key(key) and len(key) == 32
    assert not ix.valid_key("short") and not ix.valid_key("bad key with spaces!")
    good, bad = ix.filter_urls(
        ["https://s.test/a", "https://s.test/a", "https://other.test/b"], "https://s.test"
    )
    assert good == ["https://s.test/a"] and bad == ["https://other.test/b"]


def test_indexnow_submit_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(202 if len(payloads) == 1 else 200)

    monkeypatch.setattr(ix, "BATCH", 2)
    urls = [f"https://s.test/{i}" for i in range(5)]

    async def go() -> list[ix.SubmitResult]:
        async with mock_client(handler) as c:
            return await ix.submit(c, "https://s.test", "abcdef123456", urls)

    results = asyncio.run(go())
    assert [r.count for r in results] == [2, 2, 1]
    assert payloads[0] == {"host": "s.test", "key": "abcdef123456", "urlList": urls[:2]}
    assert results[0].meaning.startswith("Accepted")


def test_indexnow_stops_on_error() -> None:
    async def go() -> list[ix.SubmitResult]:
        async with mock_client(lambda r: httpx.Response(403)) as c:
            return await ix.submit(c, "https://s.test", "abcdef123456", ["https://s.test/a"])

    [result] = asyncio.run(go())
    assert result.status == 403 and "key not valid" in result.meaning


def test_indexnow_changed_only(tmp_path: Path) -> None:
    store = Store(tmp_path / "s.db")
    pages = {"https://s.test/a": "h1", "https://s.test/b": "h2"}
    assert ix.changed_urls(store, pages) == list(pages)
    ix.remember(store, pages)
    assert ix.changed_urls(store, {**pages, "https://s.test/b": "h3"}) == ["https://s.test/b"]


def test_indexnow_key_file_verification(site_url: str) -> None:
    async def go(key: str) -> ix.KeyCheck:
        async with httpx.AsyncClient() as c:
            return await ix.verify_key_file(c, site_url, key)

    assert asyncio.run(go(INDEXNOW_KEY)).ok
    wrong = asyncio.run(go("abcdefgh12345678"))
    assert not wrong.ok and "does not match" in wrong.detail  # soft-404 HTML body


def test_indexnow_cli_dry_run(site_url: str, tmp_path: Path) -> None:
    urls = tmp_path / "urls.txt"
    urls.write_text(f"{site_url}/about\nhttps://elsewhere.test/x\n")
    cfg = tmp_path / "c.yaml"
    cfg.write_text(f"data_dir: {tmp_path / 'd'}\n")
    result = CliRunner().invoke(
        app,
        [
            "index",
            "indexnow",
            site_url,
            "--key",
            INDEXNOW_KEY,
            "--urls",
            str(urls),
            "--dry-run",
            "-c",
            str(cfg),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Skipping 1 URL(s) from other hosts" in result.output
    assert "Dry run" in result.output and "Nothing sent" in result.output


# ---- Google Search Console -------------------------------------------------------------------
def test_gsc_sitemap_and_inspection_quota(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "PUT":
            return httpx.Response(204)
        if request.method == "GET":
            return httpx.Response(200, json={"sitemap": [{"path": "https://s.test/sitemap.xml"}]})
        body = json.loads(request.content)
        assert body["siteUrl"] == "https://s.test/"
        return httpx.Response(
            200,
            json={
                "inspectionResult": {
                    "indexStatusResult": {
                        "verdict": "PASS",
                        "coverageState": "Submitted and indexed",
                        "googleCanonical": body["inspectionUrl"],
                        "robotsTxtState": "ALLOWED",
                    }
                }
            },
        )

    store = Store(tmp_path / "q.db")

    async def go() -> list[Any]:
        async with mock_client(handler) as c:
            gsc = GSCClient(c, "tok", store, daily_budget=2)
            await gsc.submit_sitemap("https://s.test/", "https://s.test/sitemap.xml")
            out = [await gsc.inspect("https://s.test/", f"https://s.test/{i}") for i in range(3)]
            return [out, gsc.remaining("https://s.test/")]

    results, remaining = asyncio.run(go())
    assert str(seen[0].url).endswith(
        "/sites/https%3A%2F%2Fs.test%2F/sitemaps/https%3A%2F%2Fs.test%2Fsitemap.xml"
    )
    assert seen[0].headers["Authorization"] == "Bearer tok"
    assert [r.verdict for r in results[:2]] == ["PASS", "PASS"]
    assert results[2].error and "budget" in results[2].error  # quota respected, no request sent
    assert remaining == 0 and len(seen) == 3


def test_gsc_auth_and_property(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GSC_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("GSC_SERVICE_ACCOUNT_FILE", raising=False)
    with pytest.raises(GSCAuthError):
        get_token()
    monkeypatch.setenv("GSC_ACCESS_TOKEN", "abc")
    assert get_token() == "abc"
    assert property_url("https://www.s.test", domain_property=True) == "sc-domain:www.s.test"


# ---- Bing ------------------------------------------------------------------------------------
def test_bing_quota_trims_batch() -> None:
    calls: list[tuple[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        assert request.url.params["apikey"] == "k"
        calls.append((method, json.loads(request.content) if request.content else None))
        if method == "GetUrlSubmissionQuota":
            return httpx.Response(200, json={"d": {"DailyQuota": 2, "MonthlyQuota": 10}})
        return httpx.Response(200, json={"d": None})

    async def go() -> int:
        async with mock_client(handler) as c:
            bing = BingClient(c, "k")
            await bing.submit_sitemap("https://s.test", "https://s.test/sitemap.xml")
            return await bing.submit_urls(
                "https://s.test", ["https://s.test/1", "https://s.test/2", "https://s.test/3"]
            )

    assert asyncio.run(go()) == 2
    assert calls[0] == (
        "SubmitFeed",
        {"siteUrl": "https://s.test", "feedUrl": "https://s.test/sitemap.xml"},
    )
    assert calls[-1][1]["urlList"] == ["https://s.test/1", "https://s.test/2"]


def test_bing_error() -> None:
    async def go() -> None:
        async with mock_client(lambda r: httpx.Response(401, text="bad key")) as c:
            await BingClient(c, "k").quota("https://s.test")

    with pytest.raises(BingError):
        asyncio.run(go())


# ---- Diagnose --------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("path", "check", "status"),
    [
        ("/noindex-page", "noindex", "fail"),
        ("/old-page", "redirects", "fail"),
        ("/private/secret", "robots.txt (Googlebot)", "fail"),
        ("/broken-page", "status", "fail"),
        ("/about", "noindex", "pass"),
        ("/about", "sitemap", "pass"),
        ("/blog/what-is-widget-testing", "sitemap", "warn"),
        ("/js-app", "rendering", "warn"),
    ],
)
def test_diagnose(site_url: str, config: Config, path: str, check: str, status: str) -> None:
    result = asyncio.run(diagnose(site_url + path, config, Store(config.db_path)))
    found = {f.check: f.status for f in result.findings}
    assert found.get(check) == status, result.findings


def test_diagnose_counts_internal_links(site_url: str, config: Config) -> None:
    result = asyncio.run(
        diagnose(f"{site_url}/about", config, Store(config.db_path), crawl_pages=30)
    )
    assert {f.check: f.status for f in result.findings}["internal links"] == "pass"


# ---- Off-page --------------------------------------------------------------------------------
def test_broken_link_finder(site_url: str, config: Config) -> None:
    def wayback(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "archived_snapshots": {
                    "closest": {"available": True, "url": "https://web.archive.org/web/2020/x"}
                }
            },
        )

    async def go() -> Any:
        async with PoliteClient(config.crawl) as client, mock_client(wayback) as api:
            return await find_broken_links(
                client, [f"{site_url}/resources", f"{site_url}/private/secret"], api=api
            )

    report = asyncio.run(go())
    port = site_url.rsplit(":", 1)[1]
    assert [d.url for d in report.dead] == [f"http://localhost:{port}/broken-page"]
    assert report.dead[0].anchor == "Widget testing handbook" and report.dead[0].archived
    assert report.pages[f"{site_url}/private/secret"].startswith("blocked by robots.txt")


def test_unlinked_mentions(site_url: str, config: Config) -> None:
    def api(request: httpx.Request) -> httpx.Response:
        if "algolia" in request.url.host:
            return httpx.Response(
                200,
                json={
                    "hits": [
                        {"objectID": "1", "title": "Resources", "url": f"{site_url}/resources"},
                        {"objectID": "2", "title": "About", "url": f"{site_url}/about"},
                        {"objectID": "3", "title": "Own", "url": "https://acme.example/blog"},
                    ]
                },
            )
        return httpx.Response(200, json={"query": {"search": []}})

    async def go() -> Any:
        async with PoliteClient(config.crawl) as client, mock_client(api) as c:
            return await find_mentions(client, c, "Acme Widgets", "https://acme.example")

    report = asyncio.run(go())
    linked = {m.url: m.linked for m in report.mentions}
    assert linked[f"{site_url}/resources"] is True
    assert linked[f"{site_url}/about"] is False  # mentions the brand, no link: outreach target
    assert linked["https://acme.example/blog"] is True
    assert [m.url for m in report.unlinked] == [f"{site_url}/about"]
    assert any("bing.com" in s for s in report.manual_searches)


def test_offpage_checklist_cli() -> None:
    assert "PBN" in checklist_markdown() or "private blog networks" in checklist_markdown()
    result = CliRunner().invoke(app, ["offpage", "policy"])
    assert result.exit_code == 0 and "never" in result.output
    engines = CliRunner().invoke(app, ["index", "engines"])
    assert "Brave" in engines.output and "browsers" in engines.output
