"""Enhanced runner tests — retry logic（并发闸门已随 spec 1 二十次修订退役）。"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.runner import _schedule_retry


@pytest.mark.asyncio
async def test_schedule_retry_noop_when_no_schedule_id():
    """Manual/api triggers retry via global run_default_* settings; default 0 → no retry."""
    execution = MagicMock()
    execution.schedule_id = None
    execution.retry_count = 0

    result_mock = MagicMock()
    result_mock.scalars.return_value = []  # 无 run_default_* 行 → max_retries=0
    session = AsyncMock()
    session.execute.return_value = result_mock
    session_factory = MagicMock()

    before = len(asyncio.all_tasks())
    await _schedule_retry(execution, session, session_factory)
    assert len(asyncio.all_tasks()) == before
    session_factory.assert_not_called()


@pytest.mark.asyncio
async def test_schedule_retry_noop_when_max_retries_reached():
    execution = MagicMock()
    execution.schedule_id = "sch-1"
    execution.retry_count = 3

    schedule_mock = MagicMock()
    schedule_mock.max_retries = 3
    schedule_mock.retry_delay_seconds = 60

    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = schedule_mock
    session = AsyncMock()
    session.execute.return_value = result_mock

    session_factory = MagicMock()

    # Should not spawn a retry task — count tasks before/after
    before = len(asyncio.all_tasks())
    await _schedule_retry(execution, session, session_factory)
    after = len(asyncio.all_tasks())
    assert after == before
