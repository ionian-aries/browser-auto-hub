from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from engine.context import ExecutionContext


@dataclass
class PipelineMetadata:
    name: str
    display_name: str
    description: str
    trigger_modes: list[Literal["cron", "interval", "api", "manual"]]
    config_schema: dict | None = None
    # 开发者自定义版本（建议 semver）。纯观测标记：sync 据此判断代码是否有更新，
    # 执行记录快照此值用于追溯「当时跑的是哪版」。不做 pin——新执行永远跑最新代码。
    version: str = "1.0.0"


@dataclass
class PipelineResult:
    success: bool
    artifacts: list[dict] = field(default_factory=list)
    summary: dict | None = None
    error: str | None = None


class BasePipeline(ABC):
    metadata: PipelineMetadata

    @abstractmethod
    async def execute(self, config: dict, ctx: "ExecutionContext") -> PipelineResult:
        ...
