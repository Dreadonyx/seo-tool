"""Common Crawl presence: how many of your URLs are in the latest Common Crawl index.

Common Crawl's open dataset is a common ingredient of LLM training corpora. Presence here is
a rough signal of whether your content is available to that ecosystem - not proof that any
particular model was trained on it. (Blocking CCBot in robots.txt removes future captures.)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

COLLINFO = "https://index.commoncrawl.org/collinfo.json"


@dataclass(slots=True)
class CCPresence:
    crawl_id: str | None
    domain: str
    captures: int = 0
    sample: list[str] = field(default_factory=list)
    error: str | None = None


async def presence(client: httpx.AsyncClient, site: str, limit: int = 1000) -> CCPresence:
    domain = urlsplit(site).hostname or site
    result = CCPresence(None, domain)
    try:
        info = (await client.get(COLLINFO, timeout=30)).json()
        latest = info[0]
        result.crawl_id = latest["id"]
        resp = await client.get(
            latest["cdx-api"],
            params={
                "url": f"{domain}/*",
                "output": "json",
                "limit": limit,
                "fl": "url,status",
            },
            timeout=60,
        )
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        result.error = str(exc)
        return result
    if resp.status_code == 404:
        return result  # no captures
    if resp.status_code != 200:
        result.error = f"HTTP {resp.status_code}"
        return result
    urls = []
    for line in resp.text.splitlines():
        try:
            urls.append(json.loads(line)["url"])
        except (ValueError, KeyError):
            continue
    result.captures = len(urls)
    result.sample = sorted(set(urls))[:20]
    return result
