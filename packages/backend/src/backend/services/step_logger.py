import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.execution import TaskLog
from backend.services.broadcaster import log_broadcaster
from engine.logger import StepLogger

# Debug 日志目录
DEBUG_LOG_DIR = Path(__file__).resolve().parents[3] / "logs" / "debug"


class DbStepLogger(StepLogger):
    """StepLogger that writes to DB and broadcasts via SSE.

    Debug 模式：当 debug_path 不为 None 时，每个 step 的完整数据（含 data）
    以 JSONL 格式追加写入文件，可 tail -f 实时查看。
    """

    def __init__(
        self,
        execution_id: str,
        session: AsyncSession,
        debug_path: Path | None = None,
    ):
        super().__init__(execution_id)
        self._session = session
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

        log = TaskLog(
            execution_id=self.execution_id,
            timestamp=now,
            level=level,
            step_name=name,
            message=message,
        )
        self._session.add(log)
        await self._session.flush()

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
