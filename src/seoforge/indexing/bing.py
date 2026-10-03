"""Bing Webmaster Tools API (free API key from Bing Webmaster Tools > Settings > API access).

Reference: https://learn.microsoft.com/en-us/bingwebmaster/getting-access
Bing recommends IndexNow for change notifications; the URL Submission API has a daily quota
reported by GetUrlSubmissionQuota.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

BASE = "https://ssl.bing.com/webmaster/api.svc/json"


class BingError(RuntimeError):
    pass


@dataclass(slots=True)
class Quota:
    daily: int
    monthly: int


class BingClient:
    def __init__(self, client: httpx.AsyncClient, api_key: str) -> None:
        self.client = client
        self.key = api_key

    async def _call(self, method: str, body: dict[str, Any]) -> object:
        resp = await self.client.post(
            f"{BASE}/{method}", params={"apikey": self.key}, json=body, timeout=30
        )
        if resp.status_code != 200:
            raise BingError(f"{method}: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.json().get("d") if resp.content else None

    async def quota(self, site: str) -> Quota:
        resp = await self.client.get(
            f"{BASE}/GetUrlSubmissionQuota",
            params={"siteUrl": site, "apikey": self.key},
            timeout=30,
        )
        if resp.status_code != 200:
            raise BingError(f"GetUrlSubmissionQuota: HTTP {resp.status_code} {resp.text[:300]}")
        d = resp.json().get("d") or {}
        return Quota(int(d.get("DailyQuota", 0)), int(d.get("MonthlyQuota", 0)))

    async def submit_urls(self, site: str, urls: list[str]) -> int:
        quota = await self.quota(site)
        batch = urls[: quota.daily]
        if not batch:
            raise BingError("Daily URL submission quota is exhausted.")
        await self._call("SubmitUrlbatch", {"siteUrl": site, "urlList": batch})
        return len(batch)

    async def submit_sitemap(self, site: str, sitemap_url: str) -> None:
        await self._call("SubmitFeed", {"siteUrl": site, "feedUrl": sitemap_url})
