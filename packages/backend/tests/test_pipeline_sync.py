"""pipeline_sync 内容对比同步测试（spec 1 §4.5，2026-07-24 二十七次修订）"""

import pytest

from backend.models.pipeline import Pipeline
from backend.services.pipeline_sync import sync_pipelines_to_db
from engine.base import BasePipeline, PipelineMetadata, PipelineResult
from engine.registry import PipelineRegistry


def _make_cls(name, config_schema=None, version="1.0.0", display_name="T"):
    class P(BasePipeline):
        metadata = PipelineMetadata(
            name=name,
            display_name=display_name,
            description="d",
            trigger_modes=["api"],
            config_schema=config_schema,
            version=version,
        )

        async def execute(self, config, ctx) -> PipelineResult:
            return PipelineResult(success=True)

    return P


class _FakeResult:
    def __init__(self, existing):
        self._existing = existing

    def scalar_one_or_none(self):
        return self._existing

    def scalars(self):
        return self

    def all(self):
        return [self._existing] if self._existing is not None else []


class _FakeSession:
    def __init__(self, existing):
        self._existing = existing
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def execute(self, stmt):
        return _FakeResult(self._existing)

    async def commit(self):
        pass


@pytest.fixture
def use_registry(monkeypatch):
    def _set(cls):
        monkeypatch.setattr(PipelineRegistry, "discover", lambda: None)
        monkeypatch.setattr(
            PipelineRegistry, "all", lambda: {cls.metadata.name: cls}
        )

    return _set


@pytest.mark.asyncio
async def test_sync_updates_on_content_change_without_version_bump(use_registry):
    """version 未 bump 但 config_schema 变了 → 必须同步
    （二十七次修订动因：max_verify_rounds 忘 bump 导致 DB 漂移事件回归）。"""
    cls = _make_cls("test.pipe", config_schema={"properties": {"new_key": {}}})
    use_registry(cls)
    existing = Pipeline(
        name="test.pipe", display_name="T", description="d",
        trigger_modes=["api"], config_schema={"properties": {}},
        version="1.0.0", status="active",
    )
    await sync_pipelines_to_db(_FakeSession(existing))
    assert existing.config_schema == {"properties": {"new_key": {}}}
    assert existing.version == "1.0.0"


@pytest.mark.asyncio
async def test_sync_skips_when_definitions_identical(use_registry, caplog):
    """定义字段全部一致 → 跳过（不记变更日志）。"""
    cls = _make_cls("test.pipe", config_schema={"properties": {"a": {}}})
    use_registry(cls)
    existing = Pipeline(
        name="test.pipe", display_name="T", description="d",
        trigger_modes=["api"], config_schema={"properties": {"a": {}}},
        version="1.0.0", status="active",
    )
    with caplog.at_level("INFO", logger="backend.services.pipeline_sync"):
        await sync_pipelines_to_db(_FakeSession(existing))
    assert "定义字段变更" not in caplog.text


@pytest.mark.asyncio
async def test_sync_inserts_new_pipeline(use_registry):
    cls = _make_cls("test.new", version="2.0.0")
    use_registry(cls)
    session = _FakeSession(existing=None)
    await sync_pipelines_to_db(session)
    assert len(session.added) == 1
    assert session.added[0].version == "2.0.0"
    assert session.added[0].status == "active"


@pytest.mark.asyncio
async def test_sync_restores_archived_on_code_return(use_registry):
    cls = _make_cls("test.pipe")
    use_registry(cls)
    existing = Pipeline(
        name="test.pipe", display_name="T", description="d",
        trigger_modes=["api"], config_schema=None,
        version="1.0.0", status="archived",
    )
    await sync_pipelines_to_db(_FakeSession(existing))
    assert existing.status == "active"
