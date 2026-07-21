from apscheduler import AsyncScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models.execution import TaskExecution
from backend.models.schedule import Schedule


class SchedulerManager:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self._scheduler = AsyncScheduler()

    async def start(self) -> None:
        await self._scheduler.__aenter__()
        await self.sync_all()

    async def stop(self) -> None:
        await self._scheduler.__aexit__(None, None, None)

    async def sync_all(self) -> None:
        """Load all enabled schedules from DB and register them."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Schedule).where(Schedule.enabled == True)
            )
            schedules = result.scalars().all()
            for schedule in schedules:
                await self._register_job(schedule)

    async def add_schedule(self, schedule: Schedule) -> None:
        if schedule.enabled:
            await self._register_job(schedule)

    async def remove_schedule(self, schedule_id: str) -> None:
        job_id = f"schedule_{schedule_id}"
        try:
            await self._scheduler.remove_job(job_id)
        except Exception:
            pass  # Job may not exist

    async def update_schedule(self, schedule: Schedule) -> None:
        await self.remove_schedule(schedule.id)
        if schedule.enabled:
            await self._register_job(schedule)

    async def _register_job(self, schedule: Schedule) -> None:
        job_id = f"schedule_{schedule.id}"
        trigger = self._build_trigger(schedule)
        if trigger is None:
            return

        await self._scheduler.add_job(
            self._execute_scheduled,
            trigger=trigger,
            id=job_id,
            kwargs={"schedule_id": schedule.id, "pipeline_id": schedule.pipeline_id},
            replace_existing=True,
        )

    def _build_trigger(self, schedule: Schedule):
        if schedule.trigger_type == "cron" and schedule.cron_expr:
            parts = schedule.cron_expr.split()
            if len(parts) == 5:
                return CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                )
        elif schedule.trigger_type == "interval" and schedule.interval_seconds:
            return IntervalTrigger(seconds=schedule.interval_seconds)
        return None

    async def _execute_scheduled(self, schedule_id: str, pipeline_id: str) -> None:
        from backend.services.runner import dispatch_execution

        async with self._session_factory() as session:
            # Load schedule for config
            result = await session.execute(
                select(Schedule).where(Schedule.id == schedule_id)
            )
            schedule = result.scalar_one_or_none()
            if schedule is None or not schedule.enabled:
                return

            # Create execution record
            execution = TaskExecution(
                pipeline_id=pipeline_id,
                schedule_id=schedule_id,
                trigger_type="scheduled",
                status="pending",
                config=schedule.config_override,
            )
            session.add(execution)
            await session.commit()
            await session.refresh(execution)

        await dispatch_execution(execution.id, self._session_factory)


# Module-level singleton, initialized in app lifespan
scheduler_manager: SchedulerManager | None = None
