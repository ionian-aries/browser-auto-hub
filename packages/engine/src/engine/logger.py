from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class LogEntry:
    timestamp: datetime
    level: str
    step_name: str
    message: str
    data: Any = None


class StepLogger:
    """Records structured step logs during pipeline execution.

    In production, this is subclassed by backend to write to DB + broadcast SSE.
    The base implementation stores logs in memory for testing.

    Debug 模式：step() 的 data 参数携带中间数据（采集列表、筛选结果、LLM 返回等），
    由 DbStepLogger 写入 JSONL 文件供 tail -f 实时查看。
    """

    def __init__(self, execution_id: str):
        self.execution_id = execution_id
        self.entries: list[LogEntry] = []

    async def step(
        self,
        name: str,
        message: str,
        level: str = "info",
        data: Any = None,
    ) -> None:
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc),
            level=level,
            step_name=name,
            message=message,
            data=data,
        )
        self.entries.append(entry)

    async def error(self, name: str, message: str, data: Any = None) -> None:
        await self.step(name, message, level="error", data=data)

    async def warn(self, name: str, message: str, data: Any = None) -> None:
        await self.step(name, message, level="warn", data=data)
