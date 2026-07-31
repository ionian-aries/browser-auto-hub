"""相对日期表达式解析（resolve_date_expr）与入参边界校验（validate_config）单测。"""
from datetime import datetime, timedelta

import pytest

from engine.pipelines.port_maritime_info.collect import _validate_dates, resolve_date_expr
from engine.pipelines.port_maritime_info.harvest import PortMaritimeInfoHarvestPipeline


def _today() -> str:
    return datetime.now().date().isoformat()


def _days_ago(n: int) -> str:
    return (datetime.now().date() - timedelta(days=n)).isoformat()


class TestResolveDateExpr:
    def test_today(self):
        assert resolve_date_expr("today") == _today()

    def test_today_minus_zero(self):
        assert resolve_date_expr("today-0") == _today()

    def test_today_minus_n(self):
        assert resolve_date_expr("today-1") == _days_ago(1)
        assert resolve_date_expr("today-6") == _days_ago(6)
        assert resolve_date_expr("today-29") == _days_ago(29)

    def test_explicit_date_passthrough(self):
        assert resolve_date_expr("2026-07-01") == "2026-07-01"

    def test_whitespace_tolerated(self):
        assert resolve_date_expr(" today-6 ") == _days_ago(6)

    @pytest.mark.parametrize("bad", ["toddy", "today-", "today-x", "yesterday", "last_week", ""])
    def test_garbage_passthrough_for_validator(self, bad):
        """无法识别的值原样透传，由 _validate_dates 统一报错。"""
        assert resolve_date_expr(bad) == bad

    def test_non_string_passthrough(self):
        """非字符串（API 类型混淆）原样透传，不得抛 AttributeError。"""
        assert resolve_date_expr(20260730) == 20260730
        assert resolve_date_expr(None) is None


class TestValidateDatesTypeSafety:
    """类型混淆必须归一为 ValueError，不得泄漏 TypeError/AttributeError。"""

    @pytest.mark.parametrize("bad", [20260730, None, ["2026-07-30"], {"d": 1}])
    def test_non_string_raises_value_error(self, bad):
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            _validate_dates(bad, "today")

    def test_reversed_range(self):
        with pytest.raises(ValueError, match="start_date"):
            _validate_dates("2026-07-30", "2026-07-01")


class TestValidateConfig:
    """触发边界预校验钩子（API/定时任务创建时调用）。"""

    def _cfg(self, **over):
        base = {"sources": ["交通运输部"], "start_date": "today-6", "end_date": "today"}
        base.update(over)
        return base

    def test_valid_relative(self):
        assert PortMaritimeInfoHarvestPipeline.validate_config(self._cfg()) is None

    def test_valid_fixed(self):
        assert PortMaritimeInfoHarvestPipeline.validate_config(
            self._cfg(start_date="2026-07-01", end_date="2026-07-30")
        ) is None

    def test_valid_mixed(self):
        assert PortMaritimeInfoHarvestPipeline.validate_config(
            self._cfg(start_date="today-29", end_date="2026-07-30")
        ) is None

    def test_missing_sources(self):
        assert "sources" in PortMaritimeInfoHarvestPipeline.validate_config(
            self._cfg(sources=[])
        )

    def test_missing_dates(self):
        err = PortMaritimeInfoHarvestPipeline.validate_config(
            self._cfg(start_date="", end_date="")
        )
        assert "start_date" in err

    def test_garbage_expression(self):
        err = PortMaritimeInfoHarvestPipeline.validate_config(
            self._cfg(start_date="toddy", end_date="today-x")
        )
        assert "YYYY-MM-DD" in err

    def test_reversed_relative_range(self):
        """today ~ today-6（反向）解析后必须被 start<=end 抓住。"""
        err = PortMaritimeInfoHarvestPipeline.validate_config(
            self._cfg(start_date="today", end_date="today-6")
        )
        assert "start_date" in err

    def test_non_string_date(self):
        err = PortMaritimeInfoHarvestPipeline.validate_config(
            self._cfg(start_date=20260730)
        )
        assert "YYYY-MM-DD" in err
