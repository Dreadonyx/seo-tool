"""IndexNow (https://www.indexnow.org/documentation).

One submission to api.indexnow.org is shared with all participating search engines
(including Microsoft Bing, Yandex, Seznam.cz, Naver and Yep). Submit only URLs that were
added, updated or deleted - not your whole site on every deploy.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from seoforge.storage import Store

ENDPOINT = "https://api.indexnow.org/indexnow"
BATCH = 10_000
KEY_RE = re.compile(r"^[a-zA-Z0-9-]{8,128}$")
STATUS_MEANING = {
    200: "OK - URLs submitted",
    202: "Accepted - key validation pending",
    400: "Bad request - invalid format",
    403: "Forbidden - key not valid (key file missing or mismatched)",
    422: "Unprocessable - URLs don't belong to the host or key doesn't match",
    429: "Too many requests - potential spam; slow down",
}


def generate_key() -> str:
    return secrets.token_hex(16)


def valid_key(key: str) -> bool:
    return bool(KEY_RE.match(key))


@dataclass(slots=True)
class KeyCheck:
    url: str
    ok: bool
    detail: str


async def verify_key_file(
    client: httpx.AsyncClient, site: str, key: str, key_location: str | None = None
) -> KeyCheck:
    url = key_location or f"{site.rstrip('/')}/{key}.txt"
    try:
        resp = await client.get(url, follow_redirects=True, timeout=15)
    except httpx.HTTPError as exc:
        return KeyCheck(url, False, f"request failed: {exc}")
    if resp.status_code != 200:
        return KeyCheck(url, False, f"HTTP {resp.status_code}")
    if resp.text.strip() != key:
        return KeyCheck(url, False, "file content does not match the key")
    return KeyCheck(url, True, "key file found and matches")


@dataclass(slots=True)
class SubmitResult:
    batch: int
    count: int
    status: int
    meaning: str


def filter_urls(urls: list[str], site: str) -> tuple[list[str], list[str]]:
    host = urlsplit(site).netloc
    good = [u for u in dict.fromkeys(urls) if urlsplit(u).netloc == host]
    bad = [u for u in urls if urlsplit(u).netloc != host]
    return good, bad


def changed_urls(store: Store, pages: dict[str, str]) -> list[str]:
    """URLs whose content hash differs from the last successful submission."""
    return [u for u, h in pages.items() if store.kv_get("indexnow", u) != h]


def remember(store: Store, pages: dict[str, str]) -> None:
    for url, digest in pages.items():
        store.kv_set("indexnow", url, digest)


async def submit(
    client: httpx.AsyncClient,
    site: str,
    key: str,
    urls: list[str],
    key_location: str | None = None,
    endpoint: str = ENDPOINT,
) -> list[SubmitResult]:
    host = urlsplit(site).netloc
    results = []
    for i in range(0, len(urls), BATCH):
        batch = urls[i : i + BATCH]
        payload: dict[str, object] = {"host": host, "key": key, "urlList": batch}
        if key_location:
            payload["keyLocation"] = key_location
        resp = await client.post(
            endpoint,
            json=payload,
            timeout=30,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        results.append(
            SubmitResult(
                i // BATCH + 1,
                len(batch),
                resp.status_code,
                STATUS_MEANING.get(resp.status_code, resp.text[:200]),
            )
        )
        if resp.status_code not in (200, 202):
            break
    return results
