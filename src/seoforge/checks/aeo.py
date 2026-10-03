"""AEO and E-E-A-T checks."""

from __future__ import annotations

from collections.abc import Iterator

from seoforge import sources
from seoforge.analysis.aeo import AEOReport
from seoforge.analysis.keywords import KeywordReport
from seoforge.checks.base import AuditContext, check
from seoforge.models import Category, Effort, Issue, Severity

A = Category.AEO
E = Category.EEAT


def _report(ctx: AuditContext) -> AEOReport | None:
    return ctx.extras.get("aeo")


@check("aeo-answers", A)
def answers(ctx: AuditContext) -> Iterator[Issue]:
    report = _report(ctx)
    if report is None:
        return
    weak = {
        p.url: [f"{q.question} ({q.words} words)" for q in p.qa if not q.ideal]
        for p in report.pages
        if p.qa and any(not q.ideal for q in p.qa)
    }
    if weak:
        yield Issue(
            "aeo-answer-length",
            f"{len(weak)} page(s) answer questions without a concise 40-60 word answer",
            Severity.MEDIUM,
            A,
            "Answer engines and featured snippets favour a direct, self-contained answer right "
            "under the question heading. 40-60 words is a widely used guideline, not a rule.",
            "Start each answer with a 1-3 sentence direct answer (about 40-60 words), then "
            "expand. Drafts trimmed from your own text are in the AEO tab / report.json.",
            effort=Effort.MEDIUM,
            urls=sorted(weak),
            evidence=weak,
            source=sources.SNIPPET,
            estimate=True,
        )
    kw: KeywordReport | None = ctx.extras.get("keywords")
    intents = {p.url: p.intent for p in kw.pages} if kw else {}
    no_questions = sorted(
        p.url
        for p in report.pages
        if not p.questions and (p.is_article or intents.get(p.url) == "informational")
    )
    if no_questions:
        yield Issue(
            "aeo-no-question-headings",
            f"{len(no_questions)} informational page(s) have no question-style headings",
            Severity.LOW,
            A,
            "Headings phrased as the questions people ask make it easy for answer engines to "
            "match a passage to a query.",
            "Add H2/H3 headings that mirror real questions (see suggested questions per page), "
            "each followed by a direct answer.",
            effort=Effort.MEDIUM,
            urls=no_questions,
            evidence={p.url: p.suggested_questions for p in report.pages if p.url in no_questions},
            source=sources.HELPFUL_CONTENT,
            estimate=True,
        )
    no_def = sorted(
        p.url
        for p in report.pages
        if intents.get(p.url) == "informational" and not p.has_definition
    )
    if no_def:
        yield Issue(
            "aeo-no-definition",
            f"{len(no_def)} informational page(s) lack an opening definition",
            Severity.LOW,
            A,
            "A plain 'X is a ...' sentence near the top is the most commonly extracted snippet "
            "format for 'what is' queries.",
            "Open with a one-sentence definition of the main topic.",
            urls=no_def,
            source=sources.SNIPPET,
            estimate=True,
        )


@check("eeat-site", E)
def eeat_site(ctx: AuditContext) -> Iterator[Issue]:
    report = _report(ctx)
    if report is None:
        return
    site = report.site
    rows = [
        (
            "eeat-no-about",
            site.about,
            Severity.MEDIUM,
            "an About page",
            "Explain who runs the site, their expertise and why users should trust it.",
        ),
        (
            "eeat-no-contact",
            site.contact,
            Severity.MEDIUM,
            "a Contact page",
            "Publish a contact page with real ways to reach you (email, address or form).",
        ),
        (
            "eeat-no-privacy",
            site.privacy,
            Severity.LOW,
            "a Privacy Policy",
            "Publish a privacy policy describing what data you collect and why.",
        ),
    ]
    for cid, found, sev, what, fix in rows:
        if not found:
            yield Issue(
                cid,
                f"No link to {what} was found",
                sev,
                E,
                f"Trust signals such as {what} help users, quality raters and AI systems judge "
                "who stands behind the content.",
                fix,
                urls=[ctx.crawl.start_url],
                source=sources.EEAT,
            )


@check("eeat-pages", E)
def eeat_pages(ctx: AuditContext) -> Iterator[Issue]:
    report = _report(ctx)
    if report is None:
        return
    articles = [p for p in report.pages if p.is_article]
    no_author = sorted(p.url for p in articles if not p.eeat.get("author"))
    if no_author:
        yield Issue(
            "eeat-no-author",
            f"{len(no_author)} article(s) have no identifiable author",
            Severity.MEDIUM,
            E,
            "Bylines with a linked author page show who wrote the content and their experience.",
            "Add a visible byline linking to an author bio page, plus author in Article markup "
            "(and meta name=author).",
            urls=no_author,
            source=sources.EEAT,
        )
    no_date = sorted(p.url for p in articles if not p.eeat.get("date"))
    if no_date:
        yield Issue(
            "eeat-no-date",
            f"{len(no_date)} article(s) show no publish/update date",
            Severity.MEDIUM,
            E,
            "Dates let users and AI systems judge freshness; undated content is often deprioritized "
            "for time-sensitive queries.",
            "Show a visible published/updated date and add datePublished/dateModified to Article markup.",
            urls=no_date,
            source=f"{sources.G}/appearance/publication-dates",
        )
    no_cite = sorted(p.url for p in articles if not p.eeat.get("citations"))
    if no_cite:
        yield Issue(
            "eeat-no-citations",
            f"{len(no_cite)} article(s) cite no external sources",
            Severity.LOW,
            E,
            "Linking to primary sources for facts and statistics supports trustworthiness and "
            "makes passages easier for AI systems to verify and quote.",
            "Link claims and statistics to their original sources.",
            urls=no_cite,
            source=sources.EEAT,
            estimate=True,
        )
