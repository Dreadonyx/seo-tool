"""robots.txt parser following RFC 9309 (wildcards, longest match, allow-wins-on-tie).

The stdlib `urllib.robotparser` does not implement `*`/`$` wildcards or longest-match
precedence, so it gives wrong answers for many real sites and for AI bot rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import unquote, urlsplit

KNOWN_DIRECTIVES = {
    "user-agent",
    "allow",
    "disallow",
    "sitemap",
    "crawl-delay",
    "host",
    "clean-param",
    "noindex",
    "content-signal",
}


@dataclass(slots=True)
class Rule:
    allow: bool
    path: str

    @property
    def specificity(self) -> int:
        return len(self.path)


@dataclass(slots=True)
class Group:
    agents: list[str] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    crawl_delay: float | None = None


@dataclass(slots=True)
class RobotsWarning:
    line: int
    message: str


@lru_cache(maxsize=4096)
def _pattern_to_regex(path: str) -> re.Pattern[str]:
    anchored = path.endswith("$")
    body = path[:-1] if anchored else path
    regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
    return re.compile(regex + ("$" if anchored else ""))


def _normalize_path(path: str) -> str:
    # Compare in percent-decoded form except for reserved characters (RFC 9309 2.2.2).
    return unquote(path).replace(" ", "%20")


def _matches(rule_path: str, path: str) -> bool:
    if not rule_path:
        return False
    return _pattern_to_regex(_normalize_path(rule_path)).match(path) is not None


class RobotsTxt:
    def __init__(self, text: str = "", url: str | None = None, status: int | None = 200) -> None:
        self.url = url
        self.status = status
        self.raw = text
        self.groups: list[Group] = []
        self.sitemaps: list[str] = []
        self.warnings: list[RobotsWarning] = []
        self.content_signals: list[str] = []
        self._parse(text)

    # RFC 9309 2.3.1.3/2.3.1.4: 4xx => no restrictions, 5xx/unreachable => assume full disallow.
    @property
    def unreachable(self) -> bool:
        return self.status is None or self.status >= 500

    @property
    def missing(self) -> bool:
        return self.status is not None and 400 <= self.status < 500

    def _parse(self, text: str) -> None:
        current: Group | None = None
        last_was_agent = False
        if len(text.encode("utf-8", "ignore")) > 500 * 1024:
            self.warnings.append(RobotsWarning(0, "File exceeds 500 KiB; Google ignores the rest."))
        for lineno, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if ":" not in line:
                self.warnings.append(RobotsWarning(lineno, f"Line has no ':' separator: {line!r}"))
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            key = key.lower()
            if key not in KNOWN_DIRECTIVES:
                self.warnings.append(RobotsWarning(lineno, f"Unknown directive {key!r}"))
                continue
            if key == "sitemap":
                self.sitemaps.append(value)
                continue
            if key == "content-signal":
                self.content_signals.append(value)
                continue
            if key == "user-agent":
                if current is None or not last_was_agent:
                    current = Group()
                    self.groups.append(current)
                current.agents.append(value.lower())
                last_was_agent = True
                continue
            last_was_agent = False
            if current is None:
                self.warnings.append(
                    RobotsWarning(lineno, f"{key!r} appears before any user-agent")
                )
                continue
            if key in ("allow", "disallow"):
                if value and not value.startswith(("/", "*")):
                    self.warnings.append(
                        RobotsWarning(lineno, f"Path should start with '/': {value!r}")
                    )
                current.rules.append(Rule(allow=key == "allow", path=value))
            elif key == "crawl-delay":
                try:
                    current.crawl_delay = float(value)
                except ValueError:
                    self.warnings.append(RobotsWarning(lineno, f"Invalid crawl-delay {value!r}"))
            elif key == "noindex":
                self.warnings.append(
                    RobotsWarning(
                        lineno,
                        "'noindex' in robots.txt is unsupported by Google "
                        "since 2019; use meta robots or X-Robots-Tag.",
                    )
                )

    def _groups_for(self, user_agent: str) -> list[Group]:
        token = user_agent.split("/")[0].strip().lower()
        exact = [g for g in self.groups if token in g.agents]
        if exact:
            return exact
        return [g for g in self.groups if "*" in g.agents]

    def has_group_for(self, user_agent: str) -> bool:
        token = user_agent.split("/")[0].strip().lower()
        return any(token in g.agents for g in self.groups)

    def matching_rule(self, user_agent: str, url: str) -> Rule | None:
        parts = urlsplit(url)
        path = _normalize_path((parts.path or "/") + (f"?{parts.query}" if parts.query else ""))
        best: Rule | None = None
        for group in self._groups_for(user_agent):
            for rule in group.rules:
                if not _matches(rule.path, path):
                    continue
                if (
                    best is None
                    or rule.specificity > best.specificity
                    or (rule.specificity == best.specificity and rule.allow and not best.allow)
                ):
                    best = rule
        return best

    def can_fetch(self, user_agent: str, url: str) -> bool:
        if urlsplit(url).path == "/robots.txt":
            return True
        if self.unreachable:
            return False
        if self.missing:
            return True
        rule = self.matching_rule(user_agent, url)
        return rule is None or rule.allow

    def crawl_delay(self, user_agent: str) -> float | None:
        delays = [g.crawl_delay for g in self._groups_for(user_agent) if g.crawl_delay is not None]
        return max(delays) if delays else None

    def blocks_everything(self, user_agent: str) -> bool:
        return not self.can_fetch(user_agent, f"https://x/{'a' * 3}") and not self.can_fetch(
            user_agent, "https://x/"
        )
