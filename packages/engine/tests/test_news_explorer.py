"""Explorer tests — file-based config store (no DB)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from engine.pipelines.news_collector.explorer import explore_list, explore_detail


class TestExploreList:
    @pytest.mark.asyncio
    async def test_explore_generates_config(self):
        """探索 Agent 成功生成 config 并验证"""
        generated_config = {
            "list": {"mode": "selectors", "fields": {
                "container": "ul.news", "item": "li", "title": "a",
                "link": "a", "link_attr": "href", "date": "span"
            }},
            "pagination": None,
            "detail": {"mode": "selectors", "fields": {
                "title": "h1", "content": "div.content", "date": "span.date", "source": "span.src"
            }},
        }

        page = MagicMock()
        page.url = "https://example.com/news"
        page.evaluate = AsyncMock(return_value={"body": {}, "repeating_structures": [], "pagination_candidates": []})

        with patch("engine.pipelines.news_collector.explorer.call_llm_json",
                    new_callable=AsyncMock, return_value=generated_config), \
             patch("engine.pipelines.news_collector.explorer.try_extract_items",
                    new_callable=AsyncMock, return_value=[{"title": "test", "date": "2026-06-01", "url": "/1"}]), \
             patch("engine.pipelines.news_collector.explorer.save_source_config") as mock_save:
            result = await explore_list(page, "测试源", "https://example.com", max_retries=3)
            assert result is not None
            assert result["list"]["mode"] == "selectors"
            mock_save.assert_called_once_with("测试源", "https://example.com", generated_config)

    @pytest.mark.asyncio
    async def test_explore_fails_after_retries(self):
        """探索 Agent 多次失败后返回 None"""
        page = MagicMock()
        page.url = "https://example.com/news"
        page.evaluate = AsyncMock(return_value={"body": {}, "repeating_structures": [], "pagination_candidates": []})

        with patch("engine.pipelines.news_collector.explorer.call_llm_json",
                    new_callable=AsyncMock, return_value={"list": {}, "pagination": None, "detail": {}}), \
             patch("engine.pipelines.news_collector.explorer.try_extract_items",
                    new_callable=AsyncMock, return_value=[]):
            result = await explore_list(page, "测试源", "https://example.com", max_retries=2)
            assert result is None

    @pytest.mark.asyncio
    async def test_explore_retries_on_llm_parse_error(self):
        """LLM 返回无法解析为 JSON 时重试"""
        good_config = {
            "list": {"mode": "selectors", "fields": {
                "container": "ul", "item": "li", "title": "a",
                "link": "a", "link_attr": "href", "date": "span"
            }},
            "pagination": None,
            "detail": {"mode": "selectors", "fields": {
                "title": "h1", "content": "div.content", "date": "span.date", "source": "span.src"
            }},
        }

        page = MagicMock()
        page.url = "https://example.com/news"
        page.evaluate = AsyncMock(return_value={"body": {}, "repeating_structures": [], "pagination_candidates": []})

        with patch("engine.pipelines.news_collector.explorer.call_llm_json",
                    new_callable=AsyncMock,
                    side_effect=[ValueError("bad json"), good_config]), \
             patch("engine.pipelines.news_collector.explorer.try_extract_items",
                    new_callable=AsyncMock, return_value=[{"title": "t", "date": "2026-06-01", "url": "/1"}]), \
             patch("engine.pipelines.news_collector.explorer.save_source_config"):
            result = await explore_list(page, "测试源", "https://example.com", max_retries=3)
            assert result is not None


class TestExploreDetail:
    @pytest.mark.asyncio
    async def test_detail_success(self):
        """详情页探索成功"""
        generated_config = {
            "detail": {"mode": "selectors", "fields": {
                "title": "h1", "content": "div.content", "date": "span.date", "source": "span.src"
            }}
        }

        page = MagicMock()
        page.evaluate = AsyncMock(return_value={"body": {}, "repeating_structures": [], "pagination_candidates": []})

        with patch("engine.pipelines.news_collector.explorer.call_llm_json",
                    new_callable=AsyncMock, return_value=generated_config), \
             patch("engine.pipelines.news_collector.explorer.try_extract_detail",
                    new_callable=AsyncMock,
                    return_value={"title": "标题", "content": "正文内容" * 20, "date": "2026-06-01", "source": "新华社"}):
            result = await explore_detail(page, "https://example.com/news/1", max_retries=3)
            assert result is not None
            assert result["mode"] == "selectors"

    @pytest.mark.asyncio
    async def test_detail_fails_after_retries(self):
        """详情页多次失败返回 None"""
        page = MagicMock()
        page.evaluate = AsyncMock(return_value={"body": {}, "repeating_structures": [], "pagination_candidates": []})

        with patch("engine.pipelines.news_collector.explorer.call_llm_json",
                    new_callable=AsyncMock,
                    return_value={"detail": {"mode": "selectors", "fields": {
                        "title": "h1", "content": "div.c", "date": "span", "source": "span"
                    }}}), \
             patch("engine.pipelines.news_collector.explorer.try_extract_detail",
                    new_callable=AsyncMock, return_value=None):
            result = await explore_detail(page, "https://example.com/news/1", max_retries=2)
            assert result is None
