"""调度触发链路回归测试（spec 1 §14 / 调度方式全维度）。

覆盖：_build_trigger 三形态、_execute_scheduled 的执行记录语义
（trigger_type=scheduled、config_override、版本快照、once 自动禁用、无效场景跳过）。
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.models.schedule import Schedule
from backend.scheduler.manager import SchedulerManager


def _schedule(**kw) -> Schedule:
    defaults = {
        "id": "s1",
        "pipeline_id": "p1",
        "name": "t",
        "trigger_type": "interval",
        "interval_seconds": 300,
    }
    defaults.update(kw)
    return Schedule(**defaults)


# ---------- _build_trigger 三形态 ----------


def test_build_trigger_cron():
    s = _schedule(trigger_type="cron", cron_expr="*/5 * * * *", interval_seconds=None)
    trigger = SchedulerManager._build_trigger(s)
    assert isinstance(trigger, CronTrigger)
    assert trigger.next() is not None


def test_build_trigger_interval():
    s = _schedule()
    trigger = SchedulerManager._build_trigger(s)
    assert isinstance(trigger, IntervalTrigger)
    assert trigger.next() is not None


def test_interval_first_fire_after_one_interval():
    """spec 1 二十四次修订：首次触发 = 注册后一个间隔，而非注册瞬间。

    APScheduler 4 IntervalTrigger 的 start_time 缺省为构造时刻，首次 next()
    返回 start_time 本身（注册即触发）；显式 start_time=now+interval 修正。
    """
    before = datetime.now(timezone.utc)
    trigger = SchedulerManager._build_trigger(_schedule())  # interval_seconds=300
    after = datetime.now(timezone.utc)

    first = trigger.next().astimezone(timezone.utc)
    assert before + timedelta(seconds=300) <= first <= after + timedelta(seconds=300)
    # 第二次触发仍按间隔递增
    second = trigger.next().astimezone(timezone.utc)
    assert abs((second - first).total_seconds() - 300) < 1


def test_build_trigger_once_converts_utc_naive_to_local_aware():
    """run_at 存 UTC-naive；DateTrigger 需 tz-aware 本地时间（spec 1 §14）。"""
    future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
    s = _schedule(trigger_type="once", run_at=future, interval_seconds=None)
    trigger = SchedulerManager._build_trigger(s)
    assert isinstance(trigger, DateTrigger)
    nxt = trigger.next()
    assert nxt is not None and nxt.tzinfo is not None
    # 转换后必须指向同一时刻（与 UTC 输入相差 <=1s）
    assert abs((nxt.astimezone(timezone.utc).replace(tzinfo=None) - future).total_seconds()) <= 1


def test_build_trigger_invalid_returns_none():
    s = _schedule(trigger_type="cron", cron_expr=None, interval_seconds=None)
    assert SchedulerManager._build_trigger(s) is None


# ---------- _execute_scheduled 语义 ----------


def _fake_session(schedule, pipeline, added):
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = schedule
    session.execute.return_value = result
    session.get.return_value = pipeline

    def _add(obj):
        added.append(obj)

    async def _refresh(obj, *a, **k):
        if getattr(obj, "id", None) is None:
            obj.id = "e1"

    session.add = MagicMock(side_effect=_add)  # SQLAlchemy add 是同步方法
    session.refresh.side_effect = _refresh

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    return _Ctx()


def _manager_with(session_ctx) -> SchedulerManager:
    manager = SchedulerManager.__new__(SchedulerManager)
    manager._scheduler = AsyncMock()
    manager._paused = False
    manager._session_factory = MagicMock(return_value=session_ctx)
    return manager


def _pipeline(status="active", version="1.2.2"):
    p = MagicMock()
    p.status = status
    p.version = version
    return p


@pytest.mark.asyncio
async def test_execute_scheduled_creates_scheduled_execution(monkeypatch):
    dispatch = AsyncMock()
    monkeypatch.setattr("backend.services.runner.dispatch_execution", dispatch)

    schedule = _schedule()
    schedule.config_override = {"headless": True}
    added = []
    manager = _manager_with(_fake_session(schedule, _pipeline(), added))

    await manager._execute_scheduled("s1", "p1")

    assert len(added) == 1
    execution = added[0]
    assert execution.trigger_type == "scheduled"
    assert execution.schedule_id == "s1"
    assert execution.config == {"headless": True}
    assert execution.pipeline_version == "1.2.2"  # 版本快照
    dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_scheduled_once_auto_disables(monkeypatch):
    monkeypatch.setattr("backend.services.runner.dispatch_execution", AsyncMock())

    future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
    schedule = _schedule(trigger_type="once", run_at=future, interval_seconds=None)
    manager = _manager_with(_fake_session(schedule, _pipeline(), []))

    await manager._execute_scheduled("s1", "p1")

    assert schedule.enabled is False  # 防止重启后重复注册


@pytest.mark.asyncio
async def test_execute_scheduled_skips_when_schedule_gone_or_disabled(monkeypatch):
    dispatch = AsyncMock()
    monkeypatch.setattr("backend.services.runner.dispatch_execution", dispatch)

    for schedule in (None, _schedule(enabled=False)):
        added = []
        manager = _manager_with(_fake_session(schedule, _pipeline(), added))
        await manager._execute_scheduled("s1", "p1")
        assert added == []
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_scheduled_skips_inactive_pipeline(monkeypatch):
    dispatch = AsyncMock()
    monkeypatch.setattr("backend.services.runner.dispatch_execution", dispatch)

    added = []
    manager = _manager_with(_fake_session(_schedule(), _pipeline(status="archived"), added))
    await manager._execute_scheduled("s1", "p1")

    assert added == []
    dispatch.assert_not_awaited()
