"""Core Web Vitals via the free PageSpeed Insights API and (optionally) the local Lighthouse CLI."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import shutil
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

# Thresholds from https://web.dev/articles/vitals (75th percentile, field data).
THRESHOLDS = {
    "LCP": (2500, 4000),  # ms
    "INP": (200, 500),  # ms
    "CLS": (0.1, 0.25),
}
CRUX_KEYS = {
    "LCP": "LARGEST_CONTENTFUL_PAINT_MS",
    "INP": "INTERACTION_TO_NEXT_PAINT",
    "CLS": "CUMULATIVE_LAYOUT_SHIFT_SCORE",
}


@dataclass(slots=True)
class PerfResult:
    url: str
    tool: str  # "pagespeed" | "lighthouse"
    strategy: str = "mobile"
    field_data: dict[str, float] = field(default_factory=dict)  # CrUX p75 (real users)
    field_categories: dict[str, str] = field(default_factory=dict)
    lab: dict[str, float] = field(default_factory=dict)  # Lighthouse lab metrics
    performance_score: float | None = None  # 0-100
    error: str | None = None


def is_public(url: str) -> bool:
    host = urlsplit(url).hostname or ""
    if host in ("localhost",) or host.endswith((".local", ".internal", ".test", ".localhost")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True


def rate(metric: str, value: float) -> str:
    good, poor = THRESHOLDS[metric]
    return "good" if value <= good else "poor" if value > poor else "needs-improvement"


def _lab_from_lighthouse(lhr: dict[str, Any]) -> tuple[dict[str, float], float | None]:
    audits = lhr.get("audits", {})
    lab = {}
    for key, audit_id in (
        ("LCP", "largest-contentful-paint"),
        ("CLS", "cumulative-layout-shift"),
        ("TBT", "total-blocking-time"),
        ("FCP", "first-contentful-paint"),
        ("SI", "speed-index"),
    ):
        value = audits.get(audit_id, {}).get("numericValue")
        if value is not None:
            lab[key] = float(value)
    score = lhr.get("categories", {}).get("performance", {}).get("score")
    return lab, (float(score) * 100 if score is not None else None)


async def pagespeed(
    client: httpx.AsyncClient, url: str, api_key: str | None, strategy: str = "mobile"
) -> PerfResult:
    result = PerfResult(url=url, tool="pagespeed", strategy=strategy)
    params = {"url": url, "strategy": strategy, "category": "performance"}
    if api_key:
        params["key"] = api_key
    try:
        resp = await client.get(PSI_ENDPOINT, params=params, timeout=120)
    except httpx.HTTPError as exc:
        result.error = str(exc)
        return result
    if resp.status_code != 200:
        msg = resp.json().get("error", {}).get("message", "") if resp.content else ""
        result.error = f"HTTP {resp.status_code}: {msg[:200]}"
        return result
    data = resp.json()
    metrics = data.get("loadingExperience", {}).get("metrics", {})
    for name, key in CRUX_KEYS.items():
        if key in metrics:
            value = float(metrics[key]["percentile"])
            if name == "CLS":
                value /= 100  # CrUX reports CLS x100
            result.field_data[name] = value
            result.field_categories[name] = rate(name, value)
    result.lab, result.performance_score = _lab_from_lighthouse(data.get("lighthouseResult", {}))
    return result


def lighthouse_available() -> bool:
    return shutil.which("lighthouse") is not None


async def lighthouse(url: str, strategy: str = "mobile") -> PerfResult:
    result = PerfResult(url=url, tool="lighthouse", strategy=strategy)
    binary = shutil.which("lighthouse")
    if binary is None:
        result.error = "lighthouse CLI not found (npm install -g lighthouse)"
        return result
    args = [
        binary,
        url,
        "--output=json",
        "--output-path=stdout",
        "--quiet",
        "--only-categories=performance",
        "--chrome-flags=--headless=new --no-sandbox",
    ]
    if strategy == "desktop":
        args.append("--preset=desktop")
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=180)
    except TimeoutError:
        proc.kill()
        result.error = "lighthouse timed out"
        return result
    if proc.returncode != 0:
        result.error = err.decode(errors="replace")[-300:]
        return result
    result.lab, result.performance_score = _lab_from_lighthouse(json.loads(out))
    return result


async def measure(
    client: httpx.AsyncClient,
    urls: list[str],
    api_key: str | None,
    *,
    use_pagespeed: bool = True,
    use_lighthouse: bool = False,
) -> list[PerfResult]:
    results: list[PerfResult] = []
    for url in urls:
        if use_pagespeed and is_public(url):
            results.append(await pagespeed(client, url, api_key))
        if use_lighthouse and lighthouse_available():
            results.append(await lighthouse(url))
    return results
