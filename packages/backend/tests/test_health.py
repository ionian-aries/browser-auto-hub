import pytest


@pytest.mark.asyncio
async def test_health_endpoint(client):
    response = await client.get("/api/system/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
