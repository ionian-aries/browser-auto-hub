"""screener 单元测试 — 粗筛 + 细筛"""

import pytest
from unittest.mock import AsyncMock, patch
from engine.pipelines.news_collector.screener import coarse_screen, fine_screen


class TestCoarseScreen:
    @pytest.mark.asyncio
    async def test_coarse_filters_rejected(self):
        items = [
            {"id": "1", "title": "港口吞吐量增长", "date": "2026-06-15", "url": "/1"},
            {"id": "2", "title": "教育部招生计划", "date": "2026-06-15", "url": "/2"},
        ]
        with patch(
            "engine.pipelines.news_collector.screener.call_llm_json",
            new_callable=AsyncMock,
            return_value={
                "results": [
                    {"id": "1", "decision": "pass"},
                    {"id": "2", "decision": "reject"},
                ]
            },
        ):
            result = await coarse_screen(items, "2026-06-01", "2026-06-30", None, 20)
            assert len(result) == 1
            assert result[0]["title"] == "港口吞吐量增长"

    @pytest.mark.asyncio
    async def test_coarse_batch_split(self):
        """25 items 拆成 2 批（20 + 5）"""
        items = [
            {"id": str(i), "title": f"标题{i}", "date": None, "url": f"/{i}"}
            for i in range(25)
        ]

        call_count = 0

        async def mock_llm(prompt, system=None):
            nonlocal call_count
            call_count += 1
            # 第一批 id 0-19，第二批 id 20-24
            if call_count == 1:
                ids = [str(i) for i in range(20)]
            else:
                ids = [str(i) for i in range(20, 25)]
            return {"results": [{"id": i, "decision": "pass"} for i in ids]}

        with patch(
            "engine.pipelines.news_collector.screener.call_llm_json",
            new_callable=AsyncMock,
            side_effect=mock_llm,
        ):
            result = await coarse_screen(items, "2026-06-01", "2026-06-30", None, 20)
            assert call_count == 2  # 25 items → 2 批
            assert len(result) == 25

    @pytest.mark.asyncio
    async def test_coarse_llm_failure_passes_all(self):
        """LLM 异常 → 该批次全部 pass"""
        items = [
            {"id": "1", "title": "某标题", "date": "2026-06-15", "url": "/1"},
            {"id": "2", "title": "另一标题", "date": "2026-06-15", "url": "/2"},
        ]
        with patch(
            "engine.pipelines.news_collector.screener.call_llm_json",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM 超时"),
        ):
            result = await coarse_screen(items, "2026-06-01", "2026-06-30", None, 20)
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_coarse_assigns_id_when_missing(self):
        """item 没有 id 字段时自动分配"""
        items = [
            {"title": "标题A", "date": "2026-06-15", "url": "/a"},
            {"title": "标题B", "date": "2026-06-15", "url": "/b"},
        ]
        with patch(
            "engine.pipelines.news_collector.screener.call_llm_json",
            new_callable=AsyncMock,
            return_value={
                "results": [
                    {"id": "0", "decision": "pass"},
                    {"id": "1", "decision": "reject"},
                ]
            },
        ):
            result = await coarse_screen(items, "2026-06-01", "2026-06-30", None, 20)
            assert len(result) == 1
            assert result[0]["title"] == "标题A"


class TestFineScreen:
    @pytest.mark.asyncio
    async def test_fine_pass(self):
        item = {
            "title": "港口建设",
            "content": "正文内容" * 50,
            "date": "2026-06-15",
            "url": "/1",
            "source_name": "交通运输部",
        }

        with patch(
            "engine.pipelines.news_collector.screener.call_llm_json",
            new_callable=AsyncMock,
            return_value={
                "decision": "pass",
                "doc_date": "2026-06-15",
                "category": "建设发展",
                "digest": "摘要",
                "insight": "行业观察",
                "score": 7.5,
                "score_reason": "信息质量高",
            },
        ):
            result = await fine_screen(item, "2026-06-01", "2026-06-30")
            assert result is not None
            assert result["score"] == 7.5
            assert result["category"] == "建设发展"
            assert result["digest"] == "摘要"
            assert result["insight"] == "行业观察"

    @pytest.mark.asyncio
    async def test_fine_reject(self):
        item = {
            "title": "无关内容",
            "content": "正文" * 50,
            "date": "2026-06-15",
            "url": "/1",
            "source_name": "x",
        }

        with patch(
            "engine.pipelines.news_collector.screener.call_llm_json",
            new_callable=AsyncMock,
            return_value={"decision": "reject", "reject_reason": "与港航无关"},
        ):
            result = await fine_screen(item, "2026-06-01", "2026-06-30")
            assert result is None

    @pytest.mark.asyncio
    async def test_fine_below_threshold(self):
        """score < 6.0 → 返回 None"""
        item = {
            "title": "低分",
            "content": "正文" * 50,
            "date": "2026-06-15",
            "url": "/1",
            "source_name": "x",
        }

        with patch(
            "engine.pipelines.news_collector.screener.call_llm_json",
            new_callable=AsyncMock,
            return_value={
                "decision": "pass",
                "doc_date": "2026-06-15",
                "category": "建设发展",
                "digest": "x",
                "insight": "x",
                "score": 4.5,
                "score_reason": "信息碎片",
            },
        ):
            result = await fine_screen(item, "2026-06-01", "2026-06-30")
            assert result is None

    @pytest.mark.asyncio
    async def test_fine_llm_failure_returns_none(self):
        """LLM 异常 → 返回 None"""
        item = {
            "title": "某文章",
            "content": "正文" * 50,
            "date": "2026-06-15",
            "url": "/1",
            "source_name": "x",
        }

        with patch(
            "engine.pipelines.news_collector.screener.call_llm_json",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM 超时"),
        ):
            result = await fine_screen(item, "2026-06-01", "2026-06-30")
            assert result is None

    @pytest.mark.asyncio
    async def test_fine_score_exactly_threshold(self):
        """score == 6.0 刚好通过"""
        item = {
            "title": "边界分",
            "content": "正文" * 50,
            "date": "2026-06-15",
            "url": "/1",
            "source_name": "x",
        }

        with patch(
            "engine.pipelines.news_collector.screener.call_llm_json",
            new_callable=AsyncMock,
            return_value={
                "decision": "pass",
                "doc_date": "2026-06-15",
                "category": "政策速读",
                "digest": "摘要内容",
                "insight": "观察",
                "score": 6.0,
                "score_reason": "刚好合格",
            },
        ):
            result = await fine_screen(item, "2026-06-01", "2026-06-30")
            assert result is not None
            assert result["score"] == 6.0
