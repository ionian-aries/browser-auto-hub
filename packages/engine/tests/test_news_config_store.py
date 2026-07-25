import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from engine.pipelines.news_collector.config_store import (
    load_config,
    save_config,
    increment_explore_count,
)


class TestLoadConfig:
    @pytest.mark.asyncio
    async def test_load_config_found(self):
        row = MagicMock()
        row.config_json = json.dumps({"configs": {"list": {"mode": "selectors"}}})
        row.source_name = "交通运输部"

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = row
        db.execute = AsyncMock(return_value=result_mock)

        config = await load_config(db, "https://www.mot.gov.cn")
        assert config is not None
        assert config["source_name"] == "交通运输部"
        assert config["configs"]["list"]["mode"] == "selectors"

    @pytest.mark.asyncio
    async def test_load_config_found_dict(self):
        """config_json 可能已被 driver 反序列化为 dict（MySQL JSON 列）"""
        row = MagicMock()
        row.config_json = {"configs": {"list": {"mode": "script"}}}
        row.source_name = "新华社"

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = row
        db.execute = AsyncMock(return_value=result_mock)

        config = await load_config(db, "https://www.news.cn")
        assert config is not None
        assert config["source_name"] == "新华社"
        assert config["configs"]["list"]["mode"] == "script"

    @pytest.mark.asyncio
    async def test_load_config_not_found(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        config = await load_config(db, "https://unknown.example.com")
        assert config is None

    @pytest.mark.asyncio
    async def test_load_config_passes_base_url(self):
        """确认 SQL 参数中包含 base_url"""
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=result_mock)

        await load_config(db, "https://example.com")
        call_args = db.execute.call_args
        # params passed as second positional arg
        assert call_args[0][1]["base_url"] == "https://example.com"


class TestSaveConfig:
    @pytest.mark.asyncio
    async def test_save_config_insert(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        await save_config(
            db,
            "新华社",
            "https://www.news.cn",
            {"configs": {"list": {"mode": "selectors"}}},
        )
        assert db.execute.called
        assert db.commit.called

    @pytest.mark.asyncio
    async def test_save_config_passes_params(self):
        """确认 UPSERT SQL 参数正确"""
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        cfg = {"configs": {"list": {"mode": "selectors"}}}
        await save_config(db, "交通运输部", "https://www.mot.gov.cn", cfg)

        call_args = db.execute.call_args
        params = call_args[0][1]
        assert params["name"] == "交通运输部"
        assert params["url"] == "https://www.mot.gov.cn"
        assert json.loads(params["cfg"]) == cfg


class TestIncrementExploreCount:
    @pytest.mark.asyncio
    async def test_increment_explore_count(self):
        db = AsyncMock()
        db.execute = AsyncMock()
        db.commit = AsyncMock()

        await increment_explore_count(db, "https://www.mot.gov.cn")
        assert db.execute.called
        assert db.commit.called

        call_args = db.execute.call_args
        params = call_args[0][1]
        assert params["base_url"] == "https://www.mot.gov.cn"
