"""Core Web Vitals findings from PageSpeed Insights (field + lab) and Lighthouse (lab)."""

from __future__ import annotations

from collections.abc import Iterator

from seoforge import sources
from seoforge.analysis.performance import THRESHOLDS, PerfResult, rate
from seoforge.checks.base import AuditContext, check
from seoforge.models import Category, Effort, Issue, Severity

P = Category.PERFORMANCE
FIXES = {
    "LCP": "Optimize the largest element: compress/resize hero images (AVIF/WebP), preload it, "
    "avoid lazy-loading it, reduce server response time and render-blocking CSS/JS.",
    "INP": "Break up long JavaScript tasks, defer non-critical scripts, reduce third-party tags, "
    "and avoid heavy work in input handlers.",
    "CLS": "Reserve space for images/ads/embeds (width/height or aspect-ratio), avoid inserting "
    "content above existing content, use font-display: optional/swap with size-adjust.",
}


@check("core-web-vitals", P)
def core_web_vitals(ctx: AuditContext) -> Iterator[Issue]:
    results: list[PerfResult] = ctx.extras.get("performance", [])
    for metric in ("LCP", "INP", "CLS"):
        poor: dict[str, float] = {}
        meh: dict[str, float] = {}
        for r in results:
            if metric in r.field_data:
                bucket = (
                    poor
                    if r.field_categories[metric] == "poor"
                    else (meh if r.field_categories[metric] == "needs-improvement" else None)
                )
                if bucket is not None:
                    bucket[r.url] = r.field_data[metric]
        for bucket, sev, label in (
            (poor, Severity.HIGH, "poor"),
            (meh, Severity.MEDIUM, "needs improvement"),
        ):
            if bucket:
                yield Issue(
                    f"cwv-{metric.lower()}-{label.replace(' ', '-')}",
                    f"{metric} is '{label}' for real users on {len(bucket)} URL(s)",
                    sev,
                    P,
                    f"Chrome UX Report field data (75th percentile, mobile) via PageSpeed Insights. "
                    f"Thresholds: good <= {_fmt(metric, 0)}, poor > {_fmt(metric, 1)}.",
                    FIXES[metric],
                    effort=Effort.MEDIUM,
                    urls=sorted(bucket),
                    evidence=bucket,
                    source=sources.CORE_WEB_VITALS,
                )
    low_lab = {
        f"{r.url} ({r.tool})": round(r.performance_score)
        for r in results
        if r.performance_score is not None and r.performance_score < 50
    }
    if low_lab:
        yield Issue(
            "lab-performance-low",
            f"Lighthouse performance score below 50 on {len(low_lab)} run(s)",
            Severity.MEDIUM,
            P,
            "Lab scores are simulated (throttled mobile) and vary between runs; use them to "
            "diagnose, and field data (above) to judge real users.",
            "Open the Lighthouse report's 'Opportunities' section and address the top items.",
            effort=Effort.MEDIUM,
            urls=sorted({k.split(" (")[0] for k in low_lab}),
            evidence=low_lab,
            source=sources.PAGESPEED_API,
            estimate=True,
        )
    lab_issues = {
        r.url: {m: v for m, v in r.lab.items() if m in ("LCP", "CLS") and rate(m, v) == "poor"}
        for r in results
        if not r.field_data
    }
    lab_issues = {k: v for k, v in lab_issues.items() if v}
    if lab_issues:
        yield Issue(
            "lab-cwv-poor",
            f"Lab LCP/CLS are poor on {len(lab_issues)} URL(s) (no field data)",
            Severity.MEDIUM,
            P,
            "No Chrome UX Report data exists for these URLs (too little traffic), so lab metrics "
            "are the best available estimate.",
            FIXES["LCP"],
            effort=Effort.MEDIUM,
            urls=sorted(lab_issues),
            evidence=lab_issues,
            source=sources.CORE_WEB_VITALS,
            estimate=True,
        )
    errors = {r.url: r.error for r in results if r.error}
    if errors:
        yield Issue(
            "perf-measurement-failed",
            "Some performance measurements failed",
            Severity.INFO,
            P,
            "PageSpeed/Lighthouse could not measure these URLs.",
            "Set PAGESPEED_API_KEY (free) to raise quota, or install lighthouse locally.",
            urls=sorted(errors),
            evidence=errors,
            source=sources.PAGESPEED_API,
        )


def _fmt(metric: str, idx: int) -> str:
    v = THRESHOLDS[metric][idx]
    return f"{v} ms" if metric != "CLS" else str(v)
