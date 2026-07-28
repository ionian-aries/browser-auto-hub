# packages/backend/tests/test_system_settings.py
from backend.models.system_setting import SystemSetting


def test_system_setting_model():
    s = SystemSetting(key="test_key", value="test_value")
    assert s.key == "test_key"
    assert s.value == "test_value"


def test_system_setting_tablename():
    assert SystemSetting.__tablename__ == "system_settings"


import pytest


@pytest.mark.asyncio
async def test_settings_only_exposes_system_settings_keys(client):
    """十七次修订：minio_* 收归 .env；二十一次修订：database_url 亦不再经 API 暴露。
    settings API 仅返回 system_settings 表承载的运行旋钮。"""
    response = await client.get("/api/system/settings")
    assert response.status_code == 200
    data = response.json()
    assert not any(k.startswith("minio_") for k in data)
    assert "database_url" not in data
    assert "log_retention_days" in data
