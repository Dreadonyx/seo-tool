"""Check plugin system.

A check is a function decorated with `@check(...)` that receives an `AuditContext` and yields
`Issue`s. Built-in checks live in `seoforge.checks.*`. Third-party checks register by
exposing a module through the `seoforge.checks` entry-point group, or by listing the module
under `plugins:` in seoforge.yaml.
"""

from __future__ import annotations

import importlib
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any

from seoforge.config import Config
from seoforge.crawler.crawler import CrawlResult
from seoforge.models import Category, Issue, PageData

CheckFn = Callable[["AuditContext"], Iterable[Issue]]


@dataclass(slots=True)
class CheckSpec:
    id: str
    category: Category
    fn: CheckFn
    description: str = ""


REGISTRY: dict[str, CheckSpec] = {}


def check(check_id: str, category: Category, description: str = "") -> Callable[[CheckFn], CheckFn]:
    def decorator(fn: CheckFn) -> CheckFn:
        REGISTRY[check_id] = CheckSpec(check_id, category, fn, description or (fn.__doc__ or ""))
        return fn

    return decorator


@dataclass(slots=True)
class AuditContext:
    config: Config
    crawl: CrawlResult
    extras: dict[str, Any] = field(default_factory=dict)  # PageSpeed results, keyword data...
    _inlinks: dict[str, int] | None = None
    _depths: dict[str, int] | None = None

    @property
    def site(self) -> str:
        return self.crawl.site

    @property
    def pages(self) -> list[PageData]:
        """Indexable-candidate HTML pages (200, not redirects)."""
        return self.crawl.html_pages

    @property
    def all_pages(self) -> list[PageData]:
        return list(self.crawl.pages.values())

    @property
    def inlinks(self) -> dict[str, int]:
        """Count of distinct internal pages linking to each URL (self-links excluded)."""
        if self._inlinks is None:
            counter: Counter[str] = Counter()
            for source, targets in self.crawl.edges.items():
                for target in targets:
                    if target != source:
                        counter[target] += 1
            # Credit redirect targets with links pointing at the redirecting URL.
            for page in self.crawl.pages.values():
                if page.redirect_chain and page.url in counter:
                    counter[page.final_url] += counter[page.url]
            self._inlinks = dict(counter)
        return self._inlinks

    @property
    def click_depths(self) -> dict[str, int]:
        """Shortest link distance from the start URL (BFS over the internal link graph)."""
        if self._depths is None:
            redirects = {p.url: p.final_url for p in self.crawl.pages.values() if p.redirect_chain}
            depths = {self.crawl.start_url: 0}
            frontier = [self.crawl.start_url]
            while frontier:
                nxt: list[str] = []
                for url in frontier:
                    for target in self.crawl.edges.get(url, ()):
                        target = redirects.get(target, target)
                        if target not in depths:
                            depths[target] = depths[url] + 1
                            nxt.append(target)
                frontier = nxt
            self._depths = depths
        return self._depths


def load_plugins(modules: Iterable[str] = ()) -> None:
    """Import built-in check modules, entry-point plugins, and configured plugin modules."""
    from seoforge.checks import BUILTIN_MODULES

    for name in BUILTIN_MODULES:
        importlib.import_module(name)
    for ep in entry_points(group="seoforge.checks"):
        ep.load()
    for name in modules:
        importlib.import_module(name)


def run_checks(ctx: AuditContext) -> list[Issue]:
    load_plugins(ctx.config.plugins)
    disabled = set(ctx.config.disabled_checks)
    issues: list[Issue] = []
    for spec in REGISTRY.values():
        if spec.id in disabled:
            continue
        for issue in spec.fn(ctx):
            if issue.check_id not in disabled:
                issues.append(issue)
    issues.sort(key=lambda i: (i.severity.rank, -i.priority_score))
    return issues
