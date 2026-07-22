from datetime import datetime, timezone
from backend.models.base import UTCDateTime


def test_result_value_gets_utc_tzinfo():
    t = UTCDateTime()
    naive = datetime(2026, 7, 22, 3, 21, 20)
    result = t.process_result_value(naive, None)
    assert result.tzinfo == timezone.utc


def test_bind_param_strips_tzinfo():
    t = UTCDateTime()
    aware = datetime(2026, 7, 22, 3, 21, 20, tzinfo=timezone.utc)
    result = t.process_bind_param(aware, None)
    assert result.tzinfo is None
    assert result.hour == 3  # wall clock preserved


def test_none_passthrough():
    t = UTCDateTime()
    assert t.process_result_value(None, None) is None
    assert t.process_bind_param(None, None) is None
