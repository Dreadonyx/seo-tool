"""End-to-end: crawl the local test site and verify the planted problems are found."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from typer.testing import CliRunner

from seoforge.cli import app
from seoforge.config import Config
from seoforge.crawler.crawler import Crawler
from seoforge.report.render import render_html, render_markdown, write_reports
from seoforge.storage import Store


def ids(report) -> set[str]:  # type: ignore[no-untyped-def]
    return {i.check_id for i in report.issues}


def test_crawl_graph(audited) -> None:  # type: ignore[no-untyped-def]
    _, ctx = audited
    crawl = ctx.crawl
    base = crawl.site
    assert f"{base}/blog/what-is-widget-testing" in crawl.pages
    assert f"{base}/orphan" in crawl.pages  # discovered via sitemap only
    assert f"{base}/private/secret" in crawl.blocked  # robots.txt respected
    old = crawl.pages[f"{base}/old-page"]
    assert [h.status for h in old.redirect_chain] == [301, 302]
    assert old.final_url == f"{base}/about"
    assert ctx.click_depths[f"{base}/blog/what-is-widget-testing"] == 1
    assert ctx.inlinks.get(f"{base}/orphan", 0) == 0


def test_planted_issues_detected(audited) -> None:  # type: ignore[no-untyped-def]
    report, _ = audited
    expected = {
        "no-https",
        "broken-internal-links",
        "soft-404-sitewide",
        "sitemap-urls-blocked",
        "sitemap-non-200",
        "sitemap-noindex",
        "sitemap-redirects",
        "canonical-multiple",
        "missing-viewport",
        "title-missing",
        "title-duplicate",
        "h1-missing",
        "h1-multiple",
        "redirect-chains",
        "nosnippet",
        "img-missing-alt",
        "orphan-pages",
        "duplicate-content",
        "heading-skip",
        "viewport-zoom-disabled",
        "missing-lang",
        "anchor-generic",
        "js-app-shell",
        "noindex-pages",
        "links-to-redirects",
        "keyword-cannibalization",
    }
    missing = expected - ids(report)
    assert not missing, f"not detected: {missing}"


def test_no_false_positives(audited) -> None:  # type: ignore[no-untyped-def]
    report, ctx = audited
    by_id = {i.check_id: i for i in report.issues}
    base = ctx.crawl.site
    # The article has a canonical and the about page is linked - neither is an orphan.
    assert f"{base}/about" not in by_id["orphan-pages"].urls
    # noindex page must not be reported as missing a title or canonical.
    assert f"{base}/noindex-page" not in by_id.get("canonical-missing", by_id["orphan-pages"]).urls
    assert "redirect-loops" not in by_id


def test_issues_sorted_and_cited(audited) -> None:  # type: ignore[no-untyped-def]
    report, _ = audited
    ranks = [i.severity.rank for i in report.issues]
    assert ranks == sorted(ranks)
    assert all(i.source and i.source.startswith("https://") for i in report.issues)
    assert 0 <= report.score <= 100
    assert set(report.plan) == {"30", "60", "90"}


def test_report_outputs(audited, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    report, _ = audited
    paths = write_reports(report, tmp_path, ["html", "md", "json"])
    assert [p.name for p in paths] == ["report.html", "report.md", "report.json"]
    data = json.loads((tmp_path / "report.json").read_text())
    assert data["issues"] and data["limitations"] and data["disclaimer"]
    html = render_html(report)
    assert "What this tool cannot do" in html and "<script>" in html
    md = render_markdown(report)
    assert "## 30 / 60 / 90-day plan" in md and "cannot" in md


def test_keyword_map(audited) -> None:  # type: ignore[no-untyped-def]
    _, ctx = audited
    kw = ctx.extras["keywords"]
    by_url = {p.url: p for p in kw.pages}
    article = by_url[f"{ctx.crawl.site}/blog/what-is-widget-testing"]
    assert article.primary == "widget testing"
    assert article.intent == "informational"
    assert by_url[f"{ctx.crawl.site}/products/widget"].intent == "transactional"


def test_resume_uses_frontier(site_url: str, config: Config) -> None:
    store = Store(config.db_path)
    config.crawl.max_pages = 3
    first = asyncio.run(Crawler(config.crawl, store).crawl(site_url))
    assert first.truncated and len(first.pages) <= 4  # +1 possible redirect target
    config.crawl.max_pages = 100
    second = asyncio.run(Crawler(config.crawl, store).crawl(site_url, resume=True))
    assert second.resumed and len(second.pages) > 3
    store.close()


def test_cli_audit(site_url: str, tmp_path: Path) -> None:
    out = tmp_path / "out"
    cfg = tmp_path / "seoforge.yaml"
    cfg.write_text(f"data_dir: {tmp_path / 'data'}\ncrawl:\n  delay_seconds: 0\n")
    result = CliRunner().invoke(
        app,
        [
            "audit",
            site_url,
            "-c",
            str(cfg),
            "-o",
            str(out),
            "--no-pagespeed",
            "--fail-on",
            "critical",
        ],
    )
    assert result.exit_code == 1, result.output  # the test site has critical issues
    assert (out / "report.html").exists()
    assert "Health score" in result.output
