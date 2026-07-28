"""Lifespan — 只连不建（spec 1 十八次修订）：sync pipeline、启动/停止调度器、shutdown dispose engine。"""
from unittest.mock import AsyncMock, MagicMock

import pytest


class _CM:
    def __init__(self, value):
        self._v = value

    async def __aenter__(self):
        return self._v

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_lifespan_syncs_pipelines_and_disposes_engine(monkeypatch):
    import backend.main as main

    engine = MagicMock()
    engine.dispose = AsyncMock()
    monkeypatch.setattr(main, "get_engine", lambda: engine)

    session = AsyncMock()
    factory = MagicMock(return_value=_CM(session))
    monkeypatch.setattr(main, "get_session_factory", lambda: factory)
    sync = AsyncMock()
    monkeypatch.setattr(main, "sync_pipelines_to_db", sync)

    scheduler = MagicMock()
    scheduler.start = AsyncMock()
    scheduler.stop = AsyncMock()
    monkeypatch.setattr(main, "SchedulerManager", MagicMock(return_value=scheduler))

    async with main.lifespan(MagicMock()):
        pass

    sync.assert_awaited_once()
    scheduler.start.assert_awaited_once()
    scheduler.stop.assert_awaited_once()
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_does_not_touch_schema_or_minio(monkeypatch):
    """启动不再建表/建 bucket：engine.begin 不应被调用，MinioStorage 不应被构造。"""
    import backend.main as main

    engine = MagicMock()
    engine.dispose = AsyncMock()
    monkeypatch.setattr(main, "get_engine", lambda: engine)

    session = AsyncMock()
    factory = MagicMock(return_value=_CM(session))
    monkeypatch.setattr(main, "get_session_factory", lambda: factory)
    monkeypatch.setattr(main, "sync_pipelines_to_db", AsyncMock())

    scheduler = MagicMock()
    scheduler.start = AsyncMock()
    scheduler.stop = AsyncMock()
    monkeypatch.setattr(main, "SchedulerManager", MagicMock(return_value=scheduler))

    async with main.lifespan(MagicMock()):
        pass

    engine.begin.assert_not_called()
    assert not hasattr(main, "MinioStorage")
