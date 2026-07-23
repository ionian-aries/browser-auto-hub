"""Shared browser lifecycle for OA pipelines."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from playwright.async_api import Page, async_playwright


def _consume_close_exception(task: asyncio.Task) -> None:
    """取回后台 close 的异常，避免 'exception was never retrieved' 噪音。"""
    if not task.cancelled():
        task.exception()


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
                # shield：执行超时取消后 close 进行中若再遇手动 cancel，
                # 不打断 close —— 否则 chromium 进程残留；close 在后台继续完成
                close_task = asyncio.ensure_future(browser.close())
                close_task.add_done_callback(_consume_close_exception)
                try:
                    await asyncio.shield(close_task)
                except asyncio.CancelledError:
                    raise  # 取消继续传播；close 已在后台运行
                except Exception:
                    pass  # close 失败不应掩盖 pipeline 的原始异常
