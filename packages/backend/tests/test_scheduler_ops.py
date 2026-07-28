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


def _cleanup_session(retention_value, executed):
    """Fake session：_get_setting 返回 retention_value，捕获所有 execute 语句。"""
    session = AsyncMock()

    async def _execute(stmt, *a, **k):
        executed.append(stmt)
        result = MagicMock()
        # _get_setting 的 scalar 查询返回 retention 配置
        result.scalar_one_or_none.return_value = retention_value
        return result

    session.execute.side_effect = _execute

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    return session, _Ctx()


def _manager_with_ctx(ctx) -> SchedulerManager:
    manager = SchedulerManager.__new__(SchedulerManager)
    manager._scheduler = AsyncMock()
    manager._paused = False
    manager._session_factory = MagicMock(return_value=ctx)
    return manager


@pytest.mark.asyncio
async def test_cleanup_deletes_children_before_executions_with_cutoff():
    """清理必须按 logs → executions 顺序（FK 约束），cutoff 为保留天数前。

    十七次修订：task_artifacts 表已删除，清理目标收敛为两张表。
    """
    executed = []
    session, ctx = _cleanup_session("30", executed)
    manager = _manager_with_ctx(ctx)

    await manager._cleanup_old_executions()

    # 第 1 条是 _get_setting 的 SELECT，之后必须恰好 2 条 DELETE
    deletes = [s for s in executed if s.__class__.__name__ == "Delete"]
    assert len(deletes) == 2
    tables = [d.table.name for d in deletes]
    assert tables == ["task_logs", "task_executions"]
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_honors_custom_retention_days():
    """log_retention_days=7 时 cutoff 应为 7 天前（而非默认 30）。"""
    executed = []
    _, ctx = _cleanup_session("7", executed)
    manager = _manager_with_ctx(ctx)

    before = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    await manager._cleanup_old_executions()
    after = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)

    deletes = [s for s in executed if s.__class__.__name__ == "Delete"]
    # 编译最后一条 DELETE 的参数，确认 cutoff 落在 7 天窗口
    compiled = deletes[-1].compile(compile_kwargs={"literal_binds": False})
    cutoff_param = list(compiled.params.values())[0]
    assert before - timedelta(seconds=5) <= cutoff_param <= after + timedelta(seconds=5)


@pytest.mark.asyncio
async def test_cleanup_invalid_retention_falls_back_to_30():
    executed = []
    _, ctx = _cleanup_session("not-a-number", executed)
    manager = _manager_with_ctx(ctx)

    before = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
    await manager._cleanup_old_executions()
    after = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)

    deletes = [s for s in executed if s.__class__.__name__ == "Delete"]
    compiled = deletes[-1].compile(compile_kwargs={"literal_binds": False})
    cutoff_param = list(compiled.params.values())[0]
    assert before - timedelta(seconds=5) <= cutoff_param <= after + timedelta(seconds=5)


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
