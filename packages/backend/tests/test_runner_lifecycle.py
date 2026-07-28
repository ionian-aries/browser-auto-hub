"""Runner lifecycle tests — cancel, busy requeue, retry semantics, commit fallback."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import backend.services.runner as runner
from engine.base import PipelineResult
from engine.registry import PipelineRegistry


class _SessionCM:
    def __init__(self, session):
        self._s = session

    async def __aenter__(self):
        return self._s

    async def __aexit__(self, *exc):
        return False


def _result(**kwargs):
    r = MagicMock()
    for k, v in kwargs.items():
        getattr(r, k).return_value = v
    return r


def _execution(**overrides):
    e = MagicMock()
    e.id = "exec-1"
    e.pipeline_id = "p1"
    e.schedule_id = None
    e.retry_count = 0
    e.trigger_type = "api"
    e.config = {}
    e.status = "pending"
    e.error_message = None
    e.result_summary = None
    e.pipeline = MagicMock()
    e.pipeline.name = "test.ok"
    e.pipeline.id = "p1"
    for k, v in overrides.items():
        setattr(e, k, v)
    return e


def _session(execution, commit_side_effects=None):
    """Main-session mock matching _run_execution's execute() call order."""
    s = AsyncMock()
    s.execute.side_effect = [
        _result(scalar_one_or_none=execution),  # select execution FOR UPDATE
        _result(scalars=[]),  # _get_global_run_config
    ]
    if commit_side_effects is not None:
        s.commit.side_effect = commit_side_effects
    return s


@pytest.fixture
def _patched(monkeypatch):
    class _OkPipeline:
        async def execute(self, config, ctx):
            return PipelineResult(success=True, summary={"ok": 1})

    PipelineRegistry._pipelines["test.ok"] = _OkPipeline
    monkeypatch.setattr(runner, "MinioStorage", MagicMock())
    logger = MagicMock()
    logger.step = AsyncMock()
    monkeypatch.setattr(runner, "DbStepLogger", MagicMock(return_value=logger))
    monkeypatch.setattr(runner.log_broadcaster, "publish", AsyncMock())
    yield
    PipelineRegistry._pipelines.pop("test.ok", None)


# ---------- B3: cancel 真正停止 task ----------


@pytest.mark.asyncio
async def test_cancel_stops_running_task(_patched):
    class _SlowPipeline:
        async def execute(self, config, ctx):
            await asyncio.sleep(60)
            return PipelineResult(success=True)

    PipelineRegistry._pipelines["test.ok"] = _SlowPipeline
    execution = _execution()
    session = _session(execution)
    factory = MagicMock(return_value=_SessionCM(session))

    await runner.dispatch_execution("exec-1", factory)
    await asyncio.sleep(0.05)

    assert runner.cancel_running_execution("exec-1") is True
    await asyncio.sleep(0.1)

    assert execution.status == "cancelled"
    assert "exec-1" not in runner._running_tasks
    runner.log_broadcaster.publish.assert_any_await(
        "exec-1", {"type": "complete", "status": "cancelled"}
    )


@pytest.mark.asyncio
async def test_cancel_unknown_execution_returns_false():
    assert runner.cancel_running_execution("no-such-id") is False


# ---------- B4/N4: retry 语义 ----------


@pytest.mark.asyncio
async def test_retry_preserves_trigger_type(monkeypatch):
    schedule = MagicMock(max_retries=3, retry_delay_seconds=0)
    session = AsyncMock()
    session.execute.return_value = _result(scalar_one_or_none=schedule)

    added = []
    retry_session = MagicMock()  # add 是同步方法，用 MagicMock + 异步 commit
    retry_session.add.side_effect = lambda obj: added.append(obj)
    retry_session.commit = AsyncMock()
    factory = MagicMock(return_value=_SessionCM(retry_session))
    dispatch = AsyncMock()
    monkeypatch.setattr(runner, "dispatch_execution", dispatch)

    execution = _execution(schedule_id="sch-1", trigger_type="api")
    await runner._schedule_retry(execution, session, factory)
    await asyncio.sleep(0.05)

    assert added, "应创建 retry execution"
    assert added[0].trigger_type == "api"
    assert added[0].retry_count == 1
    dispatch.assert_awaited()


@pytest.mark.asyncio
async def test_retry_uses_global_defaults_without_schedule(monkeypatch):
    """manual/api 触发（无 schedule）按 run_default_* 全局配置重试（N4 接线）。"""
    rows = [
        MagicMock(key="run_default_max_retries", value="2"),
        MagicMock(key="run_default_retry_delay_seconds", value="0"),
    ]
    session = AsyncMock()
    session.execute.return_value = _result(scalars=rows)

    added = []
    retry_session = MagicMock()
    retry_session.add.side_effect = lambda obj: added.append(obj)
    retry_session.commit = AsyncMock()
    factory = MagicMock(return_value=_SessionCM(retry_session))
    monkeypatch.setattr(runner, "dispatch_execution", AsyncMock())

    execution = _execution()  # schedule_id=None
    await runner._schedule_retry(execution, session, factory)
    await asyncio.sleep(0.05)

    assert added, "全局默认 max_retries=2 应允许 retry"
    assert added[0].retry_count == 1


@pytest.mark.asyncio
async def test_retry_skipped_when_global_default_zero():
    """全局默认 max_retries=0 时 manual/api 不重试（保持旧默认行为）。"""
    session = AsyncMock()
    session.execute.return_value = _result(scalars=[])
    factory = MagicMock()

    before = len(asyncio.all_tasks())
    await runner._schedule_retry(_execution(), session, factory)
    assert len(asyncio.all_tasks()) == before
    factory.assert_not_called()


# ---------- B1: finally commit 防护 ----------


@pytest.mark.asyncio
async def test_final_commit_failure_falls_back_to_fresh_session(_patched):
    execution = _execution()
    session = _session(execution, commit_side_effects=[None, RuntimeError("poisoned")])

    fallback_row = _execution()
    fallback_session = AsyncMock()
    fallback_session.execute.return_value = _result(scalar_one_or_none=fallback_row)

    factory = MagicMock(side_effect=[_SessionCM(session), _SessionCM(fallback_session)])

    await runner._run_execution("exec-1", factory)

    session.rollback.assert_awaited()
    fallback_session.commit.assert_awaited()
    assert fallback_row.status == "success"
    # SSE complete 不得因 commit 失败被跳过
    runner.log_broadcaster.publish.assert_any_await(
        "exec-1", {"type": "complete", "status": "success"}
    )
