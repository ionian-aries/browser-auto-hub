"""File-based config store tests (news_collector/config_store.py)."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from engine.pipelines.news_collector.config_store import (
    load_all_configs,
    load_config_by_base_url,
    save_source_config,
    update_entry_config,
    _CONFIG_PATH,
)


@pytest.fixture
def tmp_config(tmp_path):
    """Patch _CONFIG_PATH to a temp file for each test."""
    tmp_file = tmp_path / "config.json"
    sample = [
        {
            "source_name": "交通运输部",
            "base_url": "https://www.mot.gov.cn",
            "configs": {"list": {"mode": "selectors"}},
            "entries": [
                {"entry_name": "交通要闻", "url": "https://www.mot.gov.cn/xinwen/jiaotongyaowen/index.html"}
            ],
        },
        {
            "source_name": "新华社",
            "base_url": "https://www.news.cn",
            "configs": {"list": {"mode": "script"}},
            "entries": [],
        },
    ]
    tmp_file.write_text(json.dumps(sample, ensure_ascii=False), encoding="utf-8")
    with patch("engine.pipelines.news_collector.config_store._CONFIG_PATH", tmp_file):
        yield tmp_file


class TestLoadAllConfigs:
    def test_load_returns_list(self, tmp_config):
        result = load_all_configs()
        assert isinstance(result, list)
        assert len(result) == 2

    def test_load_empty_when_no_file(self, tmp_path):
        missing = tmp_path / "missing.json"
        with patch("engine.pipelines.news_collector.config_store._CONFIG_PATH", missing):
            result = load_all_configs()
            assert result == []


class TestLoadConfigByBaseUrl:
    def test_found(self, tmp_config):
        config = load_config_by_base_url("https://www.mot.gov.cn")
        assert config is not None
        assert config["source_name"] == "交通运输部"
        assert config["configs"]["list"]["mode"] == "selectors"

    def test_not_found(self, tmp_config):
        config = load_config_by_base_url("https://unknown.example.com")
        assert config is None


class TestSaveSourceConfig:
    def test_update_existing(self, tmp_config):
        new_cfg = {"list": {"mode": "script"}, "pagination": None, "detail": {}}
        save_source_config("交通运输部", "https://www.mot.gov.cn", new_cfg)
        loaded = load_config_by_base_url("https://www.mot.gov.cn")
        assert loaded["configs"]["list"]["mode"] == "script"

    def test_insert_new(self, tmp_config):
        cfg = {"list": {"mode": "selectors"}, "pagination": None, "detail": {}}
        save_source_config("新源", "https://new.example.com", cfg)
        loaded = load_config_by_base_url("https://new.example.com")
        assert loaded is not None
        assert loaded["source_name"] == "新源"

    def test_atomic_write(self, tmp_config):
        """写入后文件存在且 JSON 合法"""
        cfg = {"list": {"mode": "selectors"}}
        save_source_config("测试", "https://test.com", cfg)
        content = json.loads(tmp_config.read_text(encoding="utf-8"))
        assert isinstance(content, list)
        assert any(s["base_url"] == "https://test.com" for s in content)


class TestUpdateEntryConfig:
    def test_update_entry(self, tmp_config):
        entry_cfg = {"list": {"mode": "script"}}
        update_entry_config(
            "https://www.mot.gov.cn", "交通要闻", entry_cfg
        )
        sources = load_all_configs()
        mot = next(s for s in sources if s["base_url"] == "https://www.mot.gov.cn")
        entry = next(e for e in mot["entries"] if e["entry_name"] == "交通要闻")
        assert entry["configs"]["list"]["mode"] == "script"

    def test_noop_when_not_found(self, tmp_config):
        """entry 不存在时不报错"""
        update_entry_config(
            "https://www.mot.gov.cn", "不存在的入口", {"list": {}}
        )
        # 验证文件未被修改
        sources = load_all_configs()
        assert len(sources) == 2
