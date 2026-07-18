import pytest


@pytest.mark.asyncio
async def test_list_pipelines(client):
    response = await client.get("/api/pipelines")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_get_pipeline_not_found(client):
    response = await client.get("/api/pipelines/nonexistent")
    assert response.status_code == 404
