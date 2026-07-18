from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database — 单一连接字符串，与 himea-agent-infra 保持一致
    database_url: str = "mysql+aiomysql://root:root@127.0.0.1:3306/browser_auto_hub?charset=utf8mb4"

    # MinIO — 与 oa-communicate-todos/config.json 参数对齐
    minio_endpoint: str = "http://localhost:9000"  # 完整URL，含协议前缀
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "browser-auto-hub"
    minio_object_prefix: str = "browser-auto-hub"
    minio_presign_expires_seconds: int = 604800  # 预签名URL过期时间，默认7天

    # App
    app_secret_key: str = "changeme"
    app_log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
