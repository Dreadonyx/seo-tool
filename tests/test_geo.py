"""GEO: AI crawler access, llms.txt, entity tools, citation score, visibility tracker."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from seoforge.cli import app
from seoforge.config import EntityConfig
from seoforge.generators.llms import generate, mirror_path
from seoforge.geo import entity, visibility
from seoforge.geo.citation import score_page
from seoforge.models import PageData
from seoforge.storage import Store


def test_bot_access_from_live_robots(audited) -> None:  # type: ignore[no-untyped-def]
    _, ctx = audited
    geo = ctx.extras["geo"]
    access = {b.token: b for b in geo.bots}
    assert not access["GPTBot"].allowed and access["GPTBot"].explicit
    assert access["ClaudeBot"].allowed and not access["ClaudeBot"].explicit
    assert geo.llms_txt_status == 404  # soft-404 HTML is not a real llms.txt


def test_llms_files(audited) -> None:  # type: ignore[no-untyped-def]
    _, ctx = audited
    files = generate(ctx.crawl, ctx.config)
    base = ctx.crawl.site
    lines = files.llms_txt.splitlines()
    assert lines[0] == "# Acme Widgets"
    assert lines[2].startswith("> ")
    assert f"- [What is widget testing?]({base}/blog/what-is-widget-testing):" in files.llms_txt
    assert "noindex-page" not in files.llms_txt and "broken-page" not in files.llms_txt
    assert "## Blog" in files.llms_txt
    md = files.mirrors["blog/what-is-widget-testing.md"]
    assert "## Why does widget testing matter?" in md and "1. Pick one widget" in md
    assert "[2025 State of Testing survey](https://example.org/state-of-testing-2025)" in md
    assert "var hidden" not in files.llms_full_txt
    assert mirror_path("https://s.test/") == "index.html.md"
    assert mirror_path("https://s.test/docs/") == "docs/index.html.md"


def test_entity_and_wikidata_draft(audited) -> None:  # type: ignore[no-untyped-def]
    _, ctx = audited
    report = entity.analyze(ctx.crawl, EntityConfig())
    assert report.name == "Acme Widgets"  # from markup, not a title suffix
    assert report.platforms["GitHub"] == "https://github.com/acme-widgets"
    assert report.platforms["LinkedIn"] is None
    cfg = EntityConfig(
        name="Acme Widgets",
        description="Open-source widget testing tools.",
        founded="2019-04-01",
        founders=["Priya Raman"],
        city="Chennai",
        same_as=["https://www.linkedin.com/company/acme-widgets"],
    )
    qs, guide = entity.wikidata_draft(cfg, ctx.crawl.site, cfg.same_as + report.same_as)
    assert qs.splitlines()[:2] == ["CREATE", 'LAST\tLen\t"Acme Widgets"']
    assert 'LAST\tDen\t"open-source widget testing tools"' in qs
    assert "LAST\tP571\t+2019-00-00T00:00:00Z/9" in qs
    assert 'LAST\tP4264\t"acme-widgets"' in qs and 'LAST\tP2037\t"acme-widgets"' in qs
    assert all(not line.startswith("#") for line in qs.splitlines())  # pure commands only
    assert "Notability" in guide and "Priya Raman" in guide and "Chennai" in guide


def test_wikidata_search_mocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["action"] == "wbsearchentities"
        return httpx.Response(
            200, json={"search": [{"id": "Q1", "label": "Acme", "description": "x"}]}
        )

    import asyncio

    async def go() -> list[dict[str, str]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await entity.wikidata_search(client, "Acme")

    assert asyncio.run(go())[0]["url"] == "https://www.wikidata.org/wiki/Q1"


def test_citation_score_components(audited) -> None:  # type: ignore[no-untyped-def]
    _, ctx = audited
    scores = {c.url: c for c in ctx.extras["geo"].citation}
    article = scores[f"{ctx.crawl.site}/blog/what-is-widget-testing"]
    shell = scores[f"{ctx.crawl.site}/js-app"]
    assert article.score >= 80 and shell.score < 20
    assert article.components["sourced_stats"] == 15
    assert shell.components["server_rendered"] == 0
    old = PageData(url="u", final_url="u", status=200, content_type="text/html")
    old.json_ld = ['{"@type": "Article", "dateModified": "2020-01-01"}']
    assert score_page(old, None, today=date(2026, 10, 1)).components["freshness"] == 3


def test_visibility_tracker(tmp_path: Path) -> None:
    store = Store(tmp_path / "v.sqlite")
    ent = EntityConfig(name="Acme Widgets", category="widget testing tool", city="Chennai")
    prompts = visibility.default_prompts(ent, ["widget testing"])
    assert ("Best widget testing tool in Chennai", "local") in prompts
    assert visibility.add_prompts(store, prompts) == len(prompts)
    assert visibility.add_prompts(store, prompts) == 0  # idempotent
    pid = visibility.list_prompts(store)[0]["id"]
    visibility.log(
        store, visibility.Observation(pid, "perplexity", True, True, 2, "https://acme.test/x")
    )
    with pytest.raises(ValueError):
        visibility.log(store, visibility.Observation(pid, "myspace", True))
    csv_path = tmp_path / "obs.csv"
    csv_path.write_text(
        "prompt,engine,date,mentioned,cited_url,position,notes\n"
        "What is Acme Widgets?,chatgpt,2026-09-01,no,,,\n"
        "New prompt,claude,2026-09-02,yes,,1,good\n"
    )
    assert visibility.import_csv(store, csv_path) == 2
    data = visibility.summary(store)
    assert data["observations"] == 3
    assert data["trend"]["chatgpt"][0]["mention_rate"] == 0.0


def test_visibility_detect_and_run(tmp_path: Path) -> None:
    mentioned, cited, url = visibility.detect(
        "Try Acme Widgets (see https://www.acme.test/guide).", ["Acme Widgets"], "acme.test"
    )
    assert mentioned and cited and url == "https://www.acme.test/guide"
    assert visibility.detect("Nothing here", ["Acme"], "acme.test") == (False, False, None)
    store = Store(tmp_path / "v.sqlite")
    visibility.add_prompts(store, [("What is Acme?", "brand"), ("Best widgets?", "category")])
    script = tmp_path / "fake_ai.py"
    script.write_text(
        "import sys\nq = sys.argv[1]\nprint('Acme is great' if 'Acme' in q else 'Try Foo')\n"
    )
    results = visibility.run_command(
        store,
        "other",
        f"{sys.executable} {script} {{prompt}}",
        EntityConfig(name="Acme"),
        "https://acme.test",
    )
    assert [r.mentioned for r in results] == [True, False]
    with pytest.raises(ValueError):
        visibility.run_command(store, "other", "echo hi", EntityConfig(name="Acme"), None)


def test_visibility_cli(tmp_path: Path) -> None:
    cfg = tmp_path / "seoforge.yaml"
    cfg.write_text(f"data_dir: {tmp_path / 'd'}\nentity:\n  name: Acme\n  category: widget tool\n")
    runner = CliRunner()
    assert runner.invoke(app, ["visibility", "init", "-c", str(cfg)]).exit_code == 0
    listed = runner.invoke(app, ["visibility", "prompts", "-c", str(cfg)])
    assert "What is Acme?" in listed.output
    logged = runner.invoke(app, ["visibility", "log", "1", "claude", "--mentioned", "-c", str(cfg)])
    assert logged.exit_code == 0, logged.output
    bad = runner.invoke(app, ["visibility", "log", "1", "nope", "-c", str(cfg)])
    assert bad.exit_code == 2
    report = runner.invoke(app, ["visibility", "report", "-c", str(cfg)])
    assert "100%" in report.output


def test_geo_cli_bots(site_url: str, tmp_path: Path) -> None:
    cfg = tmp_path / "seoforge.yaml"
    cfg.write_text(f"data_dir: {tmp_path / 'd'}\n")
    result = CliRunner().invoke(app, ["geo", "bots", site_url, "-c", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "GPTBot" in result.output and "blocked" in result.output


def test_fix_bundle_has_geo_files(audited) -> None:  # type: ignore[no-untyped-def]
    from seoforge.fix.bundle import build_bundle
    from seoforge.geo.extras import add_geo_files

    _, ctx = audited
    files = {f.path: f for f in build_bundle(ctx, extra=add_geo_files).files}
    assert files["llms.txt"].deploy_path == "llms.txt"
    assert files["markdown/about.md"].deploy_path == "about.md"
    assert "entity/wikidata.qs" in files and "entity/brand-checklist.md" in files
    assert (
        "| GitHub | [linked](https://github.com/acme-widgets)"
        in files["entity/brand-checklist.md"].content
    )
