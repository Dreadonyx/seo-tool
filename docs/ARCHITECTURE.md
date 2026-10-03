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

## Folder tree

```
action.yml
Dockerfile
.dockerignore
docs/
  ARCHITECTURE.md
  github-action.md
.github/
  workflows/
    ci.yml
.gitignore
LICENSE
.pre-commit-config.yaml
pyproject.toml
README.md
src/
  seoforge/
    analysis/
      aeo.py
      competitors.py
      __init__.py
      keywords.py
      pagetype.py
      performance.py
      structured_data.py
      suggest.py
    audit.py
    checks/
      aeo.py
      base.py
      crawl.py
      geo.py
      __init__.py
      keywords.py
      onpage.py
      performance.py
      structured_data.py
      technical.py
    cli.py
    config.py
    crawler/
      crawler.py
      __init__.py
      parser.py
      renderer.py
      sitemaps.py
    enrichers.py
    fix/
      bundle.py
      __init__.py
    generators/
      __init__.py
      llms.py
      markdown.py
      meta.py
      redirects.py
      robots.py
      schema.py
      sitemap.py
    geo/
      ai_bots.py
      analysis.py
      citation.py
      commoncrawl.py
      entity.py
      extras.py
      __init__.py
      visibility.py
    http.py
    indexing/
      bing.py
      diagnose.py
      engines.py
      gsc.py
      indexnow.py
      __init__.py
    __init__.py
    models.py
    offpage/
      broken_links.py
      checklist.py
      __init__.py
      mentions.py
    report/
      builder.py
      __init__.py
      limitations.py
      render.py
      templates/
        report.html.j2
        report.md.j2
    robots.py
    sources.py
    storage.py
    urls.py
tests/
  site/                      # local test website with planted SEO problems
  conftest.py
  plugins/
    demo_plugin.py
  serve_site.py
  test_analysis_network.py
  test_audit_integration.py
  test_fix_integration.py
  test_geo.py
  test_indexing_offpage.py
  test_plugins_and_report.py
  unit/
    test_aeo_generators.py
    test_keywords.py
    test_parsing.py
    test_robots.py
    test_structured_data.py
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
