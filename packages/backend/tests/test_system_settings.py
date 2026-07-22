# packages/backend/tests/test_system_settings.py
import pytest

from backend.models.system_setting import SystemSetting


def test_system_setting_model():
    s = SystemSetting(key="test_key", value="test_value")
    assert s.key == "test_key"
    assert s.value == "test_value"


def test_system_setting_tablename():
    assert SystemSetting.__tablename__ == "system_settings"


@pytest.mark.asyncio
async def test_settings_masks_minio_secret(client):
    """GET /settings 不得明文返回 minio_secret_key（PUT 端已按 MASKED 语义处理）。"""
    response = await client.get("/api/system/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["minio_secret_key"] in ("***", "")
