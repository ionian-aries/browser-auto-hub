from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.database import get_session
from backend.models.pipeline import Pipeline
from backend.models.schedule import Schedule
from backend.schemas.schedule import ScheduleCreate, ScheduleResponse, ScheduleUpdate

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


def _to_response(s: Schedule) -> ScheduleResponse:
    resp = ScheduleResponse.model_validate(s)
    if s.pipeline:
        resp.pipeline_name = s.pipeline.name
        resp.pipeline_display_name = s.pipeline.display_name
    resp.next_run_at = _compute_next_run(s)
    return resp


def _compute_next_run(s: Schedule):
    """Compute next fire time from the trigger definition (not persisted)."""
    if not s.enabled:
        return None
    from backend.scheduler.manager import SchedulerManager

    trigger = SchedulerManager._build_trigger(s)
    return trigger.next() if trigger is not None else None


def _to_utc_naive(dt: datetime | None) -> datetime | None:
    """DB contract is UTC-naive; UTCDateTime strips tz without converting, so convert first."""
    if dt is not None and dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _validate_trigger(trigger_type: str, cron_expr, interval_seconds, run_at) -> None:
    if trigger_type == "cron" and not cron_expr:
        raise HTTPException(400, "cron 触发必须提供 cron 表达式")
    if trigger_type == "interval" and not interval_seconds:
        raise HTTPException(400, "固定间隔触发必须提供间隔秒数")
    if trigger_type == "once":
        if run_at is None:
            raise HTTPException(400, "单次定时必须提供执行时刻")
        naive = (
            run_at.astimezone(timezone.utc).replace(tzinfo=None)
            if run_at.tzinfo
            else run_at
        )
        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        if naive < utc_now - timedelta(minutes=1):
            raise HTTPException(400, "执行时刻不能早于当前时间")


@router.get("", response_model=list[ScheduleResponse])
async def list_schedules(
    pipeline_id: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    stmt = (
        select(Schedule)
        .options(selectinload(Schedule.pipeline))
        .order_by(Schedule.id.desc())
    )
    if pipeline_id:
        stmt = stmt.where(Schedule.pipeline_id == pipeline_id)
    result = await session.execute(stmt)
    return [_to_response(s) for s in result.scalars().all()]


@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(
    schedule_id: str, session: AsyncSession = Depends(get_session)
):
    """单条调度回显（/run 页 edit 模式）。"""
    result = await session.execute(
        select(Schedule)
        .options(selectinload(Schedule.pipeline))
        .where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise HTTPException(404, "Schedule not found")
    return _to_response(schedule)


@router.post("", response_model=ScheduleResponse, status_code=201)
async def create_schedule(
    body: ScheduleCreate, session: AsyncSession = Depends(get_session)
):
    # Resolve pipeline
    result = await session.execute(
        select(Pipeline).where(Pipeline.id == body.pipeline_id)
    )
    pipeline = result.scalar_one_or_none()
    if pipeline is None:
        raise HTTPException(404, f"Pipeline '{body.pipeline_id}' not found")

    _validate_trigger(body.trigger_type, body.cron_expr, body.interval_seconds, body.run_at)

    schedule = Schedule(
        pipeline_id=pipeline.id,
        name=body.name,
        trigger_type=body.trigger_type,
        cron_expr=body.cron_expr,
        interval_seconds=body.interval_seconds,
        run_at=_to_utc_naive(body.run_at),
        config_override=body.config_override,
        enabled=body.enabled,
        max_retries=body.max_retries,
        retry_delay_seconds=body.retry_delay_seconds,
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)

    from backend.scheduler.manager import scheduler_manager

    if scheduler_manager is not None:
        await scheduler_manager.add_schedule(schedule)

    resp = _to_response(schedule)
    resp.pipeline_name = pipeline.name
    resp.pipeline_display_name = pipeline.display_name
    return resp


@router.put("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: str, body: ScheduleUpdate, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(Schedule)
        .options(selectinload(Schedule.pipeline))
        .where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise HTTPException(404, "Schedule not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(schedule, field, value)
    schedule.run_at = _to_utc_naive(schedule.run_at)

    _validate_trigger(
        schedule.trigger_type,
        schedule.cron_expr,
        schedule.interval_seconds,
        schedule.run_at,
    )

    await session.commit()
    await session.refresh(schedule)

    from backend.scheduler.manager import scheduler_manager

    if scheduler_manager is not None:
        await scheduler_manager.update_schedule(schedule)

    return _to_response(schedule)


@router.delete("/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: str, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(select(Schedule).where(Schedule.id == schedule_id))
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise HTTPException(404, "Schedule not found")
    await session.delete(schedule)
    await session.commit()

    from backend.scheduler.manager import scheduler_manager

    if scheduler_manager is not None:
        await scheduler_manager.remove_schedule(schedule_id)


@router.patch("/{schedule_id}/toggle", response_model=ScheduleResponse)
async def toggle_schedule(
    schedule_id: str, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(Schedule)
        .options(selectinload(Schedule.pipeline))
        .where(Schedule.id == schedule_id)
    )
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise HTTPException(404, "Schedule not found")
    schedule.enabled = not schedule.enabled
    await session.commit()
    await session.refresh(schedule)

    from backend.scheduler.manager import scheduler_manager

    if scheduler_manager is not None:
        await scheduler_manager.update_schedule(schedule)

    return _to_response(schedule)
