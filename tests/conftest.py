from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from seoforge.config import Config
from serve_site import start


@pytest.fixture(scope="session")
def site_url() -> Iterator[str]:
    server, url = start()
    yield url
    server.shutdown()


@pytest.fixture
def config(tmp_path: Path) -> Config:
    cfg = Config(data_dir=str(tmp_path / ".seoforge"))
    cfg.crawl.delay_seconds = 0
    cfg.crawl.concurrency = 4
    cfg.crawl.max_pages = 100
    return cfg


@pytest.fixture(scope="session")
def audited(site_url: str, tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    """One full audit of the test site shared by integration tests."""
    import asyncio

    from seoforge.audit import AuditOptions, run_audit

    cfg = Config(data_dir=str(tmp_path_factory.mktemp("data")))
    cfg.crawl.delay_seconds = 0
    cfg.entity.name = "Acme Widgets"
    report, ctx = asyncio.run(run_audit(site_url, cfg, AuditOptions(pagespeed=False)))
    return report, ctx
