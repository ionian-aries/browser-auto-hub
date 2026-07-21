import importlib
import pkgutil
import sys
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
        """Recursively import all modules in engine.pipelines to trigger registration."""
        import engine.pipelines as pipelines_pkg

        # If registry was cleared (test scenario), we need to reload cached modules
        need_reload = not cls._pipelines

        for importer, modname, ispkg in pkgutil.walk_packages(
            pipelines_pkg.__path__, prefix="engine.pipelines."
        ):
            # Skip __init__ and shared/ modules (no pipelines there)
            if modname.endswith("__init__") or ".shared." in modname:
                continue
            try:
                if modname in sys.modules:
                    if need_reload:
                        importlib.reload(sys.modules[modname])
                else:
                    importlib.import_module(modname)
            except ImportError:
                pass  # Skip modules with missing optional dependencies


def register_pipeline(**kwargs):
    """Decorator to register a pipeline class."""

    def decorator(cls: type[BasePipeline]) -> type[BasePipeline]:
        cls.metadata = PipelineMetadata(**kwargs)
        PipelineRegistry.register(cls)
        return cls

    return decorator
