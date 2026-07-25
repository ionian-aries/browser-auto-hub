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


_fired_probe: list = []


async def _probe_job():
    """模块级探针（APScheduler 4 拒绝 `<locals>` 闭包，必须模块级）。"""
    _fired_probe.append(1)


@pytest.mark.asyncio
async def test_start_actually_fires_scheduled_jobs():
    """start() 必须让调度循环真正运行（APScheduler 4 需 start_in_background）。

    回归场景：仅 __aenter__ 时 add_schedule 静默成功但永不触发，
    生产表现为调度任务零执行记录。mock 测试无法发现，必须行为级验证。
    """
    import asyncio

    from apscheduler import AsyncScheduler, ConflictPolicy
    from apscheduler.triggers.interval import IntervalTrigger

    manager = SchedulerManager.__new__(SchedulerManager)
    manager._scheduler = AsyncScheduler()
    manager._paused = False

    # 桩 session：scheduler_enabled -> "true"；sync_all 查询 -> 空列表
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = "true"
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    manager._session_factory = MagicMock(return_value=_Ctx())

    _fired_probe.clear()
    await manager.start()
    try:
        await manager._scheduler.add_schedule(
            _probe_job,
            IntervalTrigger(seconds=0.3),
            id="probe",
            conflict_policy=ConflictPolicy.replace,
        )
        await asyncio.sleep(1.0)
        assert _fired_probe, "调度循环未运行：start() 后注册的 job 在 1s 内零触发"
    finally:
        await manager.stop()
