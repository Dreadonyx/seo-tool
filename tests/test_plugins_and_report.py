"""Plugin loading, disabled checks, and HTML report rendering with every section."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from seoforge.audit import AuditOptions, run_audit
from seoforge.checks.base import REGISTRY
from seoforge.config import Config, load_config
from seoforge.report.render import render_html, render_markdown

sys.path.insert(0, str(Path(__file__).parent / "plugins"))


def test_plugin_registered_and_disable(site_url: str, tmp_path: Path) -> None:
    cfg = Config(
        data_dir=str(tmp_path / "d"),
        plugins=["demo_plugin"],
        disabled_checks=["titles", "soft-404-sitewide"],
    )
    cfg.crawl.delay_seconds = 0
    try:
        report, _ = asyncio.run(run_audit(site_url, cfg, AuditOptions(pagespeed=False)))
        ids = {i.check_id for i in report.issues}
        assert "demo-lorem-ipsum" in ids and "demo-lorem-ipsum" in REGISTRY
        assert not ids & {"title-missing", "title-duplicate", "soft-404-sitewide"}
    finally:
        REGISTRY.pop("demo-lorem-ipsum", None)


def test_load_config_yaml(tmp_path: Path) -> None:
    path = tmp_path / "seoforge.yaml"
    path.write_text(
        "site: https://s.test\ncrawl:\n  max_pages: 7\ngeo:\n  ai_bot_preset: deny-all\n"
        "  ai_bots:\n    OAI-SearchBot: allow\n"
    )
    cfg = load_config(path)
    assert cfg.site == "https://s.test" and cfg.crawl.max_pages == 7
    assert cfg.geo.ai_bot_preset == "deny-all" and "ai_bot_preset" in cfg.geo.model_fields_set


def test_html_report_sections(audited) -> None:  # type: ignore[no-untyped-def]
    report, _ = audited
    html = render_html(report)
    for tab in (
        'data-tab="issues"',
        'data-tab="keywords"',
        'data-tab="aeo"',
        'data-tab="geo"',
        'data-tab="plan"',
        'data-tab="limits"',
    ):
        assert tab in html
    assert "GPTBot" in html and "Citation-friendliness" in html
    assert "<script>alert" not in html  # content is escaped
    md = render_markdown(report)
    assert "## Generative-engine optimization (GEO)" in md
    assert "## Answer-engine readiness (AEO)" in md
