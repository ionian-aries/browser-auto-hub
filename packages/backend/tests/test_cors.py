"""CORS middleware — preflight must be answered."""
import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_cors_preflight_allowed():
    from backend.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        resp = await ac.options(
            "/api/system/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") in (
        "*",
        "http://localhost:5173",
    )
