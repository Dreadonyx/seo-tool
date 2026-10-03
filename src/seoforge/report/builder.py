"""Turns raw issues into a prioritized report with a 30/60/90-day plan."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from seoforge import __version__
from seoforge.checks.base import AuditContext
from seoforge.models import Effort, Issue, Severity
from seoforge.report.limitations import DISCLAIMER, LIMITATIONS, SCOPE_NOTES

STANDING_TASKS = {
    "30": [
        "Verify the site in Google Search Console and Bing Webmaster Tools (free) and submit "
        "the sitemap in both (`seoforge index gsc-sitemap`, `seoforge index bing`).",
        "Set up IndexNow (`seoforge index indexnow-key`) so Bing, Yandex, Seznam, Naver and Yep "
        "learn about changes within minutes.",
        "Publish robots.txt with an explicit AI-crawler policy and an llms.txt (`seoforge fix`).",
    ],
    "60": [
        "Add or improve structured data for your key page types and validate it in Google's "
        "Rich Results Test and the Schema.org validator.",
        "Rewrite key pages with direct 40-60 word answers under question-style headings "
        "(see AEO findings).",
        "Make your brand entity consistent: same name, logo, description and links on every "
        "profile listed in the entity checklist.",
    ],
    "90": [
        "Create one genuinely useful, linkable asset (original data, tool, or guide) per "
        "content cluster and promote it to relevant communities and publications.",
        "Re-run `seoforge audit` and compare; track AI answers monthly with `seoforge visibility`.",
        "Review Search Console 'Pages' and 'Performance' reports for pages that are crawled "
        "but not indexed, and queries with high impressions but low CTR.",
    ],
}


@dataclass(slots=True)
class Report:
    site: str
    generated_at: str
    stats: dict[str, Any]
    issues: list[Issue]
    plan: dict[str, list[dict[str, Any]]]
    score: int
    extras: dict[str, Any] = field(default_factory=dict)
    disclaimer: str = DISCLAIMER
    limitations: list[str] = field(default_factory=lambda: list(LIMITATIONS))
    scope_notes: list[str] = field(default_factory=lambda: list(SCOPE_NOTES))
    version: str = __version__

    @property
    def severity_counts(self) -> dict[str, int]:
        counts = Counter(i.severity.value for i in self.issues)
        return {s.value: counts.get(s.value, 0) for s in Severity}

    def to_dict(self) -> dict[str, Any]:
        return {
            "site": self.site,
            "generated_at": self.generated_at,
            "version": self.version,
            "score": self.score,
            "score_note": "Heuristic health score (estimate): 100 minus weighted issue penalties.",
            "stats": self.stats,
            "severity_counts": self.severity_counts,
            "issues": [i.to_dict() for i in self.issues],
            "plan": self.plan,
            "extras": self.extras,
            "disclaimer": self.disclaimer,
            "limitations": self.limitations,
            "scope_notes": self.scope_notes,
        }


def health_score(issues: list[Issue], page_count: int) -> int:
    pages = max(page_count, 1)
    penalty = 0.0
    for issue in issues:
        fraction = min(len(issue.urls), pages) / pages if issue.urls else 0.0
        penalty += issue.severity.weight * (0.3 + 0.7 * fraction) / 4
    return max(0, round(100 - penalty))


def build_plan(issues: list[Issue]) -> dict[str, list[dict[str, Any]]]:
    plan: dict[str, list[dict[str, Any]]] = {"30": [], "60": [], "90": []}
    for issue in issues:
        if issue.severity == Severity.INFO:
            continue
        if issue.severity in (Severity.CRITICAL, Severity.HIGH) and issue.effort != Effort.HIGH:
            bucket = "30"
        elif issue.severity in (Severity.HIGH, Severity.MEDIUM):
            bucket = "60"
        else:
            bucket = "90"
        plan[bucket].append(
            {
                "check_id": issue.check_id,
                "title": issue.title,
                "severity": issue.severity.value,
                "effort": issue.effort.value,
                "fix": issue.fix,
            }
        )
    for bucket, tasks in STANDING_TASKS.items():
        plan[bucket].extend(
            {"check_id": "standing", "title": t, "severity": "plan", "effort": "-", "fix": ""}
            for t in tasks
        )
    return plan


def build_report(ctx: AuditContext, issues: list[Issue]) -> Report:
    crawl = ctx.crawl
    html_pages = ctx.pages
    stats = {
        "urls_crawled": len(crawl.pages),
        "html_pages": len(html_pages),
        "indexable_pages": sum(1 for p in html_pages if p.is_indexable),
        "noindex_pages": sum(1 for p in html_pages if p.noindex),
        "redirects": sum(1 for p in crawl.pages.values() if p.redirect_chain),
        "errors_4xx": sum(1 for p in crawl.pages.values() if 400 <= p.status < 500),
        "errors_5xx": sum(1 for p in crawl.pages.values() if p.status >= 500),
        "blocked_by_robots": len(crawl.blocked),
        "sitemap_urls": len(crawl.sitemaps.urls),
        "avg_response_ms": round(sum(p.elapsed_ms for p in html_pages) / len(html_pages))
        if html_pages
        else 0,
        "avg_word_count": round(sum(p.word_count for p in html_pages) / len(html_pages))
        if html_pages
        else 0,
        "js_rendered": any(p.rendered for p in html_pages),
        "render_error": crawl.render_error,
        "truncated_at_max_pages": crawl.truncated,
        "resumed": crawl.resumed,
    }
    extras: dict[str, Any] = {}
    for key, value in ctx.extras.items():
        if hasattr(value, "to_dict"):
            extras[key] = value.to_dict()
        elif isinstance(value, list):
            extras[key] = [v.to_dict() if hasattr(v, "to_dict") else _plain(v) for v in value]
        else:
            extras[key] = _plain(value)
    return Report(
        site=crawl.site,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        stats=stats,
        issues=issues,
        plan=build_plan(issues),
        score=health_score(issues, len(html_pages)),
        extras=extras,
    )


def _plain(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(value)
    return value
