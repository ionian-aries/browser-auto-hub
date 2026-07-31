"""ganghang_materials 表操作（ctx.db AsyncSession + raw SQL，engine 通用做法）。

表名经 resolve_table 解析（TABLE_ganghang_materials 环境变量可覆盖）。
所有函数只执行 SQL，commit 由调用方决定（本 pipeline per-item commit 保耐久）。
并发调用方必须用同一把锁串行（session 非并发安全）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from engine.table_names import resolve_table

TABLE = resolve_table("ganghang_materials", "ganghang_materials")


async def find_existing_urls(session: Any, urls: list[str]) -> set[str]:
    """返回 ganghang_materials 中已存在的 URL 集合。"""
    if not urls:
        return set()
    params = {f"u{i}": u for i, u in enumerate(urls)}
    placeholders = ",".join(f":{k}" for k in params)
    result = await session.execute(
        text(f"SELECT link_url FROM {TABLE} WHERE link_url IN ({placeholders})"),
        params,
    )
    return {row[0] for row in result.fetchall()}


async def insert_basic(session: Any, items: list[dict], execution_id: str) -> None:
    """INSERT 粗筛通过的基础行（INSERT IGNORE 防重复），回填 db_id / is_new / execution_id。

    execution_id 仅在真正 INSERT 时写入；INSERT IGNORE 跳过的复用行内容未变，
    归属不动（force 覆盖由 update_fine 负责刷新）。
    """
    sql = text(
        f"INSERT IGNORE INTO {TABLE}"
        " (title, content, link_url, execution_id, doc_date, website_name, category, digest)"
        " VALUES (:title, :content, :link_url, :execution_id, :doc_date, :website_name, '', '')"
    )
    id_sql = text(f"SELECT id FROM {TABLE} WHERE link_url = :link_url")
    for it in items:
        it["execution_id"] = execution_id
        result = await session.execute(sql, {
            "title": it["title"],
            "content": it.get("content", ""),
            "link_url": it["link_url"],
            "execution_id": execution_id,
            "doc_date": it["doc_date"],
            "website_name": it["website_name"],
        })
        row_id = result.lastrowid
        if not row_id:
            # INSERT IGNORE 跳过 → 复用已有行（force 模式），标记非新行
            row = (await session.execute(
                id_sql, {"link_url": it["link_url"]}
            )).fetchone()
            row_id = row[0] if row else None
            it["is_new"] = False
        else:
            it["is_new"] = True
        it["db_id"] = row_id


async def update_fine(session: Any, it: dict) -> None:
    """UPDATE 细筛结果到已存在的行（含 content/title 覆盖 + 细筛字段）。

    execution_id 随内容原子刷新：行的全部内容字段被本执行重写，
    归属（最后写入者）即本执行；updated_at 由 MySQL 自动刷新。
    """
    await session.execute(text(
        f"UPDATE {TABLE}"
        " SET title=:title, content=:content,"
        "     category=:category, digest=:digest, insight=:insight,"
        "     score=:score, score_reason=:score_reason, doc_date=:doc_date,"
        "     execution_id=:execution_id"
        " WHERE id=:id"
    ), {
        "title": it["title"],
        "content": it.get("content", ""),
        "category": it["category"],
        "digest": it["digest"],
        "insight": it.get("insight"),
        "score": it.get("score"),
        "score_reason": it.get("score_reason"),
        "doc_date": it["doc_date"],
        "execution_id": it.get("execution_id"),
        "id": it["db_id"],
    })


async def delete_rows(session: Any, ids: list[int]) -> int:
    """删除细筛拒绝的行，返回删除行数。"""
    if not ids:
        return 0
    params = {f"i{k}": v for k, v in enumerate(ids)}
    placeholders = ",".join(f":{k}" for k in params)
    result = await session.execute(
        text(f"DELETE FROM {TABLE} WHERE id IN ({placeholders})"), params
    )
    return result.rowcount


async def cleanup_unprocessed(session: Any, ids: list[int]) -> int:
    """清理本批插入但未被细筛 UPDATE 的行（category 仍为空），返回删除行数。"""
    if not ids:
        return 0
    params = {f"i{k}": v for k, v in enumerate(ids)}
    placeholders = ",".join(f":{k}" for k in params)
    result = await session.execute(
        text(f"DELETE FROM {TABLE} WHERE id IN ({placeholders}) AND category = ''"),
        params,
    )
    return result.rowcount
