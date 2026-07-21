from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models.pipeline import Pipeline
from backend.models.schedule import Schedule
from backend.schemas.schedule import ScheduleCreate, ScheduleResponse, ScheduleUpdate

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


@router.get("", response_model=list[ScheduleResponse])
async def list_schedules(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Schedule).order_by(Schedule.id.desc()))
    schedules = result.scalars().all()
    out = []
    for s in schedules:
        resp = ScheduleResponse.model_validate(s)
        if s.pipeline:
            resp.pipeline_name = s.pipeline.name
        out.append(resp)
    return out


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

    schedule = Schedule(
        pipeline_id=pipeline.id,
        name=body.name,
        trigger_type=body.trigger_type,
        cron_expr=body.cron_expr,
        interval_seconds=body.interval_seconds,
        config_override=body.config_override,
        enabled=body.enabled,
        max_retries=body.max_retries,
        retry_delay_seconds=body.retry_delay_seconds,
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    resp = ScheduleResponse.model_validate(schedule)
    resp.pipeline_name = pipeline.name
    return resp


@router.put("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(
    schedule_id: str, body: ScheduleUpdate, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(select(Schedule).where(Schedule.id == schedule_id))
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise HTTPException(404, "Schedule not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(schedule, field, value)

    await session.commit()
    await session.refresh(schedule)
    return ScheduleResponse.model_validate(schedule)


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


@router.patch("/{schedule_id}/toggle", response_model=ScheduleResponse)
async def toggle_schedule(
    schedule_id: str, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(select(Schedule).where(Schedule.id == schedule_id))
    schedule = result.scalar_one_or_none()
    if schedule is None:
        raise HTTPException(404, "Schedule not found")
    schedule.enabled = not schedule.enabled
    await session.commit()
    await session.refresh(schedule)
    return ScheduleResponse.model_validate(schedule)
