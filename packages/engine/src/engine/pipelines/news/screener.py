"""粗筛 + 细筛（class-based, 与 collector.py 接口对齐）"""

from __future__ import annotations

import asyncio
import json

from engine.pipelines.news.prompts import COARSE_SYSTEM, COARSE_USER, FINE_SYSTEM, FINE_USER


class Screener:
    """两阶段 LLM 筛选器。

    粗筛：批量分类 A/B/C
    细筛：逐篇 GATE→CLASSIFY→GENERATE→SCORE
    """

    def __init__(self, logger, concurrency: int = 3, llm_caller=None):
        self.logger = logger
        self.concurrency = concurrency
        self.llm_caller = llm_caller

    async def coarse_screen(
        self, items: list[dict], preferences: str, batch_size: int
    ) -> list[dict]:
        """批量粗筛，返回带有 category 字段的 items。

        category: A（强相关）/ B（弱相关）/ C（不相关）
        """
        if not self.llm_caller:
            return [{"category": "A", **it} for it in items]

        sem = asyncio.Semaphore(self.concurrency)
        results = []

        async def _process_batch(batch: list[dict]):
            async with sem:
                titles = "\n".join(
                    f"- [{i}] {it.get('title', '')} ({it.get('date', '')})"
                    for i, it in enumerate(batch)
                )
                user = COARSE_USER.format(
                    articles=titles, preferences=preferences or "无"
                )
                resp = await self.llm_caller(COARSE_SYSTEM, user)
                if not resp:
                    results.extend([{"category": "B", **it} for it in batch])
                    return
                try:
                    parsed = _parse_llm_json(resp)
                    decisions = parsed if isinstance(parsed, list) else []
                except Exception:
                    decisions = []
                for i, it in enumerate(batch):
                    cat = "B"
                    if i < len(decisions):
                        cat = decisions[i].get("category", "B")
                    results.append({"category": cat, **it})

        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            await _process_batch(batch)

        return results

    async def fine_screen(
        self, article: dict, detail: dict, preferences: str,
        start_date: str, end_date: str,
    ) -> dict:
        """逐篇细筛。返回 {decision, category, digest, insight, score, ...}。"""
        if not self.llm_caller:
            return {"decision": "pass", "category": "未分类", "score": 7.0}

        title = article.get("title", "")
        content = detail.get("content", "")[:4000]
        user = FINE_USER.format(
            title=title,
            content=content,
            date=article.get("date", ""),
            url=article.get("url", ""),
            start_date=start_date,
            end_date=end_date,
            preferences=preferences or "无",
        )
        resp = await self.llm_caller(FINE_SYSTEM, user)
        if not resp:
            return {"decision": "reject", "reject_reason": "LLM调用失败"}
        try:
            result = _parse_llm_json(resp)
            if not isinstance(result, dict):
                return {"decision": "reject", "reject_reason": "LLM返回格式异常"}
            return result
        except Exception:
            return {"decision": "reject", "reject_reason": "LLM返回解析失败"}


def _parse_llm_json(text: str):
    """从 LLM 返回文本中提取 JSON。"""
    import re
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    return json.loads(text)
