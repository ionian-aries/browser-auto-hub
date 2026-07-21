from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class LogEntry:
    timestamp: datetime
    level: str
    step_name: str
    message: str
    screenshot_key: str | None = None
    metadata: dict | None = None


class StepLogger:
    """Records structured step logs during pipeline execution.

    In production, this is subclassed by backend to write to DB + broadcast SSE.
    The base implementation stores logs in memory for testing.
    """

    def __init__(self, execution_id: str):
        self.execution_id = execution_id
        self.entries: list[LogEntry] = []

    async def step(
        self,
        name: str,
        message: str,
        level: str = "info",
        screenshot: bytes | None = None,
    ) -> None:
        entry = LogEntry(
            timestamp=datetime.now(timezone.utc),
            level=level,
            step_name=name,
            message=message,
        )
        self.entries.append(entry)

    async def error(self, name: str, message: str, screenshot: bytes | None = None) -> None:
        await self.step(name, message, level="error", screenshot=screenshot)
