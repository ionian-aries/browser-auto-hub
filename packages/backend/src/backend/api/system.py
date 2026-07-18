from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models.execution import TaskExecution
from backend.models.pipeline import Pipeline
from backend.models.schedule import Schedule

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@router.get("/stats")
async def stats(session: AsyncSession = Depends(get_session)):
    pipeline_count = await session.scalar(
        select(func.count()).select_from(Pipeline).where(Pipeline.status == "active")
    )
    schedule_count = await session.scalar(
        select(func.count()).select_from(Schedule).where(Schedule.enabled == True)
    )
    total_executions = await session.scalar(
        select(func.count()).select_from(TaskExecution)
    )
    running_count = await session.scalar(
        select(func.count()).select_from(TaskExecution).where(TaskExecution.status == "running")
    )
    success_count = await session.scalar(
        select(func.count()).select_from(TaskExecution).where(TaskExecution.status == "success")
    )
    return {
        "pipelines": pipeline_count or 0,
        "schedules_active": schedule_count or 0,
        "executions_total": total_executions or 0,
        "executions_running": running_count or 0,
        "executions_success_rate": (
            round(success_count / total_executions * 100, 1) if total_executions else 0
        ),
    }
