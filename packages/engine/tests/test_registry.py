import pytest

from engine.base import BasePipeline, PipelineMetadata, PipelineResult
from engine.logger import StepLogger
from engine.registry import PipelineRegistry, register_pipeline


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear registry between tests."""
    PipelineRegistry._pipelines.clear()
    yield
    PipelineRegistry._pipelines.clear()


def test_register_pipeline_decorator():
    @register_pipeline(
        name="test_pipeline",
        display_name="Test Pipeline",
        description="A test pipeline",
        trigger_modes=["manual", "api"],
    )
    class TestPipeline(BasePipeline):
        async def execute(self, config: dict, logger: StepLogger) -> PipelineResult:
            return PipelineResult(success=True)

    assert "test_pipeline" in PipelineRegistry._pipelines
    cls = PipelineRegistry.get("test_pipeline")
    assert cls is TestPipeline
    assert cls.metadata.name == "test_pipeline"
    assert cls.metadata.display_name == "Test Pipeline"
    assert cls.metadata.trigger_modes == ["manual", "api"]


def test_registry_all():
    @register_pipeline(
        name="p1",
        display_name="P1",
        description="",
        trigger_modes=["manual"],
    )
    class P1(BasePipeline):
        async def execute(self, config, logger):
            return PipelineResult(success=True)

    @register_pipeline(
        name="p2",
        display_name="P2",
        description="",
        trigger_modes=["cron"],
    )
    class P2(BasePipeline):
        async def execute(self, config, logger):
            return PipelineResult(success=True)

    all_pipelines = PipelineRegistry.all()
    assert len(all_pipelines) == 2
    assert "p1" in all_pipelines
    assert "p2" in all_pipelines


def test_registry_get_unknown_returns_none():
    assert PipelineRegistry.get("nonexistent") is None


def test_discover_loads_pipelines():
    PipelineRegistry.discover()
    assert "example" in PipelineRegistry._pipelines
    example_cls = PipelineRegistry.get("example")
    assert example_cls.metadata.display_name == "Example Pipeline"


def test_discover_finds_pipelines_in_subdirectories():
    """Registry should find pipelines in nested packages like oa/."""
    PipelineRegistry._pipelines.clear()
    PipelineRegistry.discover()
    # After Task 7 implements the OA pipeline, this will find oa.communicate_todos
    # For now, just verify discover() doesn't crash on nested packages
    assert "example" in PipelineRegistry.all()


def test_discover_logs_import_errors(caplog, monkeypatch):
    """导入失败的模块必须留痕（warning + traceback），不能静默吞掉。"""
    import logging

    import engine.registry as reg

    PipelineRegistry._pipelines["sentinel"] = object  # 避免触发 reload 路径
    monkeypatch.setattr(
        reg.pkgutil,
        "walk_packages",
        lambda *a, **k: [(None, "engine.pipelines.broken_mod", False)],
    )

    def _raise_import(name):
        raise ImportError("No module named 'foo'")

    monkeypatch.setattr(reg.importlib, "import_module", _raise_import)

    with caplog.at_level(logging.WARNING, logger="engine.registry"):
        PipelineRegistry.discover()

    assert "engine.pipelines.broken_mod" in caplog.text
