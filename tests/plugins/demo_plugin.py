"""Example third-party check used by the plugin tests."""

from collections.abc import Iterator

from seoforge.checks.base import AuditContext, check
from seoforge.models import Category, Issue, Severity


@check("demo-lorem-ipsum", Category.ONPAGE)
def lorem(ctx: AuditContext) -> Iterator[Issue]:
    hits = [p.url for p in ctx.pages if "widget calibration" in p.text.lower()]
    if hits:
        yield Issue(
            "demo-lorem-ipsum",
            "Demo plugin finding",
            Severity.LOW,
            Category.ONPAGE,
            "Found the demo phrase.",
            "Nothing to fix - this is a test plugin.",
            urls=hits,
        )
