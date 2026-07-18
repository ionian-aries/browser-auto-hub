from engine.base import BasePipeline, PipelineResult
from engine.logger import StepLogger
from engine.registry import register_pipeline


@register_pipeline(
    name="example",
    display_name="Example Pipeline",
    description="A minimal example pipeline for testing",
    trigger_modes=["manual", "api"],
    config_schema={
        "type": "object",
        "properties": {
            "message": {"type": "string", "default": "hello"},
        },
    },
)
class ExamplePipeline(BasePipeline):
    async def execute(self, config: dict, logger: StepLogger) -> PipelineResult:
        msg = config.get("message", "hello")
        await logger.step("greet", f"Example says: {msg}")
        return PipelineResult(success=True, summary={"message": msg})
