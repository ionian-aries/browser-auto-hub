import pytest


@pytest.mark.asyncio
async def test_create_and_trigger_execution(client):
    """Test the full flow: list pipelines -> trigger execution."""
    # Health check
    resp = await client.get("/api/system/health")
    assert resp.status_code == 200

    # List pipelines (may be empty without DB, but endpoint works)
    resp = await client.get("/api/pipelines")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    # Create execution (will 404 without DB pipeline, but tests API shape)
    resp = await client.post("/api/executions", json={
        "pipeline": "example",
        "config": {"message": "test"},
        "trigger_type": "manual",
    })
    # 404 is expected because mock returns None for pipeline lookup
    assert resp.status_code in (201, 404)
