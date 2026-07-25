"""Config 数据结构定义 + 继承解析（spec §3）"""

from __future__ import annotations


def resolve_config(source: dict, entry: dict) -> dict:
    """entry 级覆盖，未定义则 fallback 到 source 级。

    Returns:
        {"list": {...}, "pagination": {...} | None, "detail": {...}}
    """
    entry_configs = entry.get("configs", {})
    source_configs = source["configs"]
    return {
        "list":       entry_configs.get("list")       or source_configs["list"],
        "pagination": entry_configs.get("pagination") or source_configs.get("pagination"),
        "detail":     entry_configs.get("detail")     or source_configs.get("detail"),
    }
