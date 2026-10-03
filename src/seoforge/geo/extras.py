"""GEO files added to `seoforge fix` bundles."""

from __future__ import annotations

from seoforge.analysis.keywords import KeywordReport
from seoforge.checks.base import AuditContext
from seoforge.fix.bundle import FixBundle
from seoforge.generators import llms
from seoforge.geo import entity


def add_geo_files(ctx: AuditContext, bundle: FixBundle) -> None:
    files = llms.generate(ctx.crawl, ctx.config)
    bundle.add(
        "llms.txt", files.llms_txt, "llms.txt map of key pages (llmstxt.org proposal)", "llms.txt"
    )
    bundle.add(
        "llms-full.txt",
        files.llms_full_txt,
        "Full Markdown text of key pages in one file",
        "llms-full.txt",
    )
    for path, md in files.mirrors.items():
        bundle.add(f"markdown/{path}", md, "Markdown mirror (serve at the page URL + .md)", path)

    kw: KeywordReport | None = ctx.extras.get("keywords")
    topics = list(
        dict.fromkeys(
            p.primary
            for p in (kw.pages if kw else [])
            if p.primary and p.intent in ("informational", "commercial", "transactional")
        )
    )[:8]
    report = entity.analyze(ctx.crawl, ctx.config.entity)
    sheet_md, facts = entity.fact_sheet(ctx.crawl, ctx.config.entity, report, topics)
    bundle.add("entity/facts.md", sheet_md, "Entity fact sheet (publish e.g. as /about/facts)")
    bundle.add("entity/entity.json", entity.entity_json(facts), "Entity facts as JSON")
    qs, guide = entity.wikidata_draft(
        ctx.config.entity, ctx.crawl.site, report.same_as, report.name
    )
    bundle.add("entity/wikidata.qs", qs, "Wikidata QuickStatements draft - read the guide first")
    bundle.add("entity/wikidata-guide.md", guide, "Wikidata steps, notability and COI rules")
    bundle.add(
        "entity/brand-checklist.md", brand_checklist(report), "Profile/brand consistency checklist"
    )


def brand_checklist(report: entity.EntityReport) -> str:
    lines = [
        f"# Brand consistency checklist: {report.name or 'your brand'}",
        "",
        "Use the exact same name, logo, one-line description and website URL everywhere.",
        "",
        "| Platform | Status | Why |",
        "|---|---|---|",
    ]
    for platform, (_, why) in entity.PLATFORMS.items():
        url = report.platforms.get(platform)
        lines.append(f"| {platform} | {f'[linked]({url})' if url else 'not in sameAs'} | {why} |")
    if report.name_variants:
        lines += ["", "## Name variants found on your site", ""]
        lines += [f"- `{v}` ({n}x)" for v, n in report.name_variants.items()]
    lines += [
        "",
        "Never buy reviews, followers or listings on link farms. Directories are useful only "
        "when real customers use them.",
    ]
    return "\n".join(lines) + "\n"
