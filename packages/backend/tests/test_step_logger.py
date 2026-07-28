"""DbStepLogger — 写入 task_logs 并广播 SSE（截图链路已退役，spec 1 十七次修订）。"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.step_logger import DbStepLogger


@pytest.mark.asyncio
async def test_step_writes_log_and_broadcasts():
    session = AsyncMock()
    session.add = MagicMock()  # SQLAlchemy add 是同步方法
    logger = DbStepLogger("e1", session)

    with patch(
        "backend.services.step_logger.log_broadcaster.publish", new=AsyncMock()
    ) as publish:
        await logger.step("login", "登录成功", level="info")

    session.add.assert_called_once()
    log = session.add.call_args.args[0]
    assert log.execution_id == "e1"
    assert log.step_name == "login"
    assert log.message == "登录成功"
    session.flush.assert_awaited_once()

    publish.assert_awaited_once()
    entry = publish.call_args.args[1]
    assert entry["step"] == "login"
    assert entry["message"] == "登录成功"
    assert entry["level"] == "info"
    assert "screenshot_key" not in entry
