import pytest
from engine.pipelines.news_collector.config_schema import resolve_config


class TestResolveConfig:
    """entry 级覆盖 + source 级 fallback"""

    def test_entry_overrides_source_list(self):
        source = {
            "configs": {
                "list": {"mode": "selectors", "fields": {"container": "ul.old"}},
                "pagination": None,
                "detail": {"mode": "selectors", "fields": {"title": "h1"}},
            }
        }
        entry = {
            "configs": {
                "list": {"mode": "selectors", "fields": {"container": "ul.new"}},
            }
        }
        result = resolve_config(source, entry)
        assert result["list"]["fields"]["container"] == "ul.new"
        assert result["pagination"] is None
        assert result["detail"]["fields"]["title"] == "h1"

    def test_entry_without_configs_falls_back_to_source(self):
        source = {
            "configs": {
                "list": {"mode": "script", "fields": {"items": "() => []"}},
                "pagination": {"mode": "selectors", "fields": {"next": "a.next"}},
                "detail": {"mode": "selectors", "fields": {"title": "h1"}},
            }
        }
        entry = {}  # 无 configs
        result = resolve_config(source, entry)
        assert result["list"]["mode"] == "script"
        assert result["pagination"]["fields"]["next"] == "a.next"

    def test_pagination_null_means_no_pagination(self):
        source = {
            "configs": {
                "list": {"mode": "selectors", "fields": {}},
                "pagination": None,
                "detail": {"mode": "selectors", "fields": {}},
            }
        }
        entry = {}
        result = resolve_config(source, entry)
        assert result["pagination"] is None
