import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI

from backend.api.system import router as system_router
from backend.api.pipelines import router as pipelines_router
from backend.api.schedules import router as schedules_router
from backend.api.executions import router as executions_router
from backend.api.sources import router as sources_router
from backend.database import get_session


@asynccontextmanager
async def _test_lifespan(app: FastAPI):
    yield


async def _mock_session():
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result
    yield session


@pytest.fixture
async def client():
    test_app = FastAPI(lifespan=_test_lifespan)
    test_app.include_router(system_router)
    test_app.include_router(pipelines_router)
    test_app.include_router(schedules_router)
    test_app.include_router(executions_router)
    test_app.include_router(sources_router)
    test_app.dependency_overrides[get_session] = _mock_session
    async with AsyncClient(
        transport=ASGITransport(app=test_app), base_url="http://test"
    ) as ac:
        yield ac
