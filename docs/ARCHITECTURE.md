# Architecture

```
                               ┌──────────────────────────────────────┐
                               │  seoforge CLI (typer)                │
                               │  audit · fix · geo · index · offpage │
                               │  visibility · keywords · diagnose    │
                               └──────────────────┬───────────────────┘
                                                  │ seoforge.yaml → Config (pydantic)
                 ┌────────────────────────────────┼──────────────────────────────────┐
                 ▼                                ▼                                  ▼
     ┌───────────────────────┐       ┌────────────────────────┐        ┌──────────────────────────┐
     │ Crawler (async httpx) │       │ Analysis               │        │ Generators (fix)         │
     │ RFC 9309 robots       │       │ keywords: TF-IDF/YAKE/ │        │ robots.txt · sitemap.xml │
     │ rate limit · resumable│       │  n-grams/intent/cluster│        │ llms.txt · llms-full.txt │
     │ redirect chains       │       │ PageSpeed · Lighthouse │        │ JSON-LD · meta · md      │
     │ Playwright renderer   │       │ competitors · suggest  │        │ redirects (5 platforms)  │
     └──────────┬────────────┘       └───────────┬────────────┘        └────────────┬─────────────┘
                │ PageData                       │                                  │ diff preview
                ▼                                ▼                                  ▼ + confirm
     ┌─────────────────────────────────────────────────────────┐        ┌──────────────────────────┐
     │ AuditContext (pages, site graph, robots, sitemaps)      │        │ Indexing (legit only)    │
     └──────────┬──────────────────────────────────────────────┘        │ IndexNow · GSC · Bing    │
                ▼                                                       │ "why not indexed" diag   │
     ┌─────────────────────────────────────────────────────────┐        └──────────────────────────┘
     │ Check registry (plugin system, entry points)            │        ┌──────────────────────────┐
     │ technical · onpage · links · duplicates · structured    │        │ GEO: AI bots · entity ·  │
     │ data · aeo · eeat · geo/citation · keywords             │        │ Wikidata draft · tracker │
     └──────────┬──────────────────────────────────────────────┘        │ Off-page: BLB · mentions │
                ▼ Issue[]                                               └──────────────────────────┘
     ┌─────────────────────────────────────────────────────────┐
     │ Report: prioritize → HTML dashboard / Markdown / JSON   │
     │ 30/60/90 plan · honest limitations                      │
     └─────────────────────────────────────────────────────────┘
     SQLite (.seoforge/seoforge.db): page cache · frontier · autosuggest cache · quotas · AI visibility
```

## Data flow

1. **Crawl** (`crawler/`): `PoliteClient` fetches with per-host throttling, robots.txt
   enforcement on every redirect hop, manual redirect following (to record chains), and a SQLite
   response cache. `Crawler` runs N async workers over a persistent frontier, so `--resume`
   continues an interrupted crawl. Optional Playwright rendering re-parses pages after JS.
2. **Enrich** (`audit.enrich`): keyword extraction, Core Web Vitals, and registered
   enrichers (AEO, GEO, competitor gap...) write into `ctx.extras`.
3. **Check** (`checks/`): each `@check` function receives an `AuditContext` and yields
   `Issue`s with severity, effort, fix, affected URLs, evidence, a source citation, and an
   `estimate` flag for heuristics.
4. **Report** (`report/`): issues are ranked (severity × reach ÷ effort), bucketed into a
   30/60/90-day plan, and rendered to HTML/Markdown/JSON with the limitations section.

## Plugins

Register checks from any importable module:

```python
from seoforge.checks.base import AuditContext, check
from seoforge.models import Category, Issue, Severity

@check("my-check", Category.ONPAGE)
def my_check(ctx: AuditContext):
    for page in ctx.pages:
        if "lorem ipsum" in page.text.lower():
            yield Issue("my-check", "Placeholder text", Severity.HIGH, Category.ONPAGE,
                        "Lorem ipsum found.", "Replace it.", urls=[page.url])
```

Then list the module under `plugins:` in seoforge.yaml, or expose it through the
`seoforge.checks` entry-point group in your package's `pyproject.toml`.
