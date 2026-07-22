# packages/backend/tests/test_connection_config.py
from unittest.mock import AsyncMock, MagicMock

from backend.config import get_merged_settings, write_env_value
from backend.database import mask_db_url
from backend.models.system_setting import SystemSetting


# --- mask_db_url ---


def test_mask_db_url_hides_password():
    masked = mask_db_url(
        "mysql+aiomysql://root:supersecret@db.host:3306/browser_auto_hub?charset=utf8mb4"
    )
    assert "supersecret" not in masked
    assert "***" in masked
    assert "root" in masked
    assert "db.host:3306" in masked
    assert "browser_auto_hub" in masked
    assert "charset=utf8mb4" in masked


def test_mask_db_url_without_password_unchanged():
    masked = mask_db_url("sqlite+aiosqlite:///./local.db")
    assert "sqlite" in masked
    assert "local.db" in masked


# --- write_env_value ---


def test_write_env_value_replaces_existing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nKEY=old\nB=2\n", encoding="utf-8")
    write_env_value("KEY", "new", env_path=str(env))
    assert env.read_text(encoding="utf-8") == "A=1\nKEY=new\nB=2\n"


def test_write_env_value_appends_missing(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")
    write_env_value("KEY", "val", env_path=str(env))
    assert env.read_text(encoding="utf-8") == "A=1\nKEY=val\n"


def test_write_env_value_preserves_other_lines(tmp_path):
    env = tmp_path / ".env"
    original = "# comment\n\nA=1\nOTHER_KEY=x\n"
    env.write_text(original, encoding="utf-8")
    write_env_value("KEY", "val", env_path=str(env))
    content = env.read_text(encoding="utf-8")
    assert content.startswith(original)
    assert content.endswith("KEY=val\n")
    # lines starting with OTHER_KEY= must not be treated as KEY=
    assert "OTHER_KEY=x" in content


def test_write_env_value_handles_missing_trailing_newline(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1", encoding="utf-8")
    write_env_value("KEY", "val", env_path=str(env))
    assert env.read_text(encoding="utf-8") == "A=1\nKEY=val\n"


# --- get_merged_settings ---


def _mock_session_with_rows(rows):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value = rows
    session.execute.return_value = result
    return session


async def test_get_merged_settings_applies_minio_endpoint_override():
    session = _mock_session_with_rows(
        [SystemSetting(key="minio_endpoint", value="http://minio.internal:9000")]
    )
    merged = await get_merged_settings(session)
    assert merged.minio_endpoint == "http://minio.internal:9000"


async def test_get_merged_settings_applies_all_minio_overrides():
    session = _mock_session_with_rows(
        [
            SystemSetting(key="minio_endpoint", value="http://m:9000"),
            SystemSetting(key="minio_access_key", value="ak"),
            SystemSetting(key="minio_secret_key", value="sk"),
            SystemSetting(key="minio_bucket", value="bucket-x"),
            SystemSetting(key="minio_object_prefix", value="prefix-x"),
            SystemSetting(key="minio_presign_expires_seconds", value="3600"),
        ]
    )
    merged = await get_merged_settings(session)
    assert merged.minio_endpoint == "http://m:9000"
    assert merged.minio_access_key == "ak"
    assert merged.minio_secret_key == "sk"
    assert merged.minio_bucket == "bucket-x"
    assert merged.minio_object_prefix == "prefix-x"
    assert merged.minio_presign_expires_seconds == 3600
    assert isinstance(merged.minio_presign_expires_seconds, int)


async def test_get_merged_settings_ignores_bad_int_and_unrelated_keys():
    session = _mock_session_with_rows(
        [SystemSetting(key="minio_presign_expires_seconds", value="not-an-int")]
    )
    merged = await get_merged_settings(session)
    # Falls back to the .env/default value rather than crashing
    assert isinstance(merged.minio_presign_expires_seconds, int)


async def test_get_merged_settings_no_overrides_returns_base():
    from backend.config import get_settings

    session = _mock_session_with_rows([])
    merged = await get_merged_settings(session)
    assert merged is get_settings()
