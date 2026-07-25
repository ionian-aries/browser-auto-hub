"""NewsCollectorPipeline 注册 + execute 测试（spec §6 Task 8）"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from engine.base import PipelineResult
from engine.registry import PipelineRegistry


@pytest.fixture(autouse=True)
def _clear_registry():
    PipelineRegistry._pipelines.clear()
    yield
    PipelineRegistry._pipelines.clear()


class TestNewsCollectorRegistration:
    def test_pipeline_registered(self):
        """import 触发 @register_pipeline 注册。"""
        import engine.pipelines.news_collector.collector  # noqa: F401

        p = PipelineRegistry.get("news.collector")
        assert p is not None
        assert p.metadata.display_name == "资讯采集"
        assert "cron" in p.metadata.trigger_modes
        assert "manual" in p.metadata.trigger_modes

    def test_pipeline_discover(self):
        """PipelineRegistry.discover() 能自动发现 news.collector。"""
        PipelineRegistry.discover()
        p = PipelineRegistry.get("news.collector")
        assert p is not None
        assert p.metadata.name == "news.collector"


class TestNewsCollectorExecute:
    @pytest.mark.asyncio
    async def test_execute_returns_result(self):
        """execute() 委托 _run_pipeline，返回 PipelineResult。"""
        from engine.pipelines.news_collector.collector import NewsCollectorPipeline

        pipeline = NewsCollectorPipeline()
        ctx = MagicMock()
        ctx.logger = MagicMock()
        ctx.logger.step = AsyncMock()
        ctx.logger.error = AsyncMock()
        ctx.db = AsyncMock()
        ctx.execution_id = "test-123"

        config = {
            "sources": [
                {
                    "name": "测试源",
                    "base_url": "https://example.com",
                    "entries": [{"name": "要闻", "url": "https://example.com/news"}],
                }
            ],
            "start_date": "2026-06-01",
            "end_date": "2026-06-30",
        }

        with patch(
            "engine.pipelines.news_collector.collector._run_pipeline",
            new_callable=AsyncMock,
            return_value=PipelineResult(success=True, summary={"total": 0}),
        ):
            result = await pipeline.execute(config, ctx)
            assert result.success is True
            assert result.summary == {"total": 0}

    @pytest.mark.asyncio
    async def test_execute_catches_exception(self):
        """_run_pipeline 抛异常时 execute() 捕获并返回 success=False。"""
        from engine.pipelines.news_collector.collector import NewsCollectorPipeline

        pipeline = NewsCollectorPipeline()
        ctx = MagicMock()
        ctx.logger = MagicMock()
        ctx.logger.error = AsyncMock()

        config = {
            "sources": [],
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        }

        with patch(
            "engine.pipelines.news_collector.collector._run_pipeline",
            new_callable=AsyncMock,
            side_effect=RuntimeError("boom"),
        ):
            result = await pipeline.execute(config, ctx)
            assert result.success is False
            assert "boom" in result.error

    @pytest.mark.asyncio
    async def test_execute_sets_defaults(self):
        """execute() 为缺失配置项注入默认值。"""
        from engine.pipelines.news_collector.collector import (
            NewsCollectorPipeline,
            _DEFAULT_RATE_LIMIT_MS,
            _DEFAULT_MAX_PAGES,
        )

        pipeline = NewsCollectorPipeline()
        ctx = MagicMock()
        ctx.logger = MagicMock()
        ctx.logger.error = AsyncMock()

        config = {
            "sources": [],
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        }

        captured = {}

        async def _capture(cfg, _ctx):
            captured.update(cfg)
            return PipelineResult(success=True)

        with patch(
            "engine.pipelines.news_collector.collector._run_pipeline",
            new_callable=AsyncMock,
            side_effect=_capture,
        ):
            await pipeline.execute(config, ctx)

        assert captured["headless"] is True
        assert captured["max_pages"] == _DEFAULT_MAX_PAGES
        assert captured["rate_limit_ms"] == _DEFAULT_RATE_LIMIT_MS
