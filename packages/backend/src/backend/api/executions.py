import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from backend.database import get_session
from backend.models.execution import TaskExecution, TaskLog
from backend.models.pipeline import Pipeline
from backend.schemas.execution import (
    ExecutionCreate,
    ExecutionListResponse,
    ExecutionResponse,
)
from backend.services.broadcaster import log_broadcaster

router = APIRouter(prefix="/api/executions", tags=["executions"])

_SSE_KEEPALIVE_SECONDS = 15


@router.post("", response_model=ExecutionResponse, status_code=201)
async def create_execution(
    body: ExecutionCreate, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(Pipeline).where(Pipeline.name == body.pipeline)
    )
    pipeline = result.scalar_one_or_none()
    if pipeline is None:
        raise HTTPException(404, f"Pipeline '{body.pipeline}' not found")
    if pipeline.status != "active":
        raise HTTPException(400, "流水线已停用，无法触发执行")

    execution = TaskExecution(
        pipeline_id=pipeline.id,
        trigger_type=body.trigger_type,
        status="pending",
        config=body.config,
        pipeline_version=pipeline.version,  # 触发时版本快照（spec 1 §4.5）
    )
    session.add(execution)
    await session.commit()
    await session.refresh(execution)

    # 直接经全局 session_factory 派发；scheduler 缺席时执行不再空转
    from backend.database import get_session_factory
    from backend.services.runner import dispatch_execution
    await dispatch_execution(execution.id, get_session_factory())

    resp = ExecutionResponse.model_validate(execution)
    resp.pipeline_name = pipeline.name
    resp.pipeline_display_name = pipeline.display_name
    return resp


@router.get("", response_model=ExecutionListResponse)
async def list_executions(
    pipeline: str | None = None,
    status: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    stmt = (
        select(TaskExecution)
        .options(selectinload(TaskExecution.pipeline))
        # UUID 主键无顺序意义：按创建时间倒序，id 作同秒兜底
        .order_by(TaskExecution.created_at.desc(), TaskExecution.id.desc())
    )
    count_stmt = select(func.count()).select_from(TaskExecution)
    if pipeline:
        stmt = stmt.join(Pipeline).where(Pipeline.name == pipeline)
        count_stmt = count_stmt.join(Pipeline).where(Pipeline.name == pipeline)
    if status:
        stmt = stmt.where(TaskExecution.status.in_(status.split(",")))
        count_stmt = count_stmt.where(TaskExecution.status.in_(status.split(",")))
    if start:
        stmt = stmt.where(TaskExecution.created_at >= start.replace(tzinfo=None))
        count_stmt = count_stmt.where(
            TaskExecution.created_at >= start.replace(tzinfo=None)
        )
    if end:
        stmt = stmt.where(TaskExecution.created_at <= end.replace(tzinfo=None))
        count_stmt = count_stmt.where(
            TaskExecution.created_at <= end.replace(tzinfo=None)
        )

    total = await session.scalar(count_stmt) or 0
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(stmt)
    out = []
    for e in result.scalars().all():
        resp = ExecutionResponse.model_validate(e)
        if e.pipeline:
            resp.pipeline_name = e.pipeline.name
            resp.pipeline_display_name = e.pipeline.display_name
        out.append(resp)
    return {"total": total, "items": out}


def _local_today_start_utc_naive() -> datetime:
    """本地零点（业务日切割，spec 1 §14）转 UTC-naive，与 UTC 存储比对。"""
    local_midnight = datetime.now(timezone.utc).astimezone().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return local_midnight.astimezone(timezone.utc).replace(tzinfo=None)


@router.get("/stats")
async def execution_stats(session: AsyncSession = Depends(get_session)):
    today_start = _local_today_start_utc_naive()

    today_count = await session.scalar(
        select(func.count()).select_from(TaskExecution).where(
            TaskExecution.created_at >= today_start
        )
    ) or 0

    today_success = await session.scalar(
        select(func.count()).select_from(TaskExecution).where(
            TaskExecution.created_at >= today_start,
            TaskExecution.status == "success",
        )
    ) or 0

    today_failed = await session.scalar(
        select(func.count()).select_from(TaskExecution).where(
            TaskExecution.created_at >= today_start,
            TaskExecution.status == "failed",
        )
    ) or 0

    running_count = await session.scalar(
        select(func.count()).select_from(TaskExecution).where(
            TaskExecution.status == "running"
        )
    ) or 0

    success_rate = round(today_success / today_count, 2) if today_count > 0 else 0

    return {
        "today_count": today_count,
        "today_success": today_success,
        "today_failed": today_failed,
        "success_rate": success_rate,
        "running_count": running_count,
    }


@router.get("/{execution_id}", response_model=ExecutionResponse)
async def get_execution(
    execution_id: str, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(TaskExecution)
        .options(selectinload(TaskExecution.pipeline))
        .where(TaskExecution.id == execution_id)
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        raise HTTPException(404, "Execution not found")
    resp = ExecutionResponse.model_validate(execution)
    if execution.pipeline:
        resp.pipeline_name = execution.pipeline.name
        resp.pipeline_display_name = execution.pipeline.display_name
    return resp


@router.get("/{execution_id}/logs")
async def get_execution_logs(
    execution_id: str, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(TaskLog)
        .where(TaskLog.execution_id == execution_id)
        .order_by(TaskLog.timestamp)
    )
    logs = result.scalars().all()
    return [
        {
            "timestamp": log.timestamp.isoformat(),
            "level": log.level,
            "step": log.step_name,
            "message": log.message,
            "screenshot_key": log.screenshot_key,
        }
        for log in logs
    ]


@router.get("/{execution_id}/logs/stream")
async def stream_execution_logs(
    execution_id: str, session: AsyncSession = Depends(get_session)
):
    queue = log_broadcaster.subscribe(execution_id)

    # 断线/迟到补发：先回放已落库日志，再进入实时流
    result = await session.execute(
        select(TaskLog)
        .where(TaskLog.execution_id == execution_id)
        .order_by(TaskLog.timestamp)
    )
    backlog = [
        {
            "timestamp": log.timestamp.isoformat(),
            "level": log.level,
            "step": log.step_name,
            "message": log.message,
            "screenshot_key": log.screenshot_key,
        }
        for log in result.scalars().all()
    ]

    async def event_generator():
        try:
            for entry in backlog:
                yield {"data": json.dumps(entry)}
            while True:
                try:
                    entry = await asyncio.wait_for(
                        queue.get(), timeout=_SSE_KEEPALIVE_SECONDS
                    )
                except asyncio.TimeoutError:
                    # SSE 注释行心跳：保持连接且前端不会渲染成伪日志
                    yield {"comment": "keepalive"}
                    continue
                yield {"data": json.dumps(entry)}
                if entry.get("type") == "complete":
                    break
        finally:
            log_broadcaster.unsubscribe(execution_id, queue)

    return EventSourceResponse(event_generator())


@router.post("/{execution_id}/cancel", response_model=ExecutionResponse)
async def cancel_execution(
    execution_id: str, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(TaskExecution).where(TaskExecution.id == execution_id)
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        raise HTTPException(404, "Execution not found")
    if execution.status not in ("pending", "running"):
        raise HTTPException(400, f"Cannot cancel execution in '{execution.status}' state")
    execution.status = "cancelled"
    execution.finished_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(execution)

    # 真正停止后台 asyncio task；未在运行则忽略
    from backend.services.runner import cancel_running_execution
    cancel_running_execution(execution_id)
    return execution


@router.delete("/{execution_id}", status_code=204)
async def delete_execution(
    execution_id: str, session: AsyncSession = Depends(get_session)
):
    from sqlalchemy import delete as sql_delete

    from backend.models.execution import TaskArtifact

    result = await session.execute(
        select(TaskExecution).where(TaskExecution.id == execution_id)
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        raise HTTPException(404, "Execution not found")
    if execution.status in ("pending", "running"):
        raise HTTPException(400, "执行进行中，请先取消再删除")

    # 仅删除执行记录 + 日志 + 产物元数据行（FK 约束要求）；
    # MinIO 中的截图/产物文件与 pipeline 写入的业务数据一律保留（spec 4 §7.2）。
    await session.execute(
        sql_delete(TaskLog).where(TaskLog.execution_id == execution_id)
    )
    await session.execute(
        sql_delete(TaskArtifact).where(TaskArtifact.execution_id == execution_id)
    )
    await session.delete(execution)
    await session.commit()


@router.get("/{execution_id}/artifacts")
async def get_execution_artifacts(
    execution_id: str, session: AsyncSession = Depends(get_session)
):
    from backend.models.execution import TaskArtifact

    result = await session.execute(
        select(TaskArtifact).where(TaskArtifact.execution_id == execution_id)
    )
    artifacts = result.scalars().all()
    return [
        {
            "id": a.id,
            "file_name": a.file_name,
            "content_type": a.content_type,
            "size_bytes": a.size_bytes,
            "download_url": f"/api/files/{a.id}/download",
            "created_at": a.created_at.isoformat(),
        }
        for a in artifacts
    ]
