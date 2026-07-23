"""SSE stream (B2) and cancel-task (B3) endpoint tests."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import backend.services.runner as runner
from backend.api.executions import cancel_execution, router
from backend.database import get_session
from backend.services.broadcaster import log_broadcaster


def _make_app(session):
    async def _sess():
        yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = _sess
    return app


def _empty_backfill_session():
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session = AsyncMock()
    session.execute.return_value = mock_result
    return session


# ---------- B3: cancel 端点停止 runner task ----------

@pytest.mark.asyncio
async def test_cancel_endpoint_stops_runner_task(monkeypatch):
    stop = MagicMock(return_value=True)
    monkeypatch.setattr(runner, "cancel_running_execution", stop)

    execution = MagicMock()
    execution.status = "running"
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = execution
    session = AsyncMock()
    session.execute.return_value = mock_result

    await cancel_execution("e1", session=session)

    assert execution.status == "cancelled"
    stop.assert_called_once_with("e1")


# ---------- B2: SSE 补发 + keepalive 不关流 ----------


@pytest.mark.asyncio
async def test_sse_stream_backfills_existing_logs():
    log = MagicMock(
        timestamp=datetime(2026, 7, 22, 8, 0, 0, tzinfo=timezone.utc),
        level="info",
        step_name="login",
        message="登录成功",
        screenshot_key=None,
    )
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [log]
    session = AsyncMock()
    session.execute.return_value = mock_result

    async def _publish_complete():
        await asyncio.sleep(0.1)
        await log_broadcaster.publish("e-bf", {"type": "complete", "status": "success"})

    task = asyncio.create_task(_publish_complete())
    async with AsyncClient(
        transport=ASGITransport(app=_make_app(session)), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/executions/e-bf/logs/stream")
    await task

    assert resp.status_code == 200
    assert '\\u767b\\u5f55\\u6210\\u529f' in resp.text  # 补发的历史日志（"登录成功"）
    assert '"type": "complete"' in resp.text


@pytest.mark.asyncio
async def test_sse_keepalive_keeps_stream_open(monkeypatch):
    monkeypatch.setattr("backend.api.executions._SSE_KEEPALIVE_SECONDS", 0.05)
    session = _empty_backfill_session()

    async def _publish_complete():
        await asyncio.sleep(0.2)  # 跨越多次 keepalive
        await log_broadcaster.publish("e-ka", {"type": "complete", "status": "success"})

    task = asyncio.create_task(_publish_complete())
    async with AsyncClient(
        transport=ASGITransport(app=_make_app(session)), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/executions/e-ka/logs/stream")
    await task

    # keepalive 必须是 SSE 注释行（前端不会渲染成伪日志），且流不因此关闭
    assert ": keepalive" in resp.text
    assert '"type": "complete"' in resp.text


# ---------- 分页 total ----------


@pytest.mark.asyncio
async def test_list_executions_returns_total():
    """列表接口必须返回 total（前端分页器需要），不再只返回裸数组。"""
    items_result = MagicMock()
    items_result.scalars.return_value.all.return_value = []

    session = AsyncMock()
    session.scalar.return_value = 42
    session.execute.return_value = items_result

    async with AsyncClient(
        transport=ASGITransport(app=_make_app(session)), base_url="http://test"
    ) as ac:
        resp = await ac.get("/api/executions", params={"page": 2, "page_size": 20})

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 42
    assert body["items"] == []

    # UUID 主键无顺序意义：必须按 created_at 倒序
    stmt = session.execute.call_args.args[0]
    sql = str(stmt.compile()).lower()
    assert "order by" in sql and "created_at desc" in sql
