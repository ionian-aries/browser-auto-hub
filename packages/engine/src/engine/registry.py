import importlib
import logging
import pkgutil
import sys

from engine.base import BasePipeline, PipelineMetadata

logger = logging.getLogger(__name__)


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
                # 可选依赖缺失允许跳过，但必须留痕，否则 pipeline 静默消失难排查
                logger.warning(
                    "跳过 pipeline 模块 %s：导入失败（依赖缺失或模块错误）",
                    modname,
                    exc_info=True,
                )


def register_pipeline(**kwargs):
    """Decorator to register a pipeline class."""

    def decorator(cls: type[BasePipeline]) -> type[BasePipeline]:
        cls.metadata = PipelineMetadata(**kwargs)
        PipelineRegistry.register(cls)
        return cls

    return decorator
