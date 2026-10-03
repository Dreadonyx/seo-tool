"""GEO analysis run during audits: AI crawler access, citation-friendliness, entity signals."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from seoforge.analysis.aeo import AEOReport
from seoforge.checks.base import AuditContext
from seoforge.geo.ai_bots import BotAccess, current_access, resolve_policy
from seoforge.geo.citation import CitationScore, score_pages
from seoforge.geo.entity import EntityReport
from seoforge.geo.entity import analyze as analyze_entity
from seoforge.http import PoliteClient, RobotsDisallowed


@dataclass(slots=True)
class GeoReport:
    bots: list[BotAccess] = field(default_factory=list)
    desired: dict[str, str] = field(default_factory=dict)
    policy_explicit: bool = False
    citation: list[CitationScore] = field(default_factory=list)
    entity: EntityReport | None = None
    llms_txt_status: int | None = None
    llms_full_status: int | None = None

    @property
    def mismatches(self) -> dict[str, dict[str, str]]:
        out = {}
        for b in self.bots:
            want = self.desired.get(b.token)
            have = "allow" if b.allowed else "deny"
            if want and want != have:
                out[b.token] = {"live": have, "desired": want}
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "bots": [asdict(b) for b in self.bots],
            "desired_policy": self.desired,
            "policy_mismatches": self.mismatches,
            "citation": [c.to_dict() for c in self.citation],
            "entity": self.entity.to_dict() if self.entity else None,
            "llms_txt_status": self.llms_txt_status,
            "llms_full_status": self.llms_full_status,
        }


async def _status(client: PoliteClient, url: str) -> int | None:
    """HTTP status of a plain-text file; an HTML 200 is a soft-404 page, reported as 404."""
    try:
        result = await client.fetch(url)
    except RobotsDisallowed:
        return None
    if result.error:
        return None
    if result.status == 200 and "html" in result.headers.get("content-type", ""):
        return 404
    return result.status


async def analyze(ctx: AuditContext, client: PoliteClient) -> GeoReport:
    geo = ctx.config.geo
    report = GeoReport()
    report.policy_explicit = bool({"ai_bot_preset", "ai_bots"} & geo.model_fields_set)
    report.desired = resolve_policy(geo.ai_bot_preset, geo.ai_bots)
    report.bots = current_access(ctx.crawl.robots, ctx.site, [t for t in geo.ai_bots if t])
    aeo: AEOReport | None = ctx.extras.get("aeo")
    report.citation = score_pages(ctx.pages, {p.url: p for p in aeo.pages} if aeo else {})
    report.entity = analyze_entity(ctx.crawl, ctx.config.entity)
    # An HTML 200 for /llms.txt is the soft-404 page, not a real llms.txt.
    report.llms_txt_status = await _status(client, f"{ctx.site}/llms.txt")
    report.llms_full_status = await _status(client, f"{ctx.site}/llms-full.txt")
    return report
