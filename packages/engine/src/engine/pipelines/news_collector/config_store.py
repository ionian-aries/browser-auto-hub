"""Config DB 读写 — raw SQL via AsyncSession（spec §8.1）"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text


async def load_config(db: Any, base_url: str) -> dict | None:
    """从 news_source_configs 加载信源配置。

    Returns:
        包含 source_name 及展开后 config 的 dict，未找到返回 None。
    """
    result = await db.execute(
        text("SELECT source_name, config_json FROM news_source_configs "
             "WHERE base_url = :base_url LIMIT 1"),
        {"base_url": base_url},
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    config = (
        json.loads(row.config_json)
        if isinstance(row.config_json, str)
        else row.config_json
    )
    return {"source_name": row.source_name, **config}


async def save_config(
    db: Any, source_name: str, base_url: str, config_json: dict
) -> None:
    """UPSERT 信源配置到 news_source_configs。"""
    await db.execute(
        text(
            "INSERT INTO news_source_configs "
            "(source_name, base_url, config_json) "
            "VALUES (:name, :url, :cfg) "
            "ON DUPLICATE KEY UPDATE "
            "source_name = VALUES(source_name), "
            "config_json = VALUES(config_json), "
            "updated_at = CURRENT_TIMESTAMP(6)"
        ),
        {
            "name": source_name,
            "url": base_url,
            "cfg": json.dumps(config_json, ensure_ascii=False),
        },
    )
    await db.commit()


async def increment_explore_count(db: Any, base_url: str) -> None:
    """累加探索 Agent 触发次数。"""
    await db.execute(
        text(
            "UPDATE news_source_configs "
            "SET explore_count = explore_count + 1 "
            "WHERE base_url = :base_url"
        ),
        {"base_url": base_url},
    )
    await db.commit()
