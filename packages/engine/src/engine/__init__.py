"""Browser automation engine — pipeline registry, executors, and base classes."""
from engine.base import BasePipeline, PipelineMetadata, PipelineResult
from engine.context import ExecutionContext
from engine.logger import StepLogger
from engine.registry import PipelineRegistry, register_pipeline

__all__ = [
    "BasePipeline",
    "ExecutionContext",
    "PipelineMetadata",
    "PipelineResult",
    "PipelineRegistry",
    "StepLogger",
    "register_pipeline",
]
