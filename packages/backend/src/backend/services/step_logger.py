import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from backend.models.execution import TaskLog
from backend.services.broadcaster import log_broadcaster
from engine.logger import StepLogger

# Debug 日志目录
DEBUG_LOG_DIR = Path(__file__).resolve().parents[3] / "logs" / "debug"

# task_logs.message 为 MySQL TEXT（65,535 字节）；utf8mb4 中文 3 字节/字符，
# 超长日志（如数百条采集明细）会触发 DataError 1406。预留余量按字节安全截断。
_MAX_MESSAGE_BYTES = 60000


def _truncate_message(message: str) -> str:
    """按 UTF-8 字节数截断到 TEXT 列容量内（decode errors=ignore 保证不切断多字节字符）。"""
    encoded = message.encode("utf-8")
    if len(encoded) <= _MAX_MESSAGE_BYTES:
        return message
    kept = encoded[:_MAX_MESSAGE_BYTES].decode("utf-8", errors="ignore")
    return f"{kept}\n…[日志过长已截断，原始 {len(message)} 字符]"


class DbStepLogger(StepLogger):
    """StepLogger that writes to DB and broadcasts via SSE.

    日志用独立 session 立即 commit，不用 pipeline 业务 session：
    1) 业务 session 只在终态 commit，运行中日志对其他连接不可见
       （刷新页面时 SSE backlog 回放读不到）；
    2) 日志 commit 不能顺带提交业务 session 的半事务状态。

    Debug 模式：当 debug_path 不为 None 时，每个 step 的完整数据（含 data）
    以 JSONL 格式追加写入文件，可 tail -f 实时查看。
    """

    def __init__(
        self,
        execution_id: str,
        session_factory: async_sessionmaker[AsyncSession],
        debug_path: Path | None = None,
    ):
        super().__init__(execution_id)
        self._session_factory = session_factory
        self._debug_path = debug_path
        if debug_path:
            debug_path.parent.mkdir(parents=True, exist_ok=True)

    async def step(
        self,
        name: str,
        message: str,
        level: str = "info",
        data: Any = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        message = _truncate_message(message)

        # 日志是观测设施：落库失败只降级为 stderr，绝不上抛杀死业务执行
        # （与下方 debug JSONL 写入的容错语义一致）
        try:
            async with self._session_factory() as session:
                session.add(TaskLog(
                    execution_id=self.execution_id,
                    timestamp=now,
                    level=level,
                    step_name=name,
                    message=message,
                ))
                await session.commit()
        except Exception as e:
            print(f"[DbStepLogger] 日志落库失败 {name}: {e}", file=sys.stderr)

        # Broadcast to SSE subscribers
        entry = {
            "timestamp": now.isoformat(),
            "level": level,
            "step": name,
            "message": message,
        }
        await log_broadcaster.publish(self.execution_id, entry)

        # Debug 模式：写入 JSONL 文件
        if self._debug_path and data is not None:
            debug_entry = {
                "timestamp": now.isoformat(),
                "level": level,
                "step": name,
                "message": message,
                "data": data,
            }
            try:
                with open(self._debug_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(debug_entry, ensure_ascii=False, default=str) + "\n")
                    f.flush()
            except Exception:
                pass  # debug 写入失败不阻断主流程
