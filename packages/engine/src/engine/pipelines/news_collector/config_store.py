"""Config 文件读写 — JSON 文件持久化（替代 DB 存储）。

config.json 存储所有信源的采集配置（selectors / script），
支持信源级默认 + entry 级覆盖。探索 Agent 成功生成新配置后，
通过 save_source_config() 原子写回。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

_CONFIG_PATH = Path(__file__).parent / "config.json"


def load_all_configs() -> list[dict]:
    """读取 config.json，返回完整信源配置列表。"""
    if not _CONFIG_PATH.exists():
        return []
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_config_by_base_url(base_url: str) -> dict | None:
    """按 base_url 查找信源配置。

    Returns:
        包含 source_name 及展开后 config 的 dict，未找到返回 None。
    """
    for source in load_all_configs():
        if source.get("base_url") == base_url:
            return source
    return None


def save_source_config(
    source_name: str, base_url: str, config_json: dict
) -> None:
    """UPSERT 信源配置到 config.json（原子写入）。

    如果 base_url 已存在，更新 configs 字段；否则新增一条。
    """
    sources = load_all_configs()
    found = False
    for source in sources:
        if source.get("base_url") == base_url:
            source["configs"] = config_json
            source["source_name"] = source_name
            found = True
            break
    if not found:
        sources.append({
            "source_name": source_name,
            "base_url": base_url,
            "configs": config_json,
            "entries": [],
        })
    _atomic_write(sources)


def update_entry_config(
    base_url: str, entry_name: str, entry_configs: dict
) -> None:
    """探索成功后，将新 configs 写入对应 entry。"""
    sources = load_all_configs()
    for source in sources:
        if source.get("base_url") != base_url:
            continue
        for entry in source.get("entries", []):
            if entry.get("entry_name") == entry_name:
                entry["configs"] = entry_configs
                _atomic_write(sources)
                return


def _atomic_write(config: list[dict]) -> None:
    """原子写入 config.json（先写临时文件再 rename）。"""
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=_CONFIG_PATH.parent, suffix=".tmp", prefix=".config_"
    )
    try:
        with open(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
            f.write("\n")
        Path(tmp_path).replace(_CONFIG_PATH)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise
