"""Pipeline 业务表名动态解析。

通过 TABLE_ 前缀环境变量覆盖默认表名。
例：TABLE_inbox_documents=skill_custom_inbox_documents

零配置时返回代码中的默认值，开箱即用。
"""

import os
from pathlib import Path

# 加载 .env 文件（如果存在），确保 TABLE_* 环境变量可用
# 从 engine/table_names.py 向上 4 级到 repo root:
# table_names.py -> engine/ -> src/ -> engine(pkg)/ -> packages/ -> repo_root
_repo_root = Path(__file__).resolve().parents[4]
_env_file = _repo_root / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file, override=False)  # override=False: 已有环境变量不覆盖
    except ImportError:
        pass  # python-dotenv 未安装时静默降级


def resolve_table(logical_name: str, default: str) -> str:
    """返回物理表名：优先读环境变量 TABLE_{logical_name}，缺失则用 default。"""
    return os.environ.get(f"TABLE_{logical_name}", default)
