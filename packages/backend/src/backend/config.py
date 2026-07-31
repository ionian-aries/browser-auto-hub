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
    minio_object_prefix: str = "attachments"  # 对象键前缀，完全决定存储路径（spec 1 二十五次修订）
    # 平台对外地址：pipeline 拼接附件下载 URL（/api/files/{key}，spec 1 二十三次修订）
    public_base_url: str = "http://127.0.0.1:8900"
    cors_origins: str = "*"  # 逗号分隔；生产环境应收紧为具体域名

    # LLM 服务（pipeline 筛选/摘要等判断任务；OpenAI 兼容接口）
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_coarse_model: str = ""  # 粗筛模型
    llm_fine_model: str = ""    # 细筛模型


    model_config = {"env_file": str(ENV_PATH), "env_file_encoding": "utf-8", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
