"""Audit orchestration: crawl -> analyses -> checks -> report."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from seoforge.analysis import keywords as kw
from seoforge.analysis.performance import measure
from seoforge.checks.base import AuditContext, run_checks
from seoforge.config import Config
from seoforge.crawler.crawler import Crawler, CrawlResult, ProgressFn
from seoforge.http import PoliteClient
from seoforge.report.builder import Report, build_report
from seoforge.storage import Store

StepFn = Callable[[str], None]


@dataclass(slots=True)
class AuditOptions:
    resume: bool = False
    cached: bool = False
    pagespeed: bool = True
    lighthouse: bool = False
    suggest: bool = False
    competitors: list[str] = field(default_factory=list)


async def run_audit(
    url: str,
    config: Config,
    options: AuditOptions | None = None,
    *,
    progress: ProgressFn | None = None,
    step: StepFn | None = None,
    store: Store | None = None,
    client: PoliteClient | None = None,
) -> tuple[Report, AuditContext]:
    options = options or AuditOptions()
    notify = step or (lambda _msg: None)
    own_store = store is None
    store = store or Store(config.db_path)
    own_client = client is None
    client = client or PoliteClient(
        config.crawl, store, read_cache=options.resume or options.cached
    )
    try:
        notify("Crawling")
        crawl: CrawlResult = await Crawler(
            config.crawl, store, client=client, progress=progress
        ).crawl(url, resume=options.resume, cached=options.cached)
        ctx = AuditContext(config=config, crawl=crawl)
        await enrich(ctx, client, store, options, notify)
        notify("Running checks")
        issues = run_checks(ctx)
        return build_report(ctx, issues), ctx
    finally:
        if own_client:
            await client.aclose()
        if own_store:
            store.close()


async def enrich(
    ctx: AuditContext, client: PoliteClient, store: Store, options: AuditOptions, notify: StepFn
) -> None:
    """Run the analyses whose results checks and reports consume (via ctx.extras)."""
    from seoforge import enrichers

    notify("Extracting keywords")
    ctx.extras["keywords"] = kw.analyze(ctx.pages, brand=ctx.config.entity.name)
    if options.pagespeed or options.lighthouse:
        notify("Measuring Core Web Vitals")
        inlinks = ctx.inlinks
        top = sorted(
            (p for p in ctx.pages if p.is_indexable),
            key=lambda p: (p.url != ctx.crawl.start_url, -inlinks.get(p.url, 0)),
        )[: ctx.config.pagespeed_urls]
        ctx.extras["performance"] = await measure(
            client.http,
            [p.url for p in top],
            ctx.config.api.env("pagespeed_key_env"),
            use_pagespeed=options.pagespeed,
            use_lighthouse=options.lighthouse,
        )
    for name, fn in enrichers.ENRICHERS:
        notify(name)
        await fn(ctx, client, store, options)
