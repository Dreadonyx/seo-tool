"""Google Search Console API: sitemap submission and URL Inspection (quota-aware).

Auth, in order of preference:
  1. GSC_ACCESS_TOKEN env var (e.g. `gcloud auth print-access-token` with the webmasters scope)
  2. A service-account JSON file (GSC_SERVICE_ACCOUNT_FILE) that has been added as a user of
     the Search Console property. Requires `pip install seoforge[google]`.

Google's Indexing API is deliberately NOT implemented: it is only for JobPosting and
BroadcastEvent pages (https://developers.google.com/search/apis/indexing-api/v3/quickstart).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from seoforge.storage import Store

SCOPE = "https://www.googleapis.com/auth/webmasters"
TOKEN_URL = "https://oauth2.googleapis.com/token"
WEBMASTERS = "https://www.googleapis.com/webmasters/v3"
INSPECT = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
# https://developers.google.com/webmaster-tools/limits
INSPECT_DAILY_LIMIT = 2000
INSPECT_PER_MINUTE = 600


class GSCAuthError(RuntimeError):
    pass


def service_account_token(path: Path) -> str:
    try:
        from google.auth import crypt, jwt
    except ImportError as exc:
        raise GSCAuthError("Install the Google extra: pip install 'seoforge[google]'") from exc
    info = json.loads(path.read_text(encoding="utf-8"))
    signer = crypt.RSASigner.from_service_account_info(info)
    now = int(time.time())
    assertion = jwt.encode(
        signer,
        {
            "iss": info["client_email"],
            "scope": SCOPE,
            "aud": TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        },
    )
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": assertion.decode() if isinstance(assertion, bytes) else assertion,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise GSCAuthError(f"Token exchange failed: HTTP {resp.status_code} {resp.text[:200]}")
    return str(resp.json()["access_token"])


def get_token(credentials_env: str = "GSC_SERVICE_ACCOUNT_FILE") -> str:
    token = os.environ.get("GSC_ACCESS_TOKEN")
    if token:
        return token
    path = os.environ.get(credentials_env)
    if not path:
        raise GSCAuthError(
            f"Set GSC_ACCESS_TOKEN or {credentials_env} (service-account JSON added as a user "
            "of your Search Console property). See README: Free API keys."
        )
    return service_account_token(Path(path))


def property_url(site: str, domain_property: bool = False) -> str:
    if domain_property:
        from urllib.parse import urlsplit

        return f"sc-domain:{urlsplit(site).hostname}"
    return site.rstrip("/") + "/"


@dataclass(slots=True)
class Inspection:
    url: str
    verdict: str | None = None
    coverage: str | None = None
    indexing_state: str | None = None
    robots: str | None = None
    page_fetch: str | None = None
    google_canonical: str | None = None
    user_canonical: str | None = None
    last_crawl: str | None = None
    in_sitemaps: list[str] = field(default_factory=list)
    error: str | None = None

    @classmethod
    def from_api(cls, url: str, data: dict[str, Any]) -> Inspection:
        r = data.get("inspectionResult", {}).get("indexStatusResult", {})
        return cls(
            url=url,
            verdict=r.get("verdict"),
            coverage=r.get("coverageState"),
            indexing_state=r.get("indexingState"),
            robots=r.get("robotsTxtState"),
            page_fetch=r.get("pageFetchState"),
            google_canonical=r.get("googleCanonical"),
            user_canonical=r.get("userCanonical"),
            last_crawl=r.get("lastCrawlTime"),
            in_sitemaps=r.get("sitemap", []) or [],
        )


class GSCClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        token: str,
        store: Store | None = None,
        daily_budget: int = INSPECT_DAILY_LIMIT,
    ) -> None:
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"}
        self.store = store
        self.daily_budget = min(daily_budget, INSPECT_DAILY_LIMIT)
        self._minute: list[float] = []

    async def submit_sitemap(self, prop: str, sitemap_url: str) -> int:
        url = f"{WEBMASTERS}/sites/{quote(prop, safe='')}/sitemaps/{quote(sitemap_url, safe='')}"
        resp = await self.client.put(url, headers=self.headers, timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"Sitemap submit failed: HTTP {resp.status_code} {resp.text[:300]}")
        return resp.status_code

    async def list_sitemaps(self, prop: str) -> list[dict[str, Any]]:
        url = f"{WEBMASTERS}/sites/{quote(prop, safe='')}/sitemaps"
        resp = await self.client.get(url, headers=self.headers, timeout=30)
        resp.raise_for_status()
        return list(resp.json().get("sitemap", []))

    def remaining(self, prop: str) -> int:
        used = self.store.quota_used(f"gsc-inspect:{prop}") if self.store else 0
        return max(0, self.daily_budget - used)

    async def inspect(self, prop: str, url: str, language: str = "en-US") -> Inspection:
        if self.remaining(prop) <= 0:
            return Inspection(url, error="daily URL Inspection budget reached (2,000/day/property)")
        now = time.monotonic()
        self._minute = [t for t in self._minute if now - t < 60]
        if len(self._minute) >= INSPECT_PER_MINUTE:
            import asyncio

            await asyncio.sleep(60 - (now - self._minute[0]))
        self._minute.append(time.monotonic())
        resp = await self.client.post(
            INSPECT,
            headers=self.headers,
            timeout=60,
            json={
                "inspectionUrl": url,
                "siteUrl": prop,
                "languageCode": language,
            },
        )
        if self.store:
            self.store.quota_add(f"gsc-inspect:{prop}")
        if resp.status_code != 200:
            return Inspection(url, error=f"HTTP {resp.status_code}: {resp.text[:200]}")
        return Inspection.from_api(url, resp.json())
