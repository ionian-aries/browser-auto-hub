from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.api.executions import router as executions_router
from backend.api.files import router as files_router
from backend.api.pipelines import router as pipelines_router
from backend.api.schedules import router as schedules_router
from backend.api.system import router as system_router
from backend.config import get_settings
from backend.models import Base
from backend.scheduler.manager import SchedulerManager
from backend.services.pipeline_sync import sync_pipelines_to_db

import backend.scheduler.manager as scheduler_mod


async def _ensure_columns(conn) -> None:
    """Lightweight column migration: create_all won't ALTER existing tables."""
    from sqlalchemy import text

    result = await conn.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'schedules' "
            "AND column_name = 'run_at'"
        )
    )
    if result.scalar_one() == 0:
        await conn.execute(
            text("ALTER TABLE schedules ADD COLUMN run_at DATETIME(6) NULL")
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_size=5)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_columns(conn)

    # Session factory
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.session_factory = session_factory

    # Sync pipeline registry to DB
    async with session_factory() as session:
        await sync_pipelines_to_db(session)

    # Start scheduler
    scheduler = SchedulerManager(session_factory)
    scheduler_mod.scheduler_manager = scheduler
    await scheduler.start()

    yield

    # Shutdown
    await scheduler.stop()
    await engine.dispose()


app = FastAPI(title="Browser Auto Hub", version="0.1.0", lifespan=lifespan)
app.include_router(system_router)
app.include_router(pipelines_router)
app.include_router(schedules_router)
app.include_router(executions_router)
app.include_router(files_router)
