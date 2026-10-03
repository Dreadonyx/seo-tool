"""Extra analyses run during an audit, after keywords/performance and before checks.

Each enricher stores its result in `ctx.extras[...]` for checks and reports to consume.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from seoforge.checks.base import AuditContext
    from seoforge.http import PoliteClient
    from seoforge.storage import Store

EnricherFn = Callable[["AuditContext", "PoliteClient", "Store", Any], Awaitable[None]]


async def structured_data(
    ctx: AuditContext, client: PoliteClient, store: Store, options: Any
) -> None:
    from seoforge.analysis.structured_data import analyze

    ctx.extras["structured_data"] = analyze(ctx.pages)


async def aeo(ctx: AuditContext, client: PoliteClient, store: Store, options: Any) -> None:
    from seoforge.analysis.aeo import analyze

    ctx.extras["aeo"] = analyze(ctx.pages, ctx.extras.get("keywords"))


async def competitor_gap(
    ctx: AuditContext, client: PoliteClient, store: Store, options: Any
) -> None:
    if not options.competitors:
        return
    from seoforge.analysis.competitors import content_gap

    ctx.extras["keyword_gap"] = await content_gap(client, ctx.pages, options.competitors)


async def autosuggest(ctx: AuditContext, client: PoliteClient, store: Store, options: Any) -> None:
    if not options.suggest:
        return
    from seoforge.analysis.suggest import suggestions

    seeds = list(ctx.config.seed_keywords)
    kw = ctx.extras.get("keywords")
    if not seeds and kw is not None:
        seeds = list(dict.fromkeys(p.primary for p in kw.pages if p.primary))[:5]
    ctx.extras["suggestions"] = await suggestions(client.http, store, seeds)


async def geo(ctx: AuditContext, client: PoliteClient, store: Store, options: Any) -> None:
    from seoforge.geo.analysis import analyze

    ctx.extras["geo"] = await analyze(ctx, client)


ENRICHERS: list[tuple[str, EnricherFn]] = [
    ("Validating structured data", structured_data),
    ("Analyzing answer-engine readiness", aeo),
    ("Comparing competitor content", competitor_gap),
    ("Fetching Autosuggest ideas", autosuggest),
    ("Analyzing AI crawler access and citation-friendliness", geo),
]
