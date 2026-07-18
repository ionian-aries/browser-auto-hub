from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from engine.logger import StepLogger


@dataclass
class PipelineMetadata:
    name: str
    display_name: str
    description: str
    trigger_modes: list[Literal["cron", "interval", "api", "manual"]]
    config_schema: dict | None = None


@dataclass
class PipelineResult:
    success: bool
    artifacts: list[dict] = field(default_factory=list)
    summary: dict | None = None
    error: str | None = None


class BasePipeline(ABC):
    metadata: PipelineMetadata

    @abstractmethod
    async def execute(self, config: dict, logger: "StepLogger") -> PipelineResult:
        ...
