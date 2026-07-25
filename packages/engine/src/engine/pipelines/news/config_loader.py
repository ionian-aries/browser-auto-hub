"""Config 加载/合并/写回。

config.json 存储所有信源的采集配置，支持信源级默认 + entry 级覆盖。
探索Agent成功生成新配置后，通过 save_config() 原子写回。
"""

import json
import tempfile
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config() -> list[dict]:
    """读取 config.json，返回完整信源配置列表。"""
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def merge_entry_config(source_configs: dict, entry_configs: dict | None) -> dict:
    """合并信源级和entry级配置。

    合并规则：entry 中存在的功能组（list/pagination/detail）整体覆盖信源级，
    不存在的功能组继承信源级。不做字段级深度合并——功能组是最小覆盖单位。

    示例：
        source_configs = {"list": {...}, "pagination": {...}, "detail": {...}}
        entry_configs  = {"list": {...}}
        → 合并后 list 被覆盖，pagination 和 detail 继承信源级
    """
    if not entry_configs:
        return dict(source_configs)
    merged = {}
    for key in ("list", "pagination", "detail"):
        if key in entry_configs:
            merged[key] = entry_configs[key]
        else:
            merged[key] = source_configs.get(key)
    return merged


def save_config(config: list[dict]) -> None:
    """原子写入 config.json。

    先写临时文件再 rename，避免写入中断（进程被杀/磁盘满）导致配置文件损坏。
    """
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


def update_entry_config(
    config: list[dict], source_name: str, entry_name: str, new_configs: dict
) -> list[dict]:
    """探索成功后，将新 configs 写入对应 entry。

    返回更新后的完整配置列表，调用方需再调 save_config() 持久化。
    """
    for source in config:
        if source["source_name"] != source_name:
            continue
        for entry in source.get("entries", []):
            if entry["entry_name"] == entry_name:
                entry["configs"] = new_configs
                return config
    return config


def find_source_entry(
    config: list[dict], source_name: str, entry_name: str
) -> tuple[dict, dict] | None:
    """根据 source_name + entry_name 查找对应的 (source, entry)。"""
    for source in config:
        if source["source_name"] != source_name:
            continue
        for entry in source.get("entries", []):
            if entry["entry_name"] == entry_name:
                return source, entry
    return None
