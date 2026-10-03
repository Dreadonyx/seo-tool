"""Keyword findings: cannibalization and topical focus (data comes from analysis.keywords)."""

from __future__ import annotations

from collections.abc import Iterator

from seoforge import sources
from seoforge.analysis.keywords import KeywordReport
from seoforge.checks.base import AuditContext, check
from seoforge.models import Category, Effort, Issue, Severity

K = Category.KEYWORDS


@check("keyword-cannibalization", K)
def cannibalization(ctx: AuditContext) -> Iterator[Issue]:
    report: KeywordReport | None = ctx.extras.get("keywords")
    if report is None or not report.cannibalization:
        return
    yield Issue(
        "keyword-cannibalization",
        f"{len(report.cannibalization)} keyword(s) targeted by more than one page",
        Severity.MEDIUM,
        K,
        "Several pages focus on the same phrase (by extracted primary keyword or near-identical "
        "titles), so they may compete with each other and none ranks as well as one strong page.",
        "For each group pick one primary page; merge or differentiate the others, and link "
        "from them to the primary page with descriptive anchors.",
        effort=Effort.MEDIUM,
        urls=sorted({u for g in report.cannibalization.values() for u in g}),
        evidence=report.cannibalization,
        source=sources.HELPFUL_CONTENT,
        estimate=True,
    )
