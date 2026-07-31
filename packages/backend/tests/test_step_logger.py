"""DbStepLogger — 写入 task_logs 并广播 SSE（截图链路已退役，spec 1 十七次修订）。"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.step_logger import DbStepLogger


@pytest.mark.asyncio
async def test_step_writes_log_and_broadcasts():
    session = AsyncMock()
    session.add = MagicMock()  # SQLAlchemy add 是同步方法
    # 独立 session 工厂：日志即时 commit，与业务 session 解耦（刷新可见运行中日志）
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
    logger = DbStepLogger("e1", session_factory)

    with patch(
        "backend.services.step_logger.log_broadcaster.publish", new=AsyncMock()
    ) as publish:
        await logger.step("login", "登录成功", level="info")

    session.add.assert_called_once()
    log = session.add.call_args.args[0]
    assert log.execution_id == "e1"
    assert log.step_name == "login"
    assert log.message == "登录成功"
    session.commit.assert_awaited_once()

    publish.assert_awaited_once()
    entry = publish.call_args.args[1]
    assert entry["step"] == "login"
    assert entry["message"] == "登录成功"
    assert entry["level"] == "info"
    assert "screenshot_key" not in entry


def _make_logger(session):
    session.add = MagicMock()  # SQLAlchemy add 是同步方法
    session_factory = MagicMock()
    session_factory.return_value.__aenter__ = AsyncMock(return_value=session)
    session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return DbStepLogger("e1", session_factory)


@pytest.mark.asyncio
async def test_step_truncates_oversized_message():
    """超长日志（如 470 条采集明细）须按字节安全截断到 TEXT 列 64KB 内，不得抛 DataError。"""
    session = AsyncMock()
    logger = _make_logger(session)
    huge = "采集明细: 港口货物吞吐量同比增长\n" * 5000  # ~100KB UTF-8

    with patch(
        "backend.services.step_logger.log_broadcaster.publish", new=AsyncMock()
    ):
        await logger.step("crawl", huge, level="info")

    stored = session.add.call_args.args[0].message
    assert len(stored.encode("utf-8")) <= 65535
    assert "截断" in stored


@pytest.mark.asyncio
async def test_step_db_failure_does_not_kill_execution():
    """日志落库失败不得上抛杀死执行；SSE 广播仍应尝试。"""
    session = AsyncMock()
    session.commit.side_effect = Exception("Data too long")
    logger = _make_logger(session)

    with patch(
        "backend.services.step_logger.log_broadcaster.publish", new=AsyncMock()
    ) as publish:
        await logger.step("crawl", "任意消息", level="info")  # 不得 raise

    publish.assert_awaited_once()
