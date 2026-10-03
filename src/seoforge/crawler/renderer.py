"""Optional JavaScript rendering with Playwright (Chromium)."""

from __future__ import annotations

from types import TracebackType
from typing import Any


class RendererUnavailable(RuntimeError):
    pass


class Renderer:
    """Renders pages in headless Chromium. Requires `playwright install chromium`."""

    def __init__(self, user_agent: str, timeout_ms: int = 20_000) -> None:
        self.user_agent = user_agent
        self.timeout_ms = timeout_ms
        self._pw: Any = None
        self._browser: Any = None

    async def __aenter__(self) -> Renderer:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover - playwright is a hard dependency
            raise RendererUnavailable("playwright is not installed") from exc
        self._pw = await async_playwright().start()
        try:
            self._browser = await self._pw.chromium.launch(headless=True)
        except Exception as exc:
            await self._pw.stop()
            raise RendererUnavailable(
                "Chromium is not installed for Playwright. Run: playwright install chromium"
            ) from exc
        return self

    async def __aexit__(
        self, et: type[BaseException] | None, e: BaseException | None, tb: TracebackType | None
    ) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()

    async def render(self, url: str) -> str:
        context = await self._browser.new_context(user_agent=self.user_agent)
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
            return str(await page.content())
        finally:
            await context.close()
