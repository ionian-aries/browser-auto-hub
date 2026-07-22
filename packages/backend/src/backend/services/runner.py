import asyncio
import traceback
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.config import get_merged_settings
from backend.models.execution import TaskExecution
from backend.models.schedule import Schedule
from backend.models.system_setting import SystemSetting
from backend.services.broadcaster import log_broadcaster
from backend.services.step_logger import DbStepLogger
from backend.storage.minio_client import MinioStorage
from engine.context import ExecutionContext
from engine.registry import PipelineRegistry


async def _get_global_run_config(session: AsyncSession) -> dict:
    """Global run settings (system_settings run_*) as config-layer defaults.

    Override chain: these values sit at the bottom — execution.config wins.
    """
    result = await session.execute(
        select(SystemSetting).where(SystemSetting.key.like("run\\_%"))
    )
    rows = {row.key: row.value for row in result.scalars()}

    def _int(key: str, default: int) -> int:
        try:
            return int(rows[key])
        except (KeyError, TypeError, ValueError):
            return default

    return {
        "headless": rows.get("run_headless", "true") != "false",
        "close_browser": rows.get("run_close_browser", "true") != "false",
        "page_load_timeout": _int("run_page_load_timeout", 15000),
        "element_visible_timeout": _int("run_element_visible_timeout", 5000),
        "action_settle_timeout": _int("run_action_settle_timeout", 500),
    }


async def _get_global_retry_config(session: AsyncSession) -> tuple[int, int]:
    """run_default_max_retries / run_default_retry_delay_seconds（manual/api 执行的重试依据）。"""
    result = await session.execute(
        select(SystemSetting).where(
            SystemSetting.key.in_(
                ["run_default_max_retries", "run_default_retry_delay_seconds"]
            )
        )
    )
    rows = {row.key: row.value for row in result.scalars()}

    def _int(key: str, default: int) -> int:
        try:
            return int(rows[key])
        except (KeyError, TypeError, ValueError):
            return default

    return (
        _int("run_default_max_retries", 0),
        _int("run_default_retry_delay_seconds", 60),
    )


# execution_id → 正在运行的 asyncio Task（cancel 端点据此真正停止执行）
_running_tasks: dict[str, asyncio.Task] = {}
# retry / redispatch 等后台 sleeper task：防 GC、便于监督
_background_tasks: set[asyncio.Task] = set()

_BUSY_REDISPATCH_DELAY = 10  # seconds


def _track_background(task: asyncio.Task) -> None:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def dispatch_execution(
    execution_id: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Run a pipeline execution in the background."""
    task = asyncio.create_task(_run_execution(execution_id, session_factory))
    _running_tasks[execution_id] = task
    task.add_done_callback(lambda _t: _running_tasks.pop(execution_id, None))


def cancel_running_execution(execution_id: str) -> bool:
    """取消正在运行的执行 task；未在运行返回 False。"""
    task = _running_tasks.get(execution_id)
    if task is None or task.done():
        return False
    task.cancel()
    return True


async def _redispatch_later(
    execution_id: str, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await asyncio.sleep(_BUSY_REDISPATCH_DELAY)
    await dispatch_execution(execution_id, session_factory)


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
    """Schedule a retry if limits allow.

    scheduled 执行按 schedule 的 max_retries/retry_delay_seconds；
    manual/api 执行按全局 run_default_* 配置（默认为 0 = 不重试）。
    """
    if execution.schedule_id is not None:
        result = await session.execute(
            select(Schedule).where(Schedule.id == execution.schedule_id)
        )
        schedule = result.scalar_one_or_none()
        if schedule is None:
            return
        max_retries = schedule.max_retries
        retry_delay = schedule.retry_delay_seconds
    else:
        max_retries, retry_delay = await _get_global_retry_config(session)

    if execution.retry_count >= max_retries:
        return  # max retries reached

    pipeline_id = execution.pipeline_id
    schedule_id = execution.schedule_id
    trigger_type = execution.trigger_type  # 保留原始触发方式
    config = execution.config
    retry_count = execution.retry_count + 1

    async def _retry_after_delay():
        await asyncio.sleep(retry_delay)
        async with session_factory() as retry_session:
            retry_exec = TaskExecution(
                pipeline_id=pipeline_id,
                schedule_id=schedule_id,
                trigger_type=trigger_type,
                config=config,
                retry_count=retry_count,
            )
            retry_session.add(retry_exec)
            await retry_session.commit()
            await dispatch_execution(retry_exec.id, session_factory)

    _track_background(asyncio.create_task(_retry_after_delay()))


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
            # 保持 pending，延迟重派发；不再制造伪 failed 记录
            await session.rollback()  # 释放 FOR UPDATE 行锁
            _track_background(
                asyncio.create_task(
                    _redispatch_later(execution_id, session_factory)
                )
            )
            return

        # Start execution (commit releases the lock)
        execution.status = "running"
        execution.started_at = datetime.now(timezone.utc)
        await session.commit()

        settings = await get_merged_settings(session)
        storage = MinioStorage(settings=settings)
        logger = DbStepLogger(
            execution_id, session, storage, prefix=settings.minio_object_prefix
        )

        ctx = ExecutionContext(
            logger=logger,
            db=session,
            minio=storage,
            settings=settings,
            execution_id=execution_id,
        )

        try:
            pipeline = pipeline_cls()
            # 三级覆盖链：全局运行设置打底，execution.config 覆盖
            global_run = await _get_global_run_config(session)
            effective_config = {**global_run, **(execution.config or {})}
            # Execute with timeout
            exec_result = await asyncio.wait_for(
                pipeline.execute(effective_config, ctx),
                timeout=pipeline_db.timeout_seconds,
            )

            execution.status = "success" if exec_result.success else "failed"
            execution.result_summary = exec_result.summary
            if exec_result.error:
                execution.error_message = exec_result.error
        except asyncio.CancelledError:
            # cancel 端点取消了本 task：落 cancelled 终态后继续传播
            execution.status = "cancelled"
            execution.error_message = "Cancelled by user"
            raise
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
            try:
                await session.commit()
            except Exception:
                # session 被 pipeline 污染时的兜底：换全新 session 落终态
                await session.rollback()
                await _finalize_via_fresh_session(
                    session_factory,
                    execution_id,
                    status=execution.status,
                    finished_at=execution.finished_at,
                    error_message=execution.error_message,
                    result_summary=execution.result_summary,
                )

            # Retry on failure
            if execution.status == "failed":
                await _schedule_retry(execution, session, session_factory)

            # Signal completion to SSE subscribers（通知失败不应中断收尾）
            try:
                await log_broadcaster.publish(
                    execution_id,
                    {
                        "type": "complete",
                        "status": execution.status,
                    },
                )
            except Exception:
                pass


async def _finalize_via_fresh_session(
    session_factory: async_sessionmaker[AsyncSession],
    execution_id: str,
    *,
    status: str,
    finished_at: datetime,
    error_message: str | None,
    result_summary: dict | None,
) -> None:
    """Best-effort 终态落库：主 session 已污染时用独立 session 写入。"""
    try:
        async with session_factory() as s:
            result = await s.execute(
                select(TaskExecution).where(TaskExecution.id == execution_id)
            )
            ex = result.scalar_one_or_none()
            if ex is None:
                return
            ex.status = status
            ex.finished_at = finished_at
            ex.error_message = error_message
            ex.result_summary = result_summary
            await s.commit()
    except Exception:
        pass  # 兜底失败已无更多手段，保证 SSE 通知不被阻断
