"""The honest part of every report."""

DISCLAIMER = (
    "SEOForge maximizes eligibility, discoverability and citation likelihood. No tool can "
    "guarantee rankings, indexing of every page or keyword, or that any AI system will know, "
    "cite, or recommend your site. Search engines and AI providers decide that themselves."
)

LIMITATIONS = [
    "No ranking guarantees: rankings depend on competition, query intent, links, and "
    "hundreds of signals that only search engines see.",
    "Indexing is never guaranteed. Submitting a URL (sitemap, IndexNow, Bing API, GSC) only "
    "requests a crawl; engines choose what to index.",
    "No tool can make an LLM 'know' your site. Training data cut-offs, retrieval systems and "
    "citation choices are controlled by each AI provider. GEO work raises the odds of being "
    "retrieved and quoted; it does not force it.",
    "Google's Indexing API is only for JobPosting and BroadcastEvent (livestream) pages. "
    "SEOForge does not use it for anything else, and neither should you.",
    "Search volumes and keyword difficulty are not provided: there is no free, reliable source. "
    "Keywords come from your own content, competitor pages you supply, and (opt-in) Google "
    "Autosuggest, which reflects popularity but not volume.",
    "Backlink data is limited to what free sources expose. Use Google Search Console and Bing "
    "Webmaster Tools 'Links' reports for your real backlink profile.",
    "Performance numbers from this machine (response time) are estimates. Core Web Vitals field "
    "data comes from the Chrome UX Report via PageSpeed Insights and exists only for URLs with "
    "enough real-user traffic.",
    "Heuristic findings (thin content, title length, near-duplicates, citation-friendliness, "
    "intent) are labelled as estimates. Use judgement: they flag pages to review, not verdicts.",
    "AI visibility tracking relies on answers you record manually or fetch through tools you "
    "are allowed to use. SEOForge does not scrape consumer AI apps, which their terms forbid.",
    "llms.txt is a community proposal (llmstxt.org). Major AI providers have not confirmed "
    "they use it; it is cheap to publish and harmless, nothing more is promised.",
    "FAQ rich results are limited to well-known government and health sites, and HowTo rich "
    "results were removed from Google (Aug/Sep 2023). The markup is still valid schema.org and "
    "can help other engines and answer extraction.",
    "robots.txt is a request, not an enforcement mechanism. Crawlers that ignore it must be "
    "blocked at the server/CDN/WAF level.",
    "JavaScript rendering uses headless Chromium; it approximates, but is not identical to, "
    "how Googlebot renders pages.",
]

SCOPE_NOTES = [
    "Chrome, Firefox, Edge and Safari are browsers, not search engines - there is nothing to "
    "'submit' to them.",
    "DuckDuckGo, Yahoo and Ecosia rely heavily on Bing's index (plus their own sources), so "
    "Bing Webmaster Tools and IndexNow cover much of that reach.",
    "Brave Search runs its own index and has no submission console; it discovers pages through "
    "links and its own crawling.",
]
