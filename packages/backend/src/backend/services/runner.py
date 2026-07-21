import asyncio
import traceback
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models.execution import TaskExecution
from backend.services.broadcaster import log_broadcaster
from backend.services.step_logger import DbStepLogger
from backend.storage.minio_client import MinioStorage
from engine.registry import PipelineRegistry


async def dispatch_execution(
    execution_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Run a pipeline execution in the background."""
    asyncio.create_task(_run_execution(execution_id, session_factory))


async def _run_execution(
    execution_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        result = await session.execute(
            select(TaskExecution).where(TaskExecution.id == execution_id)
        )
        execution = result.scalar_one_or_none()
        if execution is None:
            return

        # Get pipeline name via relationship
        await session.refresh(execution, ["pipeline"])
        pipeline_cls = PipelineRegistry.get(execution.pipeline.name)
        if pipeline_cls is None:
            execution.status = "failed"
            execution.error_message = f"Pipeline '{execution.pipeline.name}' not found in registry"
            await session.commit()
            return

        # Start execution
        execution.status = "running"
        execution.started_at = datetime.now(timezone.utc)
        await session.commit()

        storage = MinioStorage()
        logger = DbStepLogger(execution_id, session, storage)

        try:
            pipeline = pipeline_cls()
            result = await pipeline.execute(execution.config or {}, logger)

            execution.status = "success" if result.success else "failed"
            execution.result_summary = result.summary
            if result.error:
                execution.error_message = result.error
        except Exception as e:
            execution.status = "failed"
            execution.error_message = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        finally:
            execution.finished_at = datetime.now(timezone.utc)
            await session.commit()

            # Signal completion to SSE subscribers
            await log_broadcaster.publish(execution_id, {
                "type": "complete",
                "status": execution.status,
            })
