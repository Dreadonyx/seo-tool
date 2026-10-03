"""Where (and whether) you can submit a site, per search engine."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Engine:
    name: str
    index: str  # whose index results come from
    how: str
    url: str | None
    seoforge: str | None  # command that helps


ENGINES: tuple[Engine, ...] = (
    Engine(
        "Google",
        "own",
        "Verify the property in Search Console, submit sitemap, inspect URLs.",
        "https://search.google.com/search-console",
        "seoforge index gsc-sitemap / gsc-inspect",
    ),
    Engine(
        "Bing (also powers Copilot answers)",
        "own",
        "Verify in Bing Webmaster Tools (can import from Search Console); submit sitemap; IndexNow.",
        "https://www.bing.com/webmasters",
        "seoforge index bing / indexnow",
    ),
    Engine(
        "Yandex",
        "own",
        "Yandex Webmaster; IndexNow participant.",
        "https://webmaster.yandex.com",
        "seoforge index indexnow",
    ),
    Engine("Seznam.cz", "own", "IndexNow participant.", None, "seoforge index indexnow"),
    Engine(
        "Naver",
        "own",
        "Naver Search Advisor; IndexNow participant.",
        "https://searchadvisor.naver.com",
        "seoforge index indexnow",
    ),
    Engine("Yep", "own", "IndexNow participant.", None, "seoforge index indexnow"),
    Engine(
        "Baidu",
        "own",
        "Baidu Search Resource Platform (account setup typically needs a Chinese phone number).",
        "https://ziyuan.baidu.com",
        None,
    ),
    Engine(
        "Brave Search",
        "own",
        "Independent index with no submission console; it discovers "
        "pages via links and its own crawling. Make sure robots.txt doesn't block it.",
        None,
        None,
    ),
    Engine(
        "DuckDuckGo",
        "mostly Bing + own sources",
        "No submission; covered by Bing Webmaster Tools / IndexNow.",
        None,
        None,
    ),
    Engine("Yahoo", "Bing", "No submission; covered by Bing.", None, None),
    Engine("Ecosia", "Bing and Google (varies by market)", "No submission.", None, None),
    Engine("Startpage", "Google", "No submission; covered by Google.", None, None),
    Engine(
        "Chrome / Firefox / Edge / Safari",
        "browsers, not search engines",
        "Nothing to submit. Their default search engines are listed above.",
        None,
        None,
    ),
)

NOTE = (
    "Search partnerships change; verify current arrangements. Submitting never guarantees "
    "indexing - it only tells engines a URL exists or changed."
)
