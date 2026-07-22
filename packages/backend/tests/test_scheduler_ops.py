from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.scheduler.manager import SchedulerManager


def _make_manager() -> SchedulerManager:
    """SchedulerManager with a stubbed scheduler and dummy session factory."""
    manager = SchedulerManager.__new__(SchedulerManager)
    manager._scheduler = AsyncMock()
    manager._session_factory = MagicMock()
    manager._paused = False
    return manager


def _session_returning(value):
    """Build a fake async session whose execute() returns a fixed scalar."""
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_get_setting_returns_db_value_when_present():
    session = _session_returning("7")
    value = await SchedulerManager._get_setting(session, "log_retention_days", "30")
    assert value == "7"


@pytest.mark.asyncio
async def test_get_setting_returns_default_when_missing():
    session = _session_returning(None)
    value = await SchedulerManager._get_setting(session, "log_retention_days", "30")
    assert value == "30"


@pytest.mark.asyncio
async def test_pause_sets_paused_flag():
    manager = _make_manager()
    manager.remove_schedule = AsyncMock()

    # Fake session factory whose session returns no schedule rows.
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    session.execute.return_value = result

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    manager._session_factory = MagicMock(return_value=_Ctx())

    await manager.pause()
    assert manager._paused is True


@pytest.mark.asyncio
async def test_resume_clears_paused_flag():
    manager = _make_manager()
    manager._paused = True
    manager.sync_all = AsyncMock()

    await manager.resume()
    assert manager._paused is False
    manager.sync_all.assert_awaited_once()


def test_compute_cutoff():
    before = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = SchedulerManager._compute_cutoff(30)
    after = datetime.now(timezone.utc).replace(tzinfo=None)
    assert before - timedelta(days=30) - timedelta(seconds=5) <= cutoff <= after - timedelta(days=30) + timedelta(seconds=5)
    assert cutoff.tzinfo is None
