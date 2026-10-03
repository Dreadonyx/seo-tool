"""`seoforge fix` end-to-end against the local test site."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from seoforge.cli import app
from seoforge.fix.bundle import build_bundle
from seoforge.robots import RobotsTxt


def _cfg(tmp_path: Path) -> Path:
    cfg = tmp_path / "seoforge.yaml"
    cfg.write_text(
        f"data_dir: {tmp_path / 'data'}\ncrawl:\n  delay_seconds: 0\n"
        "entity:\n  name: Acme Widgets\n  description: Open-source widget testing tools.\n"
    )
    return cfg


def test_bundle_contents(audited) -> None:  # type: ignore[no-untyped-def]
    _, ctx = audited
    bundle = build_bundle(ctx)
    files = {f.path: f for f in bundle.files}
    assert "sitemap.xml" in files and "robots.txt" in files
    sitemap = files["sitemap.xml"].content
    base = ctx.crawl.site
    assert f"<loc>{base}/about</loc>" in sitemap
    for excluded in ("/noindex-page", "/broken-page", "/old-page", "/private/secret"):
        assert f"<loc>{base}{excluded}</loc>" not in sitemap
    robots = RobotsTxt(files["robots.txt"].content)
    assert not robots.can_fetch("SEOForge", f"{base}/private/secret")
    assert not robots.can_fetch("CCBot", f"{base}/")
    org = files["jsonld/home.organization.html"].content
    assert '"name": "Acme Widgets"' in org and "https://github.com/acme-widgets" in org
    assert "jsonld/blog_what-is-widget-testing.howto.html" in files
    assert "jsonld/products_widget.product.html" in files  # existing Product markup is broken
    nginx = files["redirects/nginx.conf"].content
    assert f"location = /old-page {{ return 301 {base}/about; }}" in nginx
    meta = files["meta-tags.html"].content
    assert "missing-title" in meta and "<!-- TODO: write a unique, descriptive <title>" in meta
    todo = json.loads(files["jsonld/TODO.json"].content)
    assert any("Organization" in k for k in todo)


def test_fix_cli_apply_requires_confirmation(site_url: str, tmp_path: Path) -> None:
    site_root = tmp_path / "public"
    site_root.mkdir()
    (site_root / "robots.txt").write_text("User-agent: *\nDisallow:\n")
    out = tmp_path / "fixes"
    args = [
        "fix",
        site_url,
        "-c",
        str(_cfg(tmp_path)),
        "-o",
        str(out),
        "--apply-to",
        str(site_root),
    ]
    declined = CliRunner().invoke(app, args, input="n\n" * 50)
    assert declined.exit_code == 0, declined.output
    assert (site_root / "robots.txt").read_text() == "User-agent: *\nDisallow:\n"
    assert not (site_root / "sitemap.xml").exists()
    assert (out / "INDEX.md").exists() and (out / "robots.txt").exists()
    assert "--- a/robots.txt" in declined.output or "-User-agent" in declined.output

    accepted = CliRunner().invoke(app, [*args, "--yes", "--cached"])
    assert accepted.exit_code == 0, accepted.output
    assert "GPTBot" in (site_root / "robots.txt").read_text()
    assert (site_root / "sitemap.xml").exists()


def test_planted_m2_issues(audited) -> None:  # type: ignore[no-untyped-def]
    report, _ = audited
    found = {i.check_id for i in report.issues}
    assert {
        "jsonld-invalid-json",
        "jsonld-missing-required",
        "aeo-answer-length",
        "faq-howto-limited",
        "eeat-no-privacy",
        "no-website-schema",
    } <= found
    assert "eeat-no-about" not in found and "eeat-no-contact" not in found
