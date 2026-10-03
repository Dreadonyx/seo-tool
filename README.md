# SEOForge

**Free, open-source CLI that audits and optimizes websites for search engines (SEO), answer
engines (AEO) and AI / generative engines (GEO) - and submits them to every index it
legitimately can.**

No paid APIs. No accounts required for the core audit. MIT licensed.

> **Honesty first.** No tool can guarantee rankings, indexing of every page or keyword, or that
> any AI system will know, cite or recommend your site. SEOForge maximizes *eligibility,
> discoverability and citation likelihood*, labels every heuristic as an estimate, cites the
> guideline behind every finding, and never uses spam tactics. See
> [What SEOForge cannot do](#what-seoforge-cannot-do).

```
seoforge audit https://example.com          # crawl + prioritized HTML/Markdown/JSON report
seoforge fix https://example.com            # robots.txt, sitemap, llms.txt, JSON-LD, redirects...
seoforge diagnose https://example.com/page  # why isn't this URL indexed?
```

## What it does

| Area | Highlights |
|---|---|
| **Crawler** | Async, robots.txt-aware (RFC 9309 wildcards + longest match), per-host rate limit and `Crawl-delay`, redirect-chain capture, SQLite cache, resumable (`--resume`), optional JavaScript rendering with Playwright, site graph (click depth, inlinks, orphans) |
| **Technical SEO** | Status codes, broken links, redirect chains/loops, soft 404s (site-wide probe + heuristics), HTTPS/HSTS/mixed content, www/http canonicalization, robots.txt validity, sitemap validity and consistency, canonicals, meta robots / X-Robots-Tag, hreflang, viewport, lang, images, compression, security headers, duplicate and near-duplicate content (SimHash) |
| **Performance** | Core Web Vitals field data (CrUX via the free PageSpeed Insights API) and lab data (PageSpeed / local Lighthouse CLI) |
| **On-page & keywords** | Titles, meta descriptions, headings, thin content, JS-only content, anchors, internal linking, Open Graph; keyword extraction (TF-IDF, YAKE, n-grams), rule-based intent, topic clustering (local sentence-transformers if installed, else TF-IDF), cannibalization, competitor content gap, opt-in cached Google Autosuggest ideas, keyword-to-page map |
| **Structured data** | JSON-LD extraction and validation (required/recommended properties, nested entities, ISO dates, `@graph`, FAQ visibility policy); generators for Organization, WebSite (+SearchAction), WebPage, Article, Product, FAQPage, HowTo, BreadcrumbList, Person with `sameAs` |
| **AEO** | Question-style headings, 40-60 word answer blocks, answer drafts trimmed from *your own* text, FAQ/definition/steps/table detection, E-E-A-T checks (author, author page, dates, citations, About/Contact/Privacy) |
| **GEO** | Per-bot robots.txt policy for 15 AI crawlers/tokens (GPTBot, OAI-SearchBot, ChatGPT-User, ClaudeBot, Claude-SearchBot, Claude-User, PerplexityBot, Perplexity-User, Google-Extended, Applebot-Extended, CCBot, Bytespider, Meta-ExternalAgent, Amazonbot, cohere-ai); `/llms.txt`, `/llms-full.txt` and Markdown mirrors; entity fact sheet; sameAs graph and brand-consistency checklist; Wikidata search + QuickStatements draft; citation-friendliness score; Common Crawl presence; AI-visibility tracker (SQLite) |
| **Indexing** | Sitemap generator, IndexNow (key file + verified batch submission of changed URLs), Google Search Console API (sitemap submit, quota-aware URL Inspection), Bing Webmaster API, engine coverage table, "why isn't this indexed?" diagnostic |
| **Off-page** | Opportunity checklist, curated directory list, robots-aware broken-link finder with Wayback lookups, unlinked brand-mention finder (Hacker News + Wikipedia APIs), strict anti-spam policy |
| **Reporting** | Prioritized issues (Critical/High/Medium/Low) with impact, effort, exact fix, source and evidence; standalone HTML dashboard + Markdown + JSON; 30/60/90-day plan; "what this tool cannot do" section |
| **`seoforge fix`** | Ready-to-paste robots.txt, sitemap.xml, llms.txt, JSON-LD, meta tags, security headers and redirects for nginx, Apache, Vercel, Netlify and Cloudflare. Applies to a *local* directory only after a diff preview and per-file confirmation |

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/Dreadonyx/seoforge && cd seoforge
python -m venv .venv && source .venv/bin/activate
pip install -e .
# Optional extras:
playwright install chromium        # JavaScript rendering (--render)
pip install -e ".[google]"         # Search Console via service account
pip install -e ".[ml]"             # local semantic clustering (large: installs PyTorch)
npm install -g lighthouse          # local Lighthouse lab runs (--lighthouse)
```

Or with Docker:

```bash
docker build -t seoforge .                              # add --build-arg WITH_BROWSER=1 for --render
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/work" seoforge audit https://example.com
```

## Quickstart

```bash
seoforge init                                   # writes an example seoforge.yaml (optional)
seoforge audit https://example.com              # report in ./seoforge-report/report.html
seoforge audit https://example.com --render --max-pages 1000 --competitor https://rival.com/page
seoforge fix https://example.com                # files in ./seoforge-fixes (see INDEX.md)
seoforge fix https://example.com --apply-to ./public   # diff + confirm, then write locally
seoforge diagnose https://example.com/missing-page --crawl-pages 200
seoforge geo bots https://example.com           # which AI crawlers can access the site
```

## Commands

| Command | Purpose |
|---|---|
| `audit URL` | Crawl and report. Options: `--max-pages`, `--depth`, `--delay`, `--concurrency`, `--render`, `--resume`, `--cached`, `--check-external`, `--competitor URL` (repeatable), `--suggest`, `--lighthouse`, `--no-pagespeed`, `--format html/md/json`, `--fail-on critical/high/medium/low` |
| `fix URL` | Generate fix files. `--ai-policy allow-all/search-only/deny-all`, `--redirect-map old_new.csv`, `--apply-to DIR [--yes]` |
| `diagnose URL` | Robots, status, redirects, noindex, canonical, rendering, soft 404, sitemap, internal links, optional `--gsc` URL Inspection |
| `geo bots / llms / entity / commoncrawl` | AI crawler access table; llms.txt + mirrors only; entity + Wikidata; Common Crawl presence |
| `visibility init / add / prompts / log / import / run / report` | AI-visibility tracker (see below) |
| `index engines / indexnow-key / indexnow / gsc-sitemap / gsc-inspect / bing` | Submissions. All ask for confirmation; all support `--dry-run` |
| `offpage checklist / policy / broken-links / mentions` | Ethical link-building helpers |

### AI-visibility tracker

AI assistants have no free, permitted API for "does this assistant mention my brand", and
automating their consumer apps violates their terms. So the tracker is a log:

```bash
seoforge visibility init                                   # prompts from entity.name/category/city
seoforge visibility add "best kanban app for small teams"
seoforge visibility prompts
seoforge visibility log 3 perplexity --mentioned --cited-url https://example.com/guide
seoforge visibility import answers.csv                     # prompt,engine,date,mentioned,cited_url,position,notes
seoforge visibility run gemini --cmd "python my_gemini_free_tier.py {prompt}"   # your own permitted tool
seoforge visibility report --json visibility.json
```

`run` executes *your* command once per prompt (no shell; `{prompt}` is passed as one
argument) and detects brand mentions and links to your domain in its output.

## Configuration (`seoforge.yaml`)

Every field is optional; run `seoforge init` for a commented example. API keys are read from
environment variables, never from the YAML.

```yaml
site: https://example.com
crawl: {max_pages: 500, delay_seconds: 0.5, concurrency: 4, render_js: false, exclude: ["/wp-admin"]}
entity:
  name: Example Inc.
  description: One factual sentence about what you do.
  category: project management software
  city: Chennai
  founded: "2019"
  same_as: [https://github.com/example, https://www.linkedin.com/company/example]
geo:
  ai_bot_preset: search-only        # allow-all | search-only | deny-all | custom
  ai_bots: {CCBot: deny}            # per-bot overrides
competitors: [https://competitor.example/pricing]
seed_keywords: [project management]
report: {output_dir: seoforge-report, fail_on: never}
disabled_checks: [deep-pages]
plugins: [mycompany.seoforge_checks]
```

`search-only` (the default) allows AI search and user-initiated fetchers - so answers can cite
and link you - and blocks training crawlers. Allowed bots inherit your `*` rules, so private
paths stay private.

## Free API keys

All optional; the audit works without any of them.

**PageSpeed Insights (Core Web Vitals)** - works without a key at low volume. For a higher
free quota: Google Cloud Console → create a project → *APIs & Services* → enable **PageSpeed
Insights API** → *Credentials* → **Create API key**. Then `export PAGESPEED_API_KEY=...`.

**Google Search Console** (sitemap submission, URL Inspection):
1. Verify your site in [Search Console](https://search.google.com/search-console).
2. Google Cloud Console → enable the **Google Search Console API**.
3. Either: create a **service account**, download its JSON key, `export
   GSC_SERVICE_ACCOUNT_FILE=/path/key.json`, `pip install -e ".[google]"`, and add the
   service account's email under Search Console → *Settings → Users and permissions* (Full
   permission; Owner if sitemap submission is refused).
   Or: `gcloud auth application-default login --scopes=https://www.googleapis.com/auth/webmasters,https://www.googleapis.com/auth/cloud-platform`
   then `export GSC_ACCESS_TOKEN=$(gcloud auth application-default print-access-token)`.
4. Quotas (enforced locally): URL Inspection 2,000/day and 600/minute per property.

**Bing Webmaster Tools**: verify the site at [bing.com/webmasters](https://www.bing.com/webmasters)
(you can import from Search Console) → *Settings → API access* → generate an **API key** →
`export BING_WEBMASTER_API_KEY=...`.

**IndexNow** (Bing, Yandex, Seznam.cz, Naver, Yep): `seoforge index indexnow-key`, upload
the generated `<key>.txt` to your site root, `export INDEXNOW_KEY=<key>`, then
`seoforge index indexnow https://example.com` (submits only URLs whose content changed).

## GitHub Action

Audit every deploy and upload the report as an artifact (see `docs/github-action.md`):

```yaml
- uses: Dreadonyx/seoforge@main
  with:
    url: https://example.com
    fail-on: critical
    pagespeed-api-key: ${{ secrets.PAGESPEED_API_KEY }}
```

## Plugins

Checks are plain functions registered with `@check`. Ship them in any module and list it under
`plugins:` or expose it via the `seoforge.checks` entry-point group. See
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and `tests/plugins/demo_plugin.py`.

## Ethics

- Obeys robots.txt on every request and redirect hop (including competitor, mention and
  broken-link checks), rate-limits per host and honours `Crawl-delay`.
- Never cloaks, generates doorway pages, fake reviews, or spam links; never scrapes search
  result pages or consumer AI apps.
- Never uses Google's Indexing API (it is only for JobPosting and BroadcastEvent pages).
- Generated markup and copy use only data from your pages or `seoforge.yaml`; anything unknown
  is left as a TODO rather than invented.
- Never modifies a site without a diff preview and confirmation, and only in a local directory.

## Assumptions

- "Submit to every index" means the legitimate channels that exist: Google Search Console,
  Bing Webmaster Tools, IndexNow, sitemaps and robots.txt. Other engines either use those
  indexes or offer no submission (listed by `seoforge index engines`).
- Keyword volumes are omitted rather than estimated, because no free, reliable source exists.
- The default AI crawler policy is `search-only`; change it in `seoforge.yaml`.
- The crawler identifies itself as `SEOForge/<version>` and matches robots.txt groups for
  `SEOForge` (falling back to `*`).
- Response cache is written on every crawl but only read with `--resume` / `--cached`, so a
  normal audit always reflects the live site.
- Thresholds such as "title > 60 characters", "under 200 words" or "40-60 word answers" are
  common heuristics, not search engine rules; findings based on them are labelled estimates.

## What SEOForge cannot do

- Guarantee rankings, indexing of any page, or traffic.
- Make any LLM know, cite or recommend your site; it can only make your content easier to
  retrieve, quote and attribute.
- Provide search volume, keyword difficulty or a full backlink index (use Search Console and
  Bing Webmaster Tools "Links" reports for your real backlinks).
- Enforce robots.txt: bots that ignore it must be blocked at the server/CDN/WAF.
- Promise anything from llms.txt: it is a community proposal that major AI providers have not
  confirmed using.
- Bring back FAQ/HowTo rich results in Google (restricted/removed in 2023), or the sitelinks
  search box (retired in 2024).
- Render pages exactly like Googlebot; headless Chromium is a close approximation.
- Measure Core Web Vitals field data for low-traffic URLs (CrUX has no data for them).

## Roadmap

- Incremental crawls driven by sitemap `lastmod` and HTTP conditional requests
- Log-file analysis (real Googlebot/AI-bot hits vs. robots policy)
- Search Console Search Analytics import (queries, CTR, position) into the keyword map
- More rich-result validators (Event, JobPosting, Recipe, VideoObject details) and SHACL export
- Multi-language keyword extraction (stopword lists beyond English)
- Report diffing between audits and trend charts
- WordPress / static-site generator integrations for `fix --apply-to`

## Development

```bash
pip install -e ".[dev]" && playwright install chromium
pre-commit install
pytest -q                      # spins up a local test site with planted issues
ruff check src tests && ruff format --check src tests && mypy
python tests/serve_site.py 8765 & seoforge audit http://127.0.0.1:8765 --no-pagespeed --delay 0
```

## License

MIT - see [LICENSE](LICENSE).
