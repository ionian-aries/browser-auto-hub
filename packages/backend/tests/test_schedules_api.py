import inspect

import pytest

from backend.api.schedules import ScheduleEnabledUpdate, set_schedule_enabled


@pytest.mark.asyncio
async def test_list_schedules(client):
    response = await client.get("/api/schedules")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


def test_enabled_update_schema():
    """PATCH 请求体仅 enabled 且必填——显式目标态（spec 1 二十二次修订）。"""
    schema = ScheduleEnabledUpdate.model_json_schema()
    assert set(schema["properties"]) == {"enabled"}
    assert "enabled" in schema.get("required", [])


def test_patch_endpoint_signature():
    sig = inspect.signature(set_schedule_enabled)
    assert "schedule_id" in sig.parameters
    assert "body" in sig.parameters


@pytest.mark.asyncio
async def test_patch_requires_body(client):
    response = await client.patch("/api/schedules/some-id")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_patch_not_found(client):
    response = await client.patch("/api/schedules/some-id", json={"enabled": True})
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_toggle_endpoint_removed(client):
    """盲翻转 /toggle 已退役（spec 1 二十二次修订）。"""
    response = await client.patch("/api/schedules/some-id/toggle")
    assert response.status_code == 404

