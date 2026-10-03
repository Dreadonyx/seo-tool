from seoforge.crawler.parser import hamming, parse_html, simhash
from seoforge.crawler.sitemaps import parse_sitemap
from seoforge.models import PageData
from seoforge.urls import normalize, same_site

HTML = """<!doctype html><html lang="en"><head>
<title> Hello   World </title>
<meta name="description" content="Desc">
<meta name="robots" content="noindex, follow">
<link rel="canonical" href="/canon">
<link rel="alternate" hreflang="de" href="https://site.test/de/">
<meta property="og:title" content="OG">
<script type="application/ld+json">{"@type":"Thing"}</script>
</head><body>
<nav><a href="/nav">Nav</a></nav>
<main><h1>Main heading</h1><p>First paragraph with <a href="/inner#frag" rel="nofollow">inner</a>.</p>
<ul><li>Item one</li></ul>
<img src="/a.png"><img src="/b.png" alt="" width="1" height="1">
<a href="https://other.test/x">ext</a><a href="mailto:a@b.c">mail</a>
<time datetime="2026-01-01">Jan</time></main>
<script>var hidden = "not content";</script>
</body></html>"""


def _page() -> PageData:
    p = PageData(
        url="https://site.test/p",
        final_url="https://site.test/p",
        status=200,
        content_type="text/html",
    )
    return parse_html(p, HTML, "https://site.test")


def test_parse_head_fields() -> None:
    p = _page()
    assert p.title == "Hello World"
    assert p.meta_description == "Desc"
    assert p.noindex and not p.nofollow
    assert p.canonical == "https://site.test/canon"
    assert p.hreflangs[0].lang == "de"
    assert p.open_graph["og:title"] == "OG"
    assert len(p.json_ld) == 1
    assert p.lang == "en"
    assert p.times == ["2026-01-01"]


def test_parse_body_fields() -> None:
    p = _page()
    assert p.h1s == ["Main heading"]
    urls = {link.url: link for link in p.links}
    assert "https://site.test/inner" in urls and urls["https://site.test/inner"].nofollow
    assert not urls["https://other.test/x"].internal
    assert all(not u.startswith("mailto") for u in urls)
    assert [i.alt for i in p.images] == [None, ""]
    assert "not content" not in p.text and "First paragraph" in p.text
    assert "Item one" in p.blocks
    assert p.lists_count == 1


def test_x_robots_tag_scoped() -> None:
    p = PageData(url="u", final_url="u", status=200, headers={"x-robots-tag": "googlebot: noindex"})
    assert p.noindex


def test_normalize() -> None:
    assert normalize("HTTPS://Site.Test:443/a#x") == "https://site.test/a"
    assert normalize("/b?q=1", "http://site.test/a/") == "http://site.test/b?q=1"
    assert normalize("javascript:void(0)") is None
    assert normalize("https://site.test") == "https://site.test/"
    assert same_site("https://www.site.test/a", "https://site.test")


def test_simhash_near_duplicates() -> None:
    a = "the quick brown fox jumps over the lazy dog " * 20
    b = a + " extra words"
    c = "completely different content about widget testing and calibration " * 20
    assert hamming(simhash(a), simhash(b)) <= 3
    assert hamming(simhash(a), simhash(c)) > 10


def test_parse_sitemap_variants() -> None:
    xml = b"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url><loc>https://s.test/a</loc><lastmod>2026-01-01</lastmod></url><url></url></urlset>"""
    sm = parse_sitemap("u", 200, xml)
    assert sm.entries[0].loc == "https://s.test/a" and sm.entries[0].lastmod == "2026-01-01"
    assert any("without <loc>" in e for e in sm.errors)
    index = b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <sitemap><loc>https://s.test/s1.xml</loc></sitemap></sitemapindex>"""
    assert parse_sitemap("u", 200, index).children == ["https://s.test/s1.xml"]
    assert parse_sitemap("u", 200, b"<urlset><broken").errors
    assert parse_sitemap("u", 404, b"").errors == ["HTTP 404"]
    text = parse_sitemap("u", 200, b"https://s.test/a\nhttps://s.test/b\n")
    assert len(text.entries) == 2
