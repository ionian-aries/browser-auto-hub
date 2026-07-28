"""Pipeline 业务表名动态解析。

通过 TABLE_ 前缀环境变量覆盖默认表名。
例：TABLE_inbox_documents=skill_custom_inbox_documents

零配置时返回代码中的默认值，开箱即用。
"""

import os


def resolve_table(logical_name: str, default: str) -> str:
    """返回物理表名：优先读环境变量 TABLE_{logical_name}，缺失则用 default。"""
    return os.environ.get(f"TABLE_{logical_name}", default)
