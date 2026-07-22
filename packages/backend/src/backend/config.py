import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings

# Repo root: packages/backend/src/backend/config.py -> parents[4]
REPO_ROOT = Path(__file__).resolve().parents[4]
ENV_PATH = REPO_ROOT / ".env"


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

    model_config = {"env_file": str(ENV_PATH), "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Runtime-overridable keys (merged from system_settings table)
OVERRIDABLE_KEYS = {
    "minio_endpoint",
    "minio_access_key",
    "minio_secret_key",
    "minio_bucket",
    "minio_object_prefix",
    "minio_presign_expires_seconds",
}


async def get_merged_settings(session) -> Settings:
    """Get settings with DB overrides applied."""
    from sqlalchemy import select
    from backend.models.system_setting import SystemSetting

    settings = get_settings()
    result = await session.execute(
        select(SystemSetting).where(SystemSetting.key.in_(OVERRIDABLE_KEYS))
    )
    overrides = {row.key: row.value for row in result.scalars()}

    if not overrides:
        return settings

    values = {}
    for key, raw in overrides.items():
        if key == "minio_presign_expires_seconds":
            try:
                values[key] = int(raw)
            except (TypeError, ValueError):
                continue
        else:
            values[key] = raw
    return settings.model_copy(update=values) if values else settings


def write_env_value(key: str, value: str, env_path: str | None = None) -> None:
    """Update or append KEY=value in .env, preserving all other lines.

    Writes atomically (temp file + os.replace). Clears the settings cache so
    future get_settings() reads pick up the new value.
    """
    path = Path(env_path) if env_path else ENV_PATH
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

    prefix = f"{key}="
    replaced = False
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = f"{prefix}{value}\n"
            replaced = True
            break
    if not replaced:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"{prefix}{value}\n")

    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text("".join(lines), encoding="utf-8")
    os.replace(tmp_path, path)

    get_settings.cache_clear()
