import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.database import get_session
from backend.models.execution import TaskExecution
from backend.models.pipeline import Pipeline
from backend.models.schedule import Schedule
from backend.models.system_setting import SystemSetting

router = APIRouter(prefix="/api/system", tags=["system"])

_start_time = time.time()


@router.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@router.get("/info")
async def system_info(session: AsyncSession = Depends(get_session)):
    from backend.scheduler.manager import scheduler_manager

    active_schedules = await session.scalar(
        select(func.count()).select_from(Schedule).where(Schedule.enabled == True)
    ) or 0

    scheduler_status = "running"
    if scheduler_manager:
        scheduler_status = "paused" if getattr(scheduler_manager, "_paused", False) else "running"

    return {
        "uptime_seconds": int(time.time() - _start_time),
        "scheduler_status": scheduler_status,
        "active_schedules": active_schedules,
        "db_pool": {"pool_size": 5, "checked_out": 0, "overflow": 0},
    }


@router.get("/settings")
async def get_system_settings(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(SystemSetting))
    rows = result.scalars().all()
    settings = get_settings()

    # Merge: DB values override .env defaults; include read-only fields for frontend display
    defaults = {
        "minio_endpoint": settings.minio_endpoint,
        "minio_bucket": settings.minio_bucket,
        "minio_object_prefix": settings.minio_object_prefix,
        "minio_presign_expires_seconds": str(settings.minio_presign_expires_seconds),
        "log_retention_days": "30",
        "scheduler_enabled": "true",
    }
    for row in rows:
        defaults[row.key] = row.value

    return defaults


class SettingsUpdate(BaseModel):
    minio_object_prefix: str | None = None
    minio_presign_expires_seconds: int | None = None
    log_retention_days: int | None = None
    scheduler_enabled: bool | None = None


@router.put("/settings")
async def update_system_settings(
    body: SettingsUpdate, session: AsyncSession = Depends(get_session)
):
    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        str_value = str(value).lower() if isinstance(value, bool) else str(value)
        result = await session.execute(
            select(SystemSetting).where(SystemSetting.key == key)
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = str_value
        else:
            session.add(SystemSetting(key=key, value=str_value))
    await session.commit()
    return {"status": "ok"}


@router.post("/storage/test")
async def test_storage():
    try:
        from backend.storage.minio_client import MinioStorage
        storage = MinioStorage()
        storage.ensure_bucket()
        return {"status": "ok", "message": "MinIO connection successful"}
    except Exception as e:
        raise HTTPException(500, f"MinIO connection failed: {e}")
