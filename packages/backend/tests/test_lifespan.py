"""Lifespan — MinIO bucket ensured at startup; engine disposed at shutdown."""
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
async def test_lifespan_ensures_bucket_and_disposes_engine(monkeypatch):
    import backend.main as main

    conn = AsyncMock()
    columns_result = MagicMock()
    columns_result.scalar_one.return_value = 1  # run_at 列已存在 → 不触发 ALTER
    conn.execute.return_value = columns_result

    engine = MagicMock()
    engine.begin.return_value = _CM(conn)
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

    storage = MagicMock()
    monkeypatch.setattr(
        main.MinioStorage, "create", AsyncMock(return_value=storage)
    )

    async with main.lifespan(MagicMock()):
        pass

    storage.ensure_bucket.assert_called_once()
    scheduler.start.assert_awaited_once()
    scheduler.stop.assert_awaited_once()
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_bucket_failure_does_not_block_startup(monkeypatch, caplog):
    import logging

    import backend.main as main

    conn = AsyncMock()
    columns_result = MagicMock()
    columns_result.scalar_one.return_value = 1
    conn.execute.return_value = columns_result

    engine = MagicMock()
    engine.begin.return_value = _CM(conn)
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

    storage = MagicMock()
    storage.ensure_bucket.side_effect = RuntimeError("minio down")
    monkeypatch.setattr(
        main.MinioStorage, "create", AsyncMock(return_value=storage)
    )

    with caplog.at_level(logging.WARNING, logger="backend.main"):
        async with main.lifespan(MagicMock()):
            pass  # 不因 MinIO 故障中断启动

    scheduler.start.assert_awaited_once()
    assert "MinIO" in caplog.text
