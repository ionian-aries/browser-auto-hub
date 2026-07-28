from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models.schedule import Schedule
from backend.models.system_setting import SystemSetting

router = APIRouter(prefix="/api/system", tags=["system"])


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
    result = await session.execute(select(SystemSetting))
    rows = {row.key: row.value for row in result.scalars()}

    return {
        "log_retention_days": _safe_int(rows.get("log_retention_days", "30"), 30),
        "scheduler_enabled": rows.get("scheduler_enabled", "true") != "false",
        # 全局运行设置（三级覆盖链底层，见 spec 4 §8.2）
        "run_headless": rows.get("run_headless", "true") != "false",
        "run_close_browser": rows.get("run_close_browser", "true") != "false",
        "run_page_load_timeout": _safe_int(rows.get("run_page_load_timeout", "15000"), 15000),
        "run_element_visible_timeout": _safe_int(rows.get("run_element_visible_timeout", "5000"), 5000),
        "run_action_settle_timeout": _safe_int(rows.get("run_action_settle_timeout", "500"), 500),
        "run_default_max_retries": _safe_int(rows.get("run_default_max_retries", "0"), 0),
        "run_default_retry_delay_seconds": _safe_int(rows.get("run_default_retry_delay_seconds", "60"), 60),
    }


class SettingsUpdate(BaseModel):
    log_retention_days: int | None = None
    scheduler_enabled: bool | None = None
    run_headless: bool | None = None
    run_close_browser: bool | None = None
    run_page_load_timeout: int | None = None
    run_element_visible_timeout: int | None = None
    run_action_settle_timeout: int | None = None
    run_default_max_retries: int | None = None
    run_default_retry_delay_seconds: int | None = None


@router.put("/settings")
async def update_system_settings(
    body: SettingsUpdate, session: AsyncSession = Depends(get_session)
):
    updates = body.model_dump(exclude_unset=True)

    scheduler_enabled = updates.get("scheduler_enabled")

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

    return {"status": "ok"}
