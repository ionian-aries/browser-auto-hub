import importlib
import pkgutil
from typing import TYPE_CHECKING

from engine.base import BasePipeline, PipelineMetadata

if TYPE_CHECKING:
    pass


class PipelineRegistry:
    _pipelines: dict[str, type[BasePipeline]] = {}

    @classmethod
    def register(cls, pipeline_cls: type[BasePipeline]) -> None:
        name = pipeline_cls.metadata.name
        cls._pipelines[name] = pipeline_cls

    @classmethod
    def get(cls, name: str) -> type[BasePipeline] | None:
        return cls._pipelines.get(name)

    @classmethod
    def all(cls) -> dict[str, type[BasePipeline]]:
        return dict(cls._pipelines)

    @classmethod
    def discover(cls) -> None:
        """Import all modules in engine.pipelines to trigger registration."""
        import engine.pipelines as pipelines_pkg

        for importer, modname, ispkg in pkgutil.iter_modules(pipelines_pkg.__path__):
            importlib.import_module(f"engine.pipelines.{modname}")


def register_pipeline(**kwargs):
    """Decorator to register a pipeline class."""

    def decorator(cls: type[BasePipeline]) -> type[BasePipeline]:
        cls.metadata = PipelineMetadata(**kwargs)
        PipelineRegistry.register(cls)
        return cls

    return decorator
