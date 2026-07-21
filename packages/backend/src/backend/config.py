from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "mysql+aiomysql://root:root@127.0.0.1:3306/browser_auto_hub?charset=utf8mb4"
    minio_endpoint: str = "http://localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "browser-auto-hub"
    minio_object_prefix: str = "browser-auto-hub"
    minio_presign_expires_seconds: int = 604800
    app_secret_key: str = "changeme"
    app_log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Runtime-overridable keys (merged from system_settings table)
OVERRIDABLE_KEYS = {"minio_object_prefix", "minio_presign_expires_seconds"}


async def get_merged_settings(session) -> Settings:
    """Get settings with DB overrides applied."""
    from sqlalchemy import select
    from backend.models.system_setting import SystemSetting

    settings = get_settings()
    result = await session.execute(
        select(SystemSetting).where(SystemSetting.key.in_(OVERRIDABLE_KEYS))
    )
    overrides = {row.key: row.value for row in result.scalars()}

    if overrides:
        values = {}
        if "minio_object_prefix" in overrides:
            values["minio_object_prefix"] = overrides["minio_object_prefix"]
        if "minio_presign_expires_seconds" in overrides:
            values["minio_presign_expires_seconds"] = int(overrides["minio_presign_expires_seconds"])
        if values:
            return settings.model_copy(update=values)
    return settings
