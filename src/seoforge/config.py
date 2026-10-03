"""Configuration loaded from seoforge.yaml (all fields optional) plus environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from seoforge import USER_AGENT

BotPolicy = Literal["allow", "deny"]
ReportFormat = Literal["html", "md", "json"]
ALL_FORMATS: tuple[ReportFormat, ...] = ("html", "md", "json")
BotPreset = Literal["allow-all", "search-only", "deny-training", "deny-all", "custom"]


class CrawlConfig(BaseModel):
    max_pages: int = 500
    max_depth: int = 10
    concurrency: int = 4
    delay_seconds: float = 0.5  # minimum delay between requests to the same host
    timeout_seconds: float = 20.0
    user_agent: str = USER_AGENT
    # robots.txt group used for allow/deny decisions; "*" unless overridden
    robots_user_agent: str = "SEOForge"
    render_js: bool = False
    include: list[str] = Field(default_factory=list)  # regexes; empty = everything
    exclude: list[str] = Field(default_factory=list)
    follow_nofollow: bool = False
    check_external: bool = False  # HEAD-check outbound links for 4xx/5xx (robots-aware, slower)
    max_external_checks: int = 200
    respect_crawl_delay: bool = True
    use_sitemaps: bool = True
    cache_ttl_hours: float = 24.0
    max_body_bytes: int = 5_000_000


class ApiConfig(BaseModel):
    """API keys are read from environment variables, never stored in the YAML."""

    pagespeed_key_env: str = "PAGESPEED_API_KEY"
    bing_key_env: str = "BING_WEBMASTER_API_KEY"
    gsc_credentials_env: str = "GSC_SERVICE_ACCOUNT_FILE"
    indexnow_key_env: str = "INDEXNOW_KEY"

    def env(self, name: str) -> str | None:
        value = os.environ.get(getattr(self, name))
        return value or None


class EntityConfig(BaseModel):
    """Facts about the brand/organization. Only what you fill in is ever published."""

    name: str | None = None
    legal_name: str | None = None
    type: str = "Organization"  # Organization | LocalBusiness | Person | ...
    description: str | None = None
    url: str | None = None
    logo: str | None = None
    founded: str | None = None
    founders: list[str] = Field(default_factory=list)
    email: str | None = None
    telephone: str | None = None
    address: dict[str, str] = Field(default_factory=dict)
    category: str | None = None  # e.g. "project management software"
    city: str | None = None
    same_as: list[str] = Field(default_factory=list)
    wikidata_id: str | None = None


class GeoConfig(BaseModel):
    ai_bot_preset: BotPreset = "search-only"
    ai_bots: dict[str, BotPolicy] = Field(default_factory=dict)  # overrides per bot token
    llms_txt_sections: dict[str, list[str]] = Field(default_factory=dict)  # section -> url regexes


class ReportConfig(BaseModel):
    output_dir: str = "seoforge-report"
    formats: list[ReportFormat] = Field(default_factory=lambda: list(ALL_FORMATS))
    fail_on: Literal["critical", "high", "medium", "low", "never"] = "never"


class Config(BaseModel):
    site: str | None = None
    data_dir: str = ".seoforge"
    crawl: CrawlConfig = Field(default_factory=CrawlConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    entity: EntityConfig = Field(default_factory=EntityConfig)
    geo: GeoConfig = Field(default_factory=GeoConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    competitors: list[str] = Field(default_factory=list)
    seed_keywords: list[str] = Field(default_factory=list)
    pagespeed_urls: int = 3  # how many top pages to send to PageSpeed Insights
    disabled_checks: list[str] = Field(default_factory=list)
    plugins: list[str] = Field(default_factory=list)  # importable modules registering checks

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / "seoforge.db"


DEFAULT_CONFIG_NAMES = ("seoforge.yaml", "seoforge.yml", ".seoforge.yaml")


def load_config(path: str | Path | None = None) -> Config:
    candidates = [Path(path)] if path else [Path(n) for n in DEFAULT_CONFIG_NAMES]
    for candidate in candidates:
        if candidate.is_file():
            data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            return Config.model_validate(data)
        if path:
            raise FileNotFoundError(f"Config file not found: {candidate}")
    return Config()


EXAMPLE_CONFIG = """\
# seoforge.yaml - every field is optional. API keys come from environment variables.
site: https://example.com
crawl:
  max_pages: 500
  max_depth: 10
  concurrency: 4
  delay_seconds: 0.5        # politeness delay per host (robots.txt Crawl-delay wins if larger)
  render_js: false          # true = render with Playwright (run `playwright install chromium`)
  exclude: ["/wp-admin", "\\\\?replytocom="]
api:
  pagespeed_key_env: PAGESPEED_API_KEY
  bing_key_env: BING_WEBMASTER_API_KEY
  gsc_credentials_env: GSC_SERVICE_ACCOUNT_FILE
  indexnow_key_env: INDEXNOW_KEY
entity:
  name: Example Inc.
  type: Organization
  description: One factual sentence about what you do.
  category: project management software
  city: Chennai
  same_as:
    - https://github.com/example
    - https://www.linkedin.com/company/example
geo:
  ai_bot_preset: search-only  # allow-all | search-only | deny-training | deny-all | custom
  ai_bots:                    # per-bot overrides
    CCBot: deny
competitors:
  - https://competitor.example/pricing
seed_keywords: ["project management", "kanban board"]
report:
  output_dir: seoforge-report
  fail_on: never              # critical | high | medium | low | never (for CI)
disabled_checks: []
plugins: []                   # e.g. ["mycompany.seoforge_checks"]
"""
