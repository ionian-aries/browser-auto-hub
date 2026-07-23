"""DbStepLogger — boto3 sync calls must not block the event loop."""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.step_logger import DbStepLogger


@pytest.mark.asyncio
async def test_screenshot_upload_does_not_block_event_loop():
    storage = MagicMock()

    def slow_upload(*args):
        time.sleep(0.3)  # 同步 boto3 阻塞
        return "key"

    storage.upload.side_effect = slow_upload

    session = AsyncMock()
    logger = DbStepLogger("e1", session, storage, prefix="p")

    ticker_elapsed = {}

    async def ticker():
        start = time.monotonic()
        await asyncio.sleep(0.1)
        ticker_elapsed["t"] = time.monotonic() - start

    # ticker 先启动计时；若 upload 阻塞事件循环，ticker 会被拖到 ~0.3s 才完成
    await asyncio.gather(ticker(), logger.step("s", "m", screenshot=b"png"))

    assert ticker_elapsed["t"] < 0.25
    storage.upload.assert_called_once()
