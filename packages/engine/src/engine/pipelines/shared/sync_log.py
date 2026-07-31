"""并发安全的步骤日志包装（pipeline 通用）。

并发 worker 共用 pipeline 业务 session 写库必须串行，否则 session 状态竞争；
日志本身由 DbStepLogger 独立 session 落库，不占用业务 session。
用法：
    log = SyncLog(ctx.logger)
    await log.info("crawl", "...")                # 普通日志（内部持锁）
    async with log.lock:                          # DB 写 + 日志需原子串行时
        await session.execute(...)
        await session.commit()
        await log.raw.step("detail", "...", "info")
"""
from __future__ import annotations

import asyncio
from typing import Any


class SyncLog:
    """StepLogger 的并发安全 facade（info/warn/error + 共享锁）。"""

    def __init__(self, logger: Any) -> None:
        self.raw = logger
        self.lock = asyncio.Lock()

    async def info(self, step: str, message: str, data: Any = None) -> None:
        async with self.lock:
            await self.raw.step(step, message, "info", data)

    async def warn(self, step: str, message: str, data: Any = None) -> None:
        async with self.lock:
            await self.raw.step(step, message, "warn", data)

    async def error(self, step: str, message: str, data: Any = None) -> None:
        async with self.lock:
            await self.raw.step(step, message, "error", data)
