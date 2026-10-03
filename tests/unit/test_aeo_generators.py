import json

from seoforge.analysis.aeo import analyze_page, draft_answer, is_question
from seoforge.generators.redirects import RedirectPlan, Rule, apache, netlify, nginx, vercel
from seoforge.generators.robots import generate_robots
from seoforge.geo.ai_bots import resolve_policy
from seoforge.models import PageData
from seoforge.robots import RobotsTxt

LONG = (
    "Widget testing verifies a single interface widget in isolation. It renders the widget with "
    "fixed inputs and checks the output. Teams run these tests on every commit because they are "
    "fast. They catch visual regressions before release. They also document expected behaviour "
    "for new engineers joining the project."
)


def test_question_detection() -> None:
    assert is_question("What is widget testing?")
    assert is_question("How do you start")
    assert not is_question("Widget testing basics")


def test_draft_answer_only_uses_page_text() -> None:
    draft = draft_answer(LONG)
    assert len(draft.split()) <= 60
    assert all(sentence in LONG for sentence in draft.rstrip("…").split(". ") if sentence)


def test_analyze_page_qa_and_drafts() -> None:
    p = PageData(url="u", final_url="u", status=200)
    p.outline = [
        ("h1", "Widget testing guide"),
        ("p", "Intro: widget testing is a practice for UI quality."),
        ("h2", "What is widget testing?"),
        ("p", "Short answer here."),
        ("p", LONG),
        ("h2", "How to start"),
        ("li", "Pick a widget"),
        ("li", "Write a test"),
        ("li", "Assert output"),
        ("h2", "FAQ"),
    ]
    r = analyze_page(p, "widget testing", "informational")
    assert r.questions == ["What is widget testing?", "How to start"]
    assert [q.ideal for q in r.qa] == [False, True]  # list of 3 steps counts as snippet-ready
    assert "What is widget testing?" in r.drafts
    assert r.has_faq and r.has_steps and r.has_definition
    assert any(q.startswith("Why is widget testing") for q in r.suggested_questions)


def test_robots_generator_preserves_rules_and_applies_policy() -> None:
    existing = RobotsTxt(
        "User-agent: *\nDisallow: /admin/\n\nUser-agent: GPTBot\nAllow: /\n"
        "\nUser-agent: Bingbot\nCrawl-delay: 5\n"
    )
    policy = resolve_policy("search-only", {"PerplexityBot": "deny"})
    text = generate_robots(existing, policy, ["https://s.test/sitemap.xml"], "search-only")
    out = RobotsTxt(text)
    assert not out.can_fetch("SEOForge", "https://s.test/admin/x")
    assert not out.can_fetch("GPTBot", "https://s.test/")  # training bot denied
    assert out.can_fetch("OAI-SearchBot", "https://s.test/page")
    assert not out.can_fetch("OAI-SearchBot", "https://s.test/admin/x")  # inherits '*' rules
    assert not out.can_fetch("PerplexityBot", "https://s.test/")  # override
    assert out.crawl_delay("Bingbot") == 5
    assert out.sitemaps == ["https://s.test/sitemap.xml"]
    assert not out.warnings


def test_policy_presets() -> None:
    assert set(resolve_policy("allow-all", {}).values()) == {"allow"}
    assert set(resolve_policy("deny-all", {}).values()) == {"deny"}
    assert resolve_policy("search-only", {})["ClaudeBot"] == "deny"
    assert resolve_policy("search-only", {"claudebot": "allow"})["ClaudeBot"] == "allow"


def test_redirect_renderers() -> None:
    plan = RedirectPlan(
        site="https://s.test",
        rules=[Rule("/old", "/new"), Rule("/q?id=1", "/x", 302)],
        force_https=True,
        canonical_host="s.test",
        alt_host="www.s.test",
        broken=["/gone"],
    )
    assert "location = /old { return 301 https://s.test/new; }" in nginx(plan)
    assert "Redirect 301 /old https://s.test/new" in apache(plan)
    assert r"^www\.s\.test$" in apache(plan)
    data = json.loads(vercel(plan))
    assert {"source": "/old", "destination": "/new", "permanent": True} in data["redirects"]
    assert data["redirects"][0]["has"][0]["value"] == "www.s.test"
    lines = netlify(plan).splitlines()
    assert "https://www.s.test/* https://s.test/:splat 301!" in lines and "/old /new 301" in lines
    assert "# TODO broken URL: /gone" in lines
