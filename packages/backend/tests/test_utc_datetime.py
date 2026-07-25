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


def test_server_defaults_use_utc_clock():
    """DB 侧默认值必须是 UTC 时钟（func.now() 是服务器本地时区，与 UTCDateTime 读回语义冲突）。"""
    from backend.models.execution import TaskArtifact, TaskExecution, TaskLog
    from backend.models.pipeline import Pipeline
    from backend.models.schedule import Schedule
    from backend.models.system_setting import SystemSetting

    cols = [
        TaskExecution.__table__.c.created_at,
        TaskLog.__table__.c.timestamp,
        TaskArtifact.__table__.c.created_at,
        Pipeline.__table__.c.created_at,
        Pipeline.__table__.c.updated_at,
        Schedule.__table__.c.created_at,
        Schedule.__table__.c.updated_at,
        SystemSetting.__table__.c.updated_at,
    ]
    for col in cols:
        assert col.server_default is not None, f"{col} 缺 server_default"
        text = str(col.server_default.arg).lower()
        assert "utc_timestamp" in text, f"{col} 仍使用本地时区默认值: {text}"


def test_today_start_is_local_midnight_in_utc():
    """业务日按本地零点切割（spec 1 §14），转 UTC-naive 后与 UTC 存储比对。"""
    from backend.api.executions import _local_today_start_utc_naive

    start = _local_today_start_utc_naive()
    assert start.tzinfo is None  # 与存储侧 naive UTC 可比
    # 本地零点 ≡ UTC 当天的前一日 16:00（UTC+8）；本地当天任意时刻都应 >= start
    now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    assert start <= now_utc_naive
    # 切割点不得早于"本地昨天"：与 now 的差必然小于 24h（UTC 日切割则可能差近 32h 的语义错误）
    assert (now_utc_naive - start).total_seconds() < 24 * 3600
