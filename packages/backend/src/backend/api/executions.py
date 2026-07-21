import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from backend.database import get_session
from backend.models.execution import TaskExecution, TaskLog
from backend.models.pipeline import Pipeline
from backend.schemas.execution import ExecutionCreate, ExecutionResponse
from backend.services.broadcaster import log_broadcaster

router = APIRouter(prefix="/api/executions", tags=["executions"])


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

    execution = TaskExecution(
        pipeline_id=pipeline.id,
        trigger_type=body.trigger_type,
        status="pending",
        config=body.config,
    )
    session.add(execution)
    await session.commit()
    await session.refresh(execution)

    from backend.scheduler.manager import scheduler_manager
    if scheduler_manager and hasattr(scheduler_manager, '_session_factory'):
        from backend.services.runner import dispatch_execution
        await dispatch_execution(execution.id, scheduler_manager._session_factory)

    resp = ExecutionResponse.model_validate(execution)
    resp.pipeline_name = pipeline.name
    return resp


@router.get("", response_model=list[ExecutionResponse])
async def list_executions(
    pipeline: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(TaskExecution).order_by(TaskExecution.id.desc())
    if pipeline:
        stmt = stmt.join(Pipeline).where(Pipeline.name == pipeline)
    if status:
        stmt = stmt.where(TaskExecution.status == status)
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(stmt)
    return result.scalars().all()


@router.get("/{execution_id}", response_model=ExecutionResponse)
async def get_execution(
    execution_id: str, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(TaskExecution).where(TaskExecution.id == execution_id)
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        raise HTTPException(404, "Execution not found")
    return execution


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
async def stream_execution_logs(execution_id: str):
    queue = log_broadcaster.subscribe(execution_id)

    async def event_generator():
        try:
            while True:
                entry = await asyncio.wait_for(queue.get(), timeout=60.0)
                yield {"data": json.dumps(entry)}
                if entry.get("type") == "complete":
                    break
        except asyncio.TimeoutError:
            yield {"data": json.dumps({"type": "keepalive"})}
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
    return execution


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
