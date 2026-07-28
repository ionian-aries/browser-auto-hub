import os

from engine.table_names import resolve_table


def test_resolve_table_returns_default_when_env_not_set(monkeypatch):
    monkeypatch.delenv("TABLE_foo", raising=False)
    assert resolve_table("foo", "foo_default") == "foo_default"


def test_resolve_table_returns_env_value_when_set(monkeypatch):
    monkeypatch.setenv("TABLE_foo", "custom_foo")
    assert resolve_table("foo", "foo_default") == "custom_foo"


def test_resolve_table_uses_table_prefix(monkeypatch):
    """TABLE_ 前缀是 key 的一部分，不带前缀的环境变量不应被读取。"""
    monkeypatch.setenv("foo", "wrong_value")
    monkeypatch.delenv("TABLE_foo", raising=False)
    assert resolve_table("foo", "fallback") == "fallback"


def test_resolve_table_inbox_documents_example(monkeypatch):
    """端到端示例：TABLE_inbox_documents=skill_custom_inbox_documents"""
    monkeypatch.setenv("TABLE_inbox_documents", "skill_custom_inbox_documents")
    assert resolve_table("inbox_documents", "inbox_documents") == "skill_custom_inbox_documents"


def test_resolve_table_empty_env_value_is_used(monkeypatch):
    """空字符串也是有效配置值（虽然不推荐），应被返回而非回退到 default。"""
    monkeypatch.setenv("TABLE_bar", "")
    assert resolve_table("bar", "bar_default") == ""
