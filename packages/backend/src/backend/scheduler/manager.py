from datetime import datetime, timedelta, timezone

from apscheduler import AsyncScheduler, ConflictPolicy
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.models.execution import TaskArtifact, TaskExecution, TaskLog
from backend.models.schedule import Schedule
from backend.models.system_setting import SystemSetting


class SchedulerManager:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self._scheduler = AsyncScheduler()
        self._paused = False

    async def start(self) -> None:
        await self._scheduler.__aenter__()
        # APScheduler 4：__aenter__ 只初始化服务，必须显式启动调度循环，
        # 否则 add_schedule 静默成功但永不触发
        await self._scheduler.start_in_background()
        # System cleanup job always runs regardless of pause state.
        await self._scheduler.add_schedule(
            self._cleanup_old_executions,
            CronTrigger(hour=3, minute=0),
            id="system_cleanup",
            conflict_policy=ConflictPolicy.replace,
        )
        async with self._session_factory() as session:
            enabled = await self._get_setting(session, "scheduler_enabled", "true")
        if enabled == "false":
            self._paused = True
            return
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

    async def pause(self) -> None:
        """Remove all schedule jobs (DB enabled flags unchanged)."""
        self._paused = True
        async with self._session_factory() as session:
            result = await session.execute(select(Schedule.id))
            for (sid,) in result.all():
                await self.remove_schedule(sid)

    async def resume(self) -> None:
        self._paused = False
        await self.sync_all()

    @staticmethod
    async def _get_setting(
        session: AsyncSession, key: str, default: str
    ) -> str:
        """Read a system setting; return default if missing."""
        result = await session.execute(
            select(SystemSetting.value).where(SystemSetting.key == key)
        )
        value = result.scalar_one_or_none()
        return default if value is None else value

    @staticmethod
    def _compute_cutoff(days: int) -> datetime:
        """Naive-UTC cutoff datetime; executions older than this get deleted."""
        return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)

    async def _cleanup_old_executions(self) -> None:
        """Delete executions (and their logs/artifacts) older than log_retention_days."""
        async with self._session_factory() as session:
            days = await self._get_setting(session, "log_retention_days", "30")
            try:
                retention_days = int(days)
            except (TypeError, ValueError):
                retention_days = 30
            cutoff = self._compute_cutoff(retention_days)
            # Delete child rows first, then executions.
            await session.execute(
                delete(TaskLog).where(
                    TaskLog.execution_id.in_(
                        select(TaskExecution.id).where(
                            TaskExecution.created_at < cutoff
                        )
                    )
                )
            )
            await session.execute(
                delete(TaskArtifact).where(
                    TaskArtifact.execution_id.in_(
                        select(TaskExecution.id).where(
                            TaskExecution.created_at < cutoff
                        )
                    )
                )
            )
            await session.execute(
                delete(TaskExecution).where(TaskExecution.created_at < cutoff)
            )
            await session.commit()

    async def add_schedule(self, schedule: Schedule) -> None:
        if self._paused:
            return
        if schedule.enabled:
            await self._register_job(schedule)

    async def remove_schedule(self, schedule_id: str) -> None:
        job_id = f"schedule_{schedule_id}"
        try:
            await self._scheduler.remove_schedule(job_id)
        except Exception:
            pass  # Job may not exist

    async def update_schedule(self, schedule: Schedule) -> None:
        if self._paused:
            return
        await self.remove_schedule(schedule.id)
        if schedule.enabled:
            await self._register_job(schedule)

    async def _register_job(self, schedule: Schedule) -> None:
        job_id = f"schedule_{schedule.id}"
        trigger = self._build_trigger(schedule)
        if trigger is None:
            return

        await self._scheduler.add_schedule(
            self._execute_scheduled,
            trigger,
            id=job_id,
            kwargs={"schedule_id": schedule.id, "pipeline_id": schedule.pipeline_id},
            conflict_policy=ConflictPolicy.replace,
        )

    @staticmethod
    def _build_trigger(schedule: Schedule):
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
        elif schedule.trigger_type == "once" and schedule.run_at:
            # run_at is stored UTC-naive; DateTrigger needs tz-aware local time
            run_time = schedule.run_at
            if run_time.tzinfo is None:
                run_time = run_time.replace(tzinfo=timezone.utc).astimezone()
            return DateTrigger(run_time=run_time)
        return None

    async def _execute_scheduled(self, schedule_id: str, pipeline_id: str) -> None:
        from backend.models.pipeline import Pipeline
        from backend.services.runner import dispatch_execution

        async with self._session_factory() as session:
            # Load schedule for config
            result = await session.execute(
                select(Schedule).where(Schedule.id == schedule_id)
            )
            schedule = result.scalar_one_or_none()
            if schedule is None or not schedule.enabled:
                return

            # Skip disabled pipelines (job stays registered but produces no execution)
            pipeline = await session.get(Pipeline, pipeline_id)
            if pipeline is None or pipeline.status != "active":
                return

            # Create execution record
            execution = TaskExecution(
                pipeline_id=pipeline_id,
                schedule_id=schedule_id,
                trigger_type="scheduled",
                status="pending",
                config=schedule.config_override,
                pipeline_version=pipeline.version,  # 触发时版本快照（spec 1 §4.5）
            )
            session.add(execution)
            await session.commit()
            await session.refresh(execution)

            # One-shot schedules auto-disable after firing so restarts don't re-register them
            if schedule.trigger_type == "once":
                schedule.enabled = False
                await session.commit()

        await dispatch_execution(execution.id, self._session_factory)


# Module-level singleton, initialized in app lifespan
scheduler_manager: SchedulerManager | None = None
