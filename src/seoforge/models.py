"""Core data models shared across the crawler, checks, and reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def weight(self) -> int:
        return {"critical": 100, "high": 40, "medium": 15, "low": 5, "info": 0}[self.value]

    @property
    def rank(self) -> int:
        return ["critical", "high", "medium", "low", "info"].index(self.value)


class Effort(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def cost(self) -> int:
        return {"low": 1, "medium": 2, "high": 4}[self.value]


class Category(StrEnum):
    CRAWL = "crawl"
    TECHNICAL = "technical"
    PERFORMANCE = "performance"
    ONPAGE = "on-page"
    KEYWORDS = "keywords"
    STRUCTURED_DATA = "structured-data"
    AEO = "aeo"
    EEAT = "e-e-a-t"
    GEO = "geo"
    INDEXING = "indexing"
    SECURITY = "security"


@dataclass(slots=True)
class Link:
    url: str
    text: str = ""
    rel: str = ""
    internal: bool = True

    @property
    def nofollow(self) -> bool:
        return "nofollow" in self.rel.lower().split()


@dataclass(slots=True)
class Image:
    src: str
    alt: str | None
    width: str | None = None
    height: str | None = None
    loading: str | None = None


@dataclass(slots=True)
class Heading:
    level: int
    text: str


@dataclass(slots=True)
class Hreflang:
    lang: str
    url: str


@dataclass(slots=True)
class RedirectHop:
    url: str
    status: int


@dataclass(slots=True)
class PageData:
    """Everything the checks need to know about one fetched URL."""

    url: str
    final_url: str
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    redirect_chain: list[RedirectHop] = field(default_factory=list)
    content_type: str = ""
    elapsed_ms: float = 0.0
    size_bytes: int = 0
    depth: int = 0
    error: str | None = None
    # Parsed HTML fields
    title: str | None = None
    titles_count: int = 0
    meta_description: str | None = None
    meta_descriptions_count: int = 0
    meta_robots: str = ""
    canonical: str | None = None
    canonicals_count: int = 0
    lang: str | None = None
    viewport: str | None = None
    charset: str | None = None
    headings: list[Heading] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    hreflangs: list[Hreflang] = field(default_factory=list)
    json_ld: list[str] = field(default_factory=list)  # raw script bodies
    has_microdata: bool = False
    has_rdfa: bool = False
    open_graph: dict[str, str] = field(default_factory=dict)
    twitter: dict[str, str] = field(default_factory=dict)
    meta: dict[str, str] = field(default_factory=dict)  # other <meta name=...>
    text: str = ""
    word_count: int = 0
    paragraphs: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)  # text of block elements (p, li, h*, td...)
    outline: list[tuple[str, str]] = field(default_factory=list)  # (tag, text) in document order
    has_details: bool = False  # <details>/<summary> accordions (common FAQ pattern)
    lists_count: int = 0
    tables_count: int = 0
    times: list[str] = field(default_factory=list)  # <time datetime> values
    mixed_content: list[str] = field(default_factory=list)
    content_hash: str = ""
    simhash: int = 0
    raw_word_count: int | None = None  # word count before JS rendering (if rendered)
    rendered: bool = False
    html: str = ""

    @property
    def is_html(self) -> bool:
        return "html" in self.content_type.lower()

    @property
    def x_robots_tag(self) -> str:
        return self.headers.get("x-robots-tag", "")

    @property
    def robots_directives(self) -> set[str]:
        tokens: set[str] = set()
        for source in (self.meta_robots, self.x_robots_tag):
            for part in source.lower().replace(";", ",").split(","):
                part = part.strip()
                # X-Robots-Tag may be scoped to a user agent: "googlebot: noindex"
                if ":" in part and not part.startswith(("max-", "unavailable_after")):
                    part = part.split(":", 1)[1].strip()
                if part:
                    tokens.add(part)
        return tokens

    @property
    def noindex(self) -> bool:
        d = self.robots_directives
        return "noindex" in d or "none" in d

    @property
    def nofollow(self) -> bool:
        d = self.robots_directives
        return "nofollow" in d or "none" in d

    @property
    def h1s(self) -> list[str]:
        return [h.text for h in self.headings if h.level == 1]

    @property
    def internal_links(self) -> list[Link]:
        return [link for link in self.links if link.internal]

    @property
    def external_links(self) -> list[Link]:
        return [link for link in self.links if not link.internal]

    @property
    def is_indexable(self) -> bool:
        canonical_ok = self.canonical is None or _same_url(self.canonical, self.final_url)
        return self.status == 200 and self.is_html and not self.noindex and canonical_ok


def _same_url(a: str, b: str) -> bool:
    return a.rstrip("/") == b.rstrip("/")


@dataclass(slots=True)
class Issue:
    """One finding. Grouped by `check_id`; `urls` lists every affected page."""

    check_id: str
    title: str
    severity: Severity
    category: Category
    description: str
    fix: str
    impact: str = ""
    effort: Effort = Effort.LOW
    urls: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    source: str | None = None  # citation for the guideline this check is based on
    estimate: bool = False  # True when the finding is a heuristic/estimate

    @property
    def priority_score(self) -> float:
        reach = 1 + min(len(self.urls), 50) / 10
        return self.severity.weight * reach / self.effort.cost

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "title": self.title,
            "severity": self.severity.value,
            "category": self.category.value,
            "description": self.description,
            "impact": self.impact,
            "effort": self.effort.value,
            "fix": self.fix,
            "urls": self.urls,
            "evidence": self.evidence,
            "source": self.source,
            "estimate": self.estimate,
            "priority_score": round(self.priority_score, 1),
        }
