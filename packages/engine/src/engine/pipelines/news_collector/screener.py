"""粗筛（批量 LLM）+ 细筛（逐篇 LLM）（spec §6 Phase 4/6）"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .llm_client import call_llm_json

_PROMPTS_DIR = Path(__file__).parent / "prompts"

_COARSE_PROMPT = (_PROMPTS_DIR / "news_coarse.txt").read_text(encoding="utf-8")
_FINE_PROMPT = (_PROMPTS_DIR / "news_fine.txt").read_text(encoding="utf-8")

# 细筛入库阈值
_SCORE_THRESHOLD = 6.0


async def coarse_screen(
    items: list[dict],
    start_date: str,
    end_date: str,
    preference: str | None,
    batch_size: int = 20,
) -> list[dict]:
    """批量粗筛，返回 decision=pass 的 items。

    Args:
        items: [{title, date, url, ...}, ...]
        start_date: 编撰周期起始（YYYY-MM-DD）
        end_date: 编撰周期终止（YYYY-MM-DD）
        preference: 用户自定义关注偏好（可选）
        batch_size: 每批条数，默认 20

    Returns:
        粗筛通过的 items 列表
    """
    # 为每条 item 分配临时 id（如缺失）
    for i, it in enumerate(items):
        it.setdefault("id", str(i))

    passed = []
    sem = asyncio.Semaphore(3)

    async def _process_batch(batch: list[dict]):
        async with sem:
            items_json = json.dumps(
                [
                    {
                        "id": it["id"],
                        "title": it.get("title", ""),
                        "doc_date": it.get("date"),
                        "link_url": it.get("url", ""),
                    }
                    for it in batch
                ],
                ensure_ascii=False,
            )
            prompt = _COARSE_PROMPT.replace("{start_date}", start_date)
            prompt = prompt.replace("{end_date}", end_date)
            if preference:
                prompt += f"\n\n## 额外关注\n{preference}"
            prompt += (
                f"\n\n## 输入\n```json\n"
                f'{{"start_date": "{start_date}", "end_date": "{end_date}", '
                f'"items": {items_json}}}\n```'
            )

            try:
                result = await call_llm_json(prompt)
                decisions = {r["id"]: r["decision"] for r in result.get("results", [])}
                for it in batch:
                    if decisions.get(it["id"]) == "pass":
                        passed.append(it)
            except Exception:
                # LLM 失败 → 该批次全部 pass（宁可多 pass 不可误 reject）
                passed.extend(batch)

    # 分批处理
    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        await _process_batch(batch)

    return passed


async def fine_screen(
    item: dict,
    start_date: str,
    end_date: str,
) -> dict | None:
    """单篇细筛。返回细筛结果（含 category/digest/insight/score），
    reject 或 score < 6.0 时返回 None。

    Args:
        item: 单条资讯 {title, content, date, url, source_name, ...}
        start_date: 编撰周期起始
        end_date: 编撰周期终止

    Returns:
        细筛结果 dict 或 None
    """
    prompt = _FINE_PROMPT.replace("{start_date}", start_date)
    prompt = prompt.replace("{end_date}", end_date)
    prompt += f"\n\n## 输入\n```json\n{json.dumps({
        'start_date': start_date,
        'end_date': end_date,
        'title': item.get('title', ''),
        'content': item.get('content', ''),
        'doc_date': item.get('date'),
        'link_url': item.get('url', ''),
    }, ensure_ascii=False)}\n```"

    try:
        result = await call_llm_json(prompt)
    except Exception:
        return None

    if result.get("decision") != "pass":
        return None

    score = result.get("score", 0)
    if isinstance(score, str):
        try:
            score = float(score)
        except ValueError:
            score = 0
    if score < _SCORE_THRESHOLD:
        return None

    return {
        "decision": "pass",
        "doc_date": result.get("doc_date", item.get("date")),
        "category": result.get("category", ""),
        "digest": result.get("digest", ""),
        "insight": result.get("insight", ""),
        "score": score,
        "score_reason": result.get("score_reason", ""),
    }
