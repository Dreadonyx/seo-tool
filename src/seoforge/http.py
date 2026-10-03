"""Polite async HTTP client: robots.txt enforcement, per-host rate limiting, caching, redirects."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx

from seoforge.config import CrawlConfig
from seoforge.models import RedirectHop
from seoforge.robots import RobotsTxt
from seoforge.storage import CachedResponse, Store

MAX_REDIRECTS = 10


class RobotsDisallowed(Exception):
    """Raised when robots.txt forbids fetching a URL."""


@dataclass(slots=True)
class FetchResult:
    url: str
    final_url: str
    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    chain: list[RedirectHop] = field(default_factory=list)
    elapsed_ms: float = 0.0
    error: str | None = None
    from_cache: bool = False

    @property
    def text(self) -> str:
        charset = "utf-8"
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            charset = ctype.split("charset=", 1)[1].split(";")[0].strip().strip('"') or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


class PoliteClient:
    def __init__(
        self,
        config: CrawlConfig,
        store: Store | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        read_cache: bool = False,
    ) -> None:
        self.config = config
        self.store = store
        # Responses are always written to the cache; reads are opt-in (resume / --cached).
        self.read_cache = read_cache and store is not None
        self._client = httpx.AsyncClient(
            headers={"User-Agent": config.user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=config.timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )
        self._robots: dict[str, RobotsTxt] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._last_request: dict[str, float] = {}

    async def __aenter__(self) -> PoliteClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---- robots.txt -------------------------------------------------------------------------
    async def robots(self, url: str) -> RobotsTxt:
        key = origin(url)
        if key in self._robots:
            return self._robots[key]
        lock = self._robots_locks.setdefault(key, asyncio.Lock())
        async with lock:
            if key not in self._robots:
                robots_url = f"{key}/robots.txt"
                result = await self._fetch_raw(robots_url, follow=True, max_redirects=5)
                if result.error:
                    self._robots[key] = RobotsTxt("", robots_url, status=None)
                else:
                    self._robots[key] = RobotsTxt(result.text, robots_url, status=result.status)
        return self._robots[key]

    async def allowed(self, url: str) -> bool:
        robots = await self.robots(url)
        return robots.can_fetch(self.config.robots_user_agent, url)

    async def _throttle(self, url: str) -> None:
        host = urlsplit(url).netloc
        delay = self.config.delay_seconds
        robots = self._robots.get(origin(url))
        if self.config.respect_crawl_delay and robots is not None:
            delay = max(delay, robots.crawl_delay(self.config.robots_user_agent) or 0.0)
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._last_request.get(host, 0.0) + delay - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request[host] = time.monotonic()

    # ---- fetching ---------------------------------------------------------------------------
    async def _single(self, url: str, method: str = "GET") -> CachedResponse:
        max_age = self.config.cache_ttl_hours * 3600
        if self.read_cache and self.store is not None and method == "GET":
            cached = self.store.get_response(url, max_age)
            if cached is not None:
                return cached
        await self._throttle(url)
        start = time.perf_counter()
        async with self._client.stream(method, url) as resp:
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                total += len(chunk)
                if total > self.config.max_body_bytes:
                    break
                chunks.append(chunk)
            headers = {k.lower(): v for k, v in resp.headers.items()}
            result = CachedResponse(
                url=url,
                status=resp.status_code,
                headers=headers,
                body=b"".join(chunks),
                elapsed_ms=(time.perf_counter() - start) * 1000,
                fetched_at=time.time(),
            )
        if self.store is not None and method == "GET":
            self.store.put_response(result)
        return result

    async def _fetch_raw(
        self,
        url: str,
        *,
        follow: bool = True,
        max_redirects: int = MAX_REDIRECTS,
        method: str = "GET",
    ) -> FetchResult:
        chain: list[RedirectHop] = []
        current = url
        try:
            for _ in range(max_redirects + 1):
                resp = await self._single(current, method)
                location = resp.headers.get("location")
                if follow and resp.status in (301, 302, 303, 307, 308) and location:
                    chain.append(RedirectHop(current, resp.status))
                    nxt = urljoin(current, location)
                    if nxt in {h.url for h in chain}:
                        return FetchResult(
                            url,
                            nxt,
                            resp.status,
                            resp.headers,
                            b"",
                            chain,
                            resp.elapsed_ms,
                            error="redirect loop",
                        )
                    current = nxt
                    continue
                return FetchResult(
                    url, current, resp.status, resp.headers, resp.body, chain, resp.elapsed_ms
                )
            return FetchResult(url, current, 0, {}, b"", chain, error="too many redirects")
        except httpx.HTTPError as exc:
            return FetchResult(
                url, current, 0, {}, b"", chain, error=f"{type(exc).__name__}: {exc}".strip(": ")
            )

    async def fetch(
        self, url: str, *, check_robots: bool = True, method: str = "GET"
    ) -> FetchResult:
        """Fetch a URL, following redirects and enforcing robots.txt on every hop."""
        if check_robots and not await self.allowed(url):
            raise RobotsDisallowed(url)
        result = await self._fetch_raw(url, method=method)
        if check_robots and result.final_url != url and not await self.allowed(result.final_url):
            raise RobotsDisallowed(result.final_url)
        return result

    @property
    def http(self) -> httpx.AsyncClient:
        """Underlying client for API calls (not crawling; still sends our User-Agent)."""
        return self._client
