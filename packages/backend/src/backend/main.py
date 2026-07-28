from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.executions import router as executions_router
from backend.api.files import router as files_router
from backend.api.pipelines import router as pipelines_router
from backend.api.schedules import router as schedules_router
from backend.api.system import router as system_router
from backend.config import get_settings
from backend.database import get_engine, get_session_factory
from backend.scheduler.manager import SchedulerManager
from backend.services.pipeline_sync import sync_pipelines_to_db

import backend.scheduler.manager as scheduler_mod


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 十八次修订（spec 1）：基础设施只连不建——库表与 MinIO bucket 由部署方提前创建，
    # 启动不做 create_all / 列迁移 / ensure_bucket，连接失败即报错。
    engine = get_engine()
    session_factory = get_session_factory()

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

_cors_origins = [
    o.strip() for o in get_settings().cors_origins.split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

app.include_router(system_router)
app.include_router(pipelines_router)
app.include_router(schedules_router)
app.include_router(executions_router)
app.include_router(files_router)
