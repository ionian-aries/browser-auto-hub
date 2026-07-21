from engine.base import BasePipeline, PipelineResult
from engine.context import ExecutionContext
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
    async def execute(self, config: dict, ctx: ExecutionContext) -> PipelineResult:
        msg = config.get("message", "hello")
        await ctx.logger.step("greet", f"Example says: {msg}")
        return PipelineResult(success=True, summary={"message": msg})
