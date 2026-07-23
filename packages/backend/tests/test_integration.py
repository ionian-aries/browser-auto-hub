import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_create_and_trigger_execution(client):
    """Test the full flow: list pipelines -> trigger execution."""
    # Health check
    resp = await client.get("/api/system/health")
    assert resp.status_code == 200

    # List pipelines (may be empty without DB, but endpoint works)
    resp = await client.get("/api/pipelines")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # Create execution (will 404 without DB pipeline, but tests API shape)
    resp = await client.post("/api/executions", json={
        "pipeline": "example",
        "config": {"message": "test"},
        "trigger_type": "manual",
    })
    # 404 is expected because mock returns None for pipeline lookup
    assert resp.status_code in (201, 404)


@pytest.mark.asyncio
async def test_create_dispatches_without_scheduler(monkeypatch):
    """N5: 无 scheduler_manager 时创建执行也必须派发（经全局 session_factory）。"""
    import backend.database as database
    import backend.services.runner as runner
    from backend.api.executions import router
    from backend.database import get_session
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    dispatch = AsyncMock()
    monkeypatch.setattr(runner, "dispatch_execution", dispatch)
    fake_factory = MagicMock(name="session_factory")
    monkeypatch.setattr(database, "get_session_factory", lambda: fake_factory)

    pipeline = MagicMock()
    pipeline.id = "p1"
    pipeline.name = "example"
    pipeline.display_name = "Example"
    pipeline.status = "active"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = pipeline
    session = AsyncMock()
    session.execute.return_value = mock_result

    async def _refresh(obj, *a, **k):
        obj.id = "e1"
        obj.created_at = datetime.now(timezone.utc)

    session.refresh.side_effect = _refresh

    async def _sess():
        yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = _sess

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.post("/api/executions", json={
            "pipeline": "example",
            "config": {},
            "trigger_type": "manual",
        })
    assert resp.status_code == 201
    dispatch.assert_awaited_once()
    assert dispatch.await_args.args[1] is fake_factory
