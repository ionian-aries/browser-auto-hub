# packages/backend/tests/test_system_settings.py
from backend.models.system_setting import SystemSetting


def test_system_setting_model():
    s = SystemSetting(key="test_key", value="test_value")
    assert s.key == "test_key"
    assert s.value == "test_value"


def test_system_setting_tablename():
    assert SystemSetting.__tablename__ == "system_settings"
