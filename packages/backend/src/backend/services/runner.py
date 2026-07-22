import asyncio
import traceback
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.config import get_settings
from backend.models.execution import TaskExecution
from backend.models.schedule import Schedule
from backend.services.broadcaster import log_broadcaster
from backend.services.step_logger import DbStepLogger
from backend.storage.minio_client import MinioStorage
from engine.context import ExecutionContext
from engine.registry import PipelineRegistry


async def dispatch_execution(
    execution_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Run a pipeline execution in the background."""
    asyncio.create_task(_run_execution(execution_id, session_factory))


async def _check_concurrency(
    session: AsyncSession, pipeline_id: str, max_concurrent: int
) -> bool:
    """Return True if pipeline has capacity to run."""
    result = await session.execute(
        select(func.count())
        .select_from(TaskExecution)
        .where(
            TaskExecution.pipeline_id == pipeline_id,
            TaskExecution.status == "running",
        )
    )
    running_count = result.scalar() or 0
    return running_count < max_concurrent


async def _schedule_retry(
    execution: TaskExecution,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Schedule a retry if schedule allows it."""
    if execution.schedule_id is None:
        return  # manual/api triggers don't auto-retry

    result = await session.execute(
        select(Schedule).where(Schedule.id == execution.schedule_id)
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        return

    if execution.retry_count >= schedule.max_retries:
        return  # max retries reached

    pipeline_id = execution.pipeline_id
    schedule_id = execution.schedule_id
    config = execution.config
    retry_count = execution.retry_count + 1
    retry_delay = schedule.retry_delay_seconds

    async def _retry_after_delay():
        await asyncio.sleep(retry_delay)
        async with session_factory() as retry_session:
            retry_exec = TaskExecution(
                pipeline_id=pipeline_id,
                schedule_id=schedule_id,
                trigger_type="scheduled",
                config=config,
                retry_count=retry_count,
            )
            retry_session.add(retry_exec)
            await retry_session.commit()
            await dispatch_execution(retry_exec.id, session_factory)

    asyncio.create_task(_retry_after_delay())


async def _run_execution(
    execution_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        result = await session.execute(
            select(TaskExecution)
            .where(TaskExecution.id == execution_id)
            .with_for_update()
        )
        execution = result.scalar_one_or_none()
        if execution is None:
            return

        # Load pipeline info via relationship
        await session.refresh(execution, ["pipeline"])
        pipeline_db = execution.pipeline

        pipeline_cls = PipelineRegistry.get(pipeline_db.name)
        if pipeline_cls is None:
            execution.status = "failed"
            execution.error_message = (
                f"Pipeline '{pipeline_db.name}' not found in registry"
            )
            await session.commit()
            return

        # Concurrency check (row locked — prevents TOCTOU race)
        if not await _check_concurrency(
            session, pipeline_db.id, pipeline_db.max_concurrent
        ):
            execution.status = "failed"
            execution.error_message = (
                "Pipeline busy: max concurrent executions reached"
            )
            await session.commit()
            return

        # Start execution (commit releases the lock)
        execution.status = "running"
        execution.started_at = datetime.now(timezone.utc)
        await session.commit()

        storage = await MinioStorage.create(session)
        logger = DbStepLogger(execution_id, session, storage)
        settings = get_settings()

        ctx = ExecutionContext(
            logger=logger,
            db=session,
            minio=storage,
            settings=settings,
            execution_id=execution_id,
        )

        try:
            pipeline = pipeline_cls()
            # Execute with timeout
            exec_result = await asyncio.wait_for(
                pipeline.execute(execution.config or {}, ctx),
                timeout=pipeline_db.timeout_seconds,
            )

            execution.status = "success" if exec_result.success else "failed"
            execution.result_summary = exec_result.summary
            if exec_result.error:
                execution.error_message = exec_result.error
        except asyncio.TimeoutError:
            execution.status = "failed"
            execution.error_message = (
                f"Execution timeout after {pipeline_db.timeout_seconds}s"
            )
        except Exception as e:
            execution.status = "failed"
            execution.error_message = (
                f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
            )
        finally:
            execution.finished_at = datetime.now(timezone.utc)
            await session.commit()

            # Retry on failure
            if execution.status == "failed":
                await _schedule_retry(execution, session, session_factory)

            # Signal completion to SSE subscribers
            await log_broadcaster.publish(
                execution_id,
                {
                    "type": "complete",
                    "status": execution.status,
                },
            )
