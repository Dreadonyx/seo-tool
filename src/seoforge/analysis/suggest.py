"""Google Autosuggest keyword ideas - opt-in, cached for 30 days, heavily rate-limited.

This uses the public suggestion endpoint browsers use for the search box. It is unofficial:
it may change or rate-limit at any time, and returns popularity-ordered phrases, not volumes.
SEOForge sends at most a few dozen requests per run, one every 1.5 s, and caches results.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from seoforge.storage import Store

ENDPOINT = "https://suggestqueries.google.com/complete/search"
CACHE_NS = "autosuggest"
MAX_AGE = 30 * 86400
MIN_INTERVAL = 1.5
MODIFIERS = ("", "how to ", "what is ", "best ", " vs ", " for ")


def expand_seeds(seeds: list[str], max_queries: int = 30) -> list[str]:
    queries: list[str] = []
    for seed in seeds:
        for mod in MODIFIERS:
            q = f"{seed}{mod}".strip() if mod.startswith(" ") else f"{mod}{seed}"
            if q not in queries:
                queries.append(q)
    return queries[:max_queries]


async def suggestions(
    client: httpx.AsyncClient,
    store: Store,
    seeds: list[str],
    lang: str = "en",
    max_queries: int = 30,
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    last = 0.0
    loop = asyncio.get_running_loop()
    for query in expand_seeds(seeds, max_queries):
        key = f"{lang}:{query}"
        cached = store.kv_get(CACHE_NS, key, MAX_AGE)
        if cached is not None:
            out[query] = cached
            continue
        wait = last + MIN_INTERVAL - loop.time()
        if wait > 0:
            await asyncio.sleep(wait)
        last = loop.time()
        try:
            resp = await client.get(
                ENDPOINT, params={"client": "firefox", "hl": lang, "q": query}, timeout=10
            )
        except httpx.HTTPError:
            break
        if resp.status_code != 200:
            break  # rate-limited or blocked: stop politely instead of retrying
        try:
            data = json.loads(resp.content.decode("utf-8", "replace"))
            values = [str(s) for s in data[1] if str(s).lower() != query.lower()]
        except (ValueError, IndexError, TypeError):
            continue
        store.kv_set(CACHE_NS, key, values)
        out[query] = values
    return out
