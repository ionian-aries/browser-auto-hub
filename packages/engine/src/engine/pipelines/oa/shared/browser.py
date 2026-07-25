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
    # 不能用 async with async_playwright()：退出上下文会停止 driver，
    # 连带杀死浏览器进程——close_browser=False 将永远失效（spec 1 §12）。
    # close_browser=False 时刻意保留 driver + 浏览器进程（调试观察用），随 backend 退出终止。
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(headless=headless)
        try:
            # 显式 context：browser.new_page() 的隐式 context 被 Playwright 禁止
            # 再 new_page()（1.61: "Please use browser.new_context()"），
            # todos 详情直达标签页依赖该能力（spec 3 2026-07-24 修订三）
            context = await browser.new_context()
            page = await context.new_page()
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
    finally:
        if close_browser:
            try:
                await pw.stop()
            except Exception:
                pass
