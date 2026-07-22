from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_merged_settings, get_settings, write_env_value
from backend.database import _get_engine, get_session, mask_db_url, swap_engine
from backend.models.schedule import Schedule
from backend.models.system_setting import SystemSetting

router = APIRouter(prefix="/api/system", tags=["system"])

MASKED = "***"


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
        "scheduler_status": scheduler_status,
        "active_schedules": active_schedules,
    }


def _safe_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@router.get("/settings")
async def get_system_settings(session: AsyncSession = Depends(get_session)):
    merged = await get_merged_settings(session)
    result = await session.execute(select(SystemSetting))
    rows = {row.key: row.value for row in result.scalars()}

    return {
        "minio_endpoint": merged.minio_endpoint,
        "minio_access_key": merged.minio_access_key,
        "minio_secret_key": MASKED,  # never return the real secret
        "minio_bucket": merged.minio_bucket,
        "minio_object_prefix": merged.minio_object_prefix,
        "minio_presign_expires_seconds": merged.minio_presign_expires_seconds,
        "log_retention_days": _safe_int(rows.get("log_retention_days", "30"), 30),
        "scheduler_enabled": rows.get("scheduler_enabled", "true") != "false",
        "database_url": mask_db_url(get_settings().database_url),
    }


class SettingsUpdate(BaseModel):
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str | None = None
    minio_object_prefix: str | None = None
    minio_presign_expires_seconds: int | None = None
    log_retention_days: int | None = None
    scheduler_enabled: bool | None = None
    database_url: str | None = None


@router.put("/settings")
async def update_system_settings(
    body: SettingsUpdate, session: AsyncSession = Depends(get_session)
):
    updates = body.model_dump(exclude_unset=True)

    new_db_url = updates.pop("database_url", None)
    scheduler_enabled = updates.get("scheduler_enabled")

    # "***" or empty secret means unchanged
    secret = updates.get("minio_secret_key")
    if secret is not None and (secret == MASKED or secret == ""):
        updates.pop("minio_secret_key")

    # Persist system_settings rows
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

    # Scheduler toggle (after persist; guard stopped/absent scheduler)
    if scheduler_enabled is not None:
        from backend.scheduler.manager import scheduler_manager

        if scheduler_manager is not None:
            try:
                if scheduler_enabled:
                    await scheduler_manager.resume()
                else:
                    await scheduler_manager.pause()
            except Exception:
                pass

    # Database URL hot-swap last: the request-scoped session above belongs to
    # the old engine and must not be used afterwards.
    if new_db_url is not None:
        if MASKED not in new_db_url and new_db_url != get_settings().database_url:
            try:
                await swap_engine(new_db_url)
            except Exception as e:
                raise HTTPException(400, f"Invalid database_url: {e}")
            write_env_value("DATABASE_URL", new_db_url)

    return {"status": "ok"}


@router.post("/storage/test")
async def test_storage(session: AsyncSession = Depends(get_session)):
    try:
        from backend.storage.minio_client import MinioStorage

        storage = await MinioStorage.create(session)
        storage.ensure_bucket()
        return {"status": "ok", "message": "MinIO connection successful"}
    except Exception as e:
        raise HTTPException(500, f"MinIO connection failed: {e}")


@router.post("/db/test")
async def test_db():
    try:
        engine = _get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(500, f"Database connection failed: {e}")
