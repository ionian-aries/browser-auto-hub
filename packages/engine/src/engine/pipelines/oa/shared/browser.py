"""Shared browser lifecycle for OA pipelines."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import Page, async_playwright


@asynccontextmanager
async def oa_browser(config: dict) -> AsyncIterator[Page]:
    """Launch Chromium, yield a page, close the browser unless close_browser=False."""
    headless = config.get("headless", True)
    close_browser = config.get("close_browser", True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        try:
            page = await browser.new_page()
            yield page
        finally:
            if close_browser:
                await browser.close()
