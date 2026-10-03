from seoforge.robots import RobotsTxt

ROBOTS = """
User-agent: *
Disallow: /private/
Allow: /private/public-page
Disallow: /*.pdf$
Disallow: /search?

User-agent: GPTBot
User-agent: CCBot
Disallow: /

User-agent: Googlebot
Allow: /
Crawl-delay: 2

Sitemap: https://example.com/sitemap.xml
Bogus: line
noindex: /x
"""


def test_group_selection_and_longest_match() -> None:
    r = RobotsTxt(ROBOTS)
    assert r.can_fetch("SEOForge", "https://example.com/")
    assert not r.can_fetch("SEOForge", "https://example.com/private/x")
    assert r.can_fetch("SEOForge", "https://example.com/private/public-page")
    assert not r.can_fetch("SEOForge", "https://example.com/files/a.pdf")
    assert r.can_fetch("SEOForge", "https://example.com/files/a.pdf?x=1")
    assert not r.can_fetch("SEOForge", "https://example.com/search?q=a")
    # Grouped user-agents share rules; specific group overrides '*'.
    assert not r.can_fetch("GPTBot", "https://example.com/")
    assert not r.can_fetch("CCBot/2.0", "https://example.com/anything")
    assert r.can_fetch("Googlebot", "https://example.com/private/x")
    assert r.crawl_delay("Googlebot") == 2
    assert r.has_group_for("gptbot") and not r.has_group_for("ClaudeBot")


def test_sitemaps_and_warnings() -> None:
    r = RobotsTxt(ROBOTS)
    assert r.sitemaps == ["https://example.com/sitemap.xml"]
    messages = " ".join(w.message for w in r.warnings)
    assert "bogus" in messages and "noindex" in messages


def test_allow_wins_on_equal_length() -> None:
    r = RobotsTxt("User-agent: *\nDisallow: /page\nAllow: /page\n")
    assert r.can_fetch("x", "https://e.com/page")


def test_status_semantics() -> None:
    assert RobotsTxt("", status=404).can_fetch("x", "https://e.com/a")
    assert not RobotsTxt("", status=503).can_fetch("x", "https://e.com/a")
    assert RobotsTxt("", status=503).can_fetch("x", "https://e.com/robots.txt")
    assert RobotsTxt("User-agent: *\nDisallow: /\n").blocks_everything("Googlebot")


def test_empty_disallow_allows_all() -> None:
    r = RobotsTxt("User-agent: *\nDisallow:\n")
    assert r.can_fetch("x", "https://e.com/anything")
