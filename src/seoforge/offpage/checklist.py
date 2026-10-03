"""Backlink opportunity checklist, directory list and SEOForge's anti-spam policy."""

from __future__ import annotations

ANTI_SPAM_POLICY = """\
# SEOForge off-page policy

SEOForge only helps with links people would give you anyway. It will never:

- buy, sell or exchange links, or use private blog networks (PBNs)
- mass-submit to directories, comment sections, forums or profile pages
- generate fake reviews, testimonials, sockpuppet accounts or astroturfed posts
- scrape search engine result pages or automate outreach spam
- hide links, cloak content, or create doorway pages

These tactics violate Google's spam policies
(https://developers.google.com/search/docs/essentials/spam-policies) and Bing's Webmaster
Guidelines, and can lead to manual actions or deindexing. Mark paid or sponsored links with
rel="sponsored" and user-generated links with rel="ugc".
"""

OPPORTUNITIES: list[tuple[str, str]] = [
    (
        "Unlinked brand mentions",
        "Ask sites that already mention you to link the mention "
        "(`seoforge offpage mentions`). Highest success rate: they already know you.",
    ),
    (
        "Broken link building",
        "Find dead links on relevant resource pages and suggest your "
        "genuinely equivalent page as a replacement (`seoforge offpage broken-links`).",
    ),
    (
        "Original data and research",
        "Publish surveys, benchmarks or datasets others will cite; "
        "these earn links and AI citations naturally.",
    ),
    (
        "Free tools and templates",
        "Small calculators, checklists or open-source tools attract links from resource pages.",
    ),
    (
        "Expert contributions",
        "Answer journalist queries (e.g. Qwoted, Featured, SourceBottle) "
        "with real expertise; disclose affiliations.",
    ),
    (
        "Partners, suppliers and customers",
        "Ask for a listing on partner/integration/customer pages where the relationship is real.",
    ),
    (
        "Community participation",
        "Help genuinely on Reddit, Stack Exchange, Quora, GitHub or "
        "niche forums; link only when it answers the question (most of those links are nofollow/ugc, "
        "which is fine - they bring visitors and brand mentions).",
    ),
    (
        "Local and industry associations",
        "Chambers of commerce, industry bodies, meetups and events you sponsor or speak at.",
    ),
    ("Podcasts and talks", "Guest appearances usually come with a show-notes link."),
    (
        "Image and quote attribution",
        "Ask sites using your images, charts or quotes without credit to add attribution.",
    ),
    (
        "Digital PR",
        "Pitch newsworthy stories (launches, data, milestones) to relevant "
        "journalists - personalized, never bulk.",
    ),
    (
        "Profile consistency",
        "Complete official profiles (see `seoforge geo entity`); these "
        "help entity recognition more than link equity.",
    ),
]

# Generic, widely used directories. Verify current terms; list only where customers look.
DIRECTORIES: dict[str, list[tuple[str, str]]] = {
    "All businesses": [
        ("Google Business Profile", "https://www.google.com/business/"),
        ("Bing Places for Business", "https://www.bingplaces.com/"),
        ("Apple Business Connect", "https://businessconnect.apple.com/"),
        ("LinkedIn Company Pages", "https://www.linkedin.com/company/setup/new/"),
        ("Crunchbase", "https://www.crunchbase.com/"),
    ],
    "Local businesses": [
        ("Yelp for Business", "https://business.yelp.com/"),
        ("Foursquare for Business", "https://foursquare.com/"),
        ("OpenStreetMap (add your business)", "https://www.openstreetmap.org/"),
    ],
    "Software / SaaS": [
        ("G2", "https://www.g2.com/"),
        ("Capterra", "https://www.capterra.com/vendors/"),
        ("Product Hunt", "https://www.producthunt.com/"),
        ("AlternativeTo", "https://alternativeto.net/"),
        ("SaaSHub", "https://www.saashub.com/"),
    ],
    "Developers / open source": [
        ("GitHub (org + repo topics)", "https://github.com/"),
        ("PyPI / npm package pages", "https://pypi.org/"),
        (
            "Hacker News (Show HN, when genuinely interesting)",
            "https://news.ycombinator.com/showhn.html",
        ),
        ("DEV Community", "https://dev.to/"),
    ],
    "Creators / content": [
        ("Medium (with canonical links)", "https://medium.com/"),
        ("Substack", "https://substack.com/"),
        ("YouTube channel", "https://www.youtube.com/"),
    ],
}


def checklist_markdown() -> str:
    lines = ["# Backlink opportunity checklist", ""]
    lines += [f"- [ ] **{title}** - {why}" for title, why in OPPORTUNITIES]
    lines += [
        "",
        "# Directories worth considering",
        "",
        "Only list where real customers look. Avoid 'submit to 500 directories' services.",
        "",
    ]
    for group, items in DIRECTORIES.items():
        lines += [f"## {group}", ""] + [f"- [{name}]({url})" for name, url in items] + [""]
    lines += ["", ANTI_SPAM_POLICY]
    return "\n".join(lines)
