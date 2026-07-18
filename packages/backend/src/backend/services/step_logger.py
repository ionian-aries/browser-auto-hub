from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models.execution import TaskLog
from backend.services.broadcaster import log_broadcaster
from backend.storage.minio_client import MinioStorage
from engine.logger import StepLogger


class DbStepLogger(StepLogger):
    """StepLogger that writes to DB and broadcasts via SSE."""

    def __init__(self, execution_id: int, session: AsyncSession, storage: MinioStorage):
        super().__init__(execution_id)
        self._session = session
        self._storage = storage
        self._prefix = get_settings().minio_object_prefix

    async def step(
        self,
        name: str,
        message: str,
        level: str = "info",
        screenshot: bytes | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        screenshot_key = None

        if screenshot:
            screenshot_key = f"{self._prefix}/screenshots/{self.execution_id}/{name}_{now.strftime('%H%M%S%f')}.png"
            self._storage.upload(screenshot_key, screenshot, "image/png")

        log = TaskLog(
            execution_id=self.execution_id,
            timestamp=now,
            level=level,
            step_name=name,
            message=message,
            screenshot_key=screenshot_key,
        )
        self._session.add(log)
        await self._session.flush()

        # Broadcast to SSE subscribers
        entry = {
            "timestamp": now.isoformat(),
            "level": level,
            "step": name,
            "message": message,
            "screenshot_key": screenshot_key,
        }
        await log_broadcaster.publish(self.execution_id, entry)
