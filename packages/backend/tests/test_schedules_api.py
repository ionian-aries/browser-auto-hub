import pytest


@pytest.mark.asyncio
async def test_list_schedules(client):
    response = await client.get("/api/schedules")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
