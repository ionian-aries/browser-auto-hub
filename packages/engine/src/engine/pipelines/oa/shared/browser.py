"""Shared browser lifecycle for OA pipelines."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import Page, async_playwright


@asynccontextmanager
async def oa_browser(config: dict) -> AsyncIterator[Page]:
    """Launch Chromium, yield a page, always close the browser."""
    headless = config.get("headless", True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        try:
            page = await browser.new_page()
            yield page
        finally:
            await browser.close()
