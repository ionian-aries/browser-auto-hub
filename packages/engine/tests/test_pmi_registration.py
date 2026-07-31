def test_pmi_pipeline_registers():
    from engine.registry import PipelineRegistry

    PipelineRegistry._pipelines.clear()
    PipelineRegistry.discover()
    assert "port_maritime_info.harvest" in PipelineRegistry.all()


def test_pmi_pipeline_metadata():
    from engine.registry import PipelineRegistry

    PipelineRegistry._pipelines.clear()
    PipelineRegistry.discover()
    cls = PipelineRegistry.get("port_maritime_info.harvest")
    assert cls is not None
    assert cls.metadata.display_name == "港航信息采集"
    assert "cron" in cls.metadata.trigger_modes
    assert "manual" in cls.metadata.trigger_modes
    required = cls.metadata.config_schema["required"]
    assert "sources" in required
    assert "start_date" in required
    assert "end_date" in required


async def test_pmi_harvest_rejects_inverted_dates():
    """start_date > end_date 应在浏览器启动前 fail fast。"""
    from types import SimpleNamespace

    from engine.logger import StepLogger
    from engine.registry import PipelineRegistry

    PipelineRegistry._pipelines.clear()
    PipelineRegistry.discover()
    cls = PipelineRegistry.get("port_maritime_info.harvest")
    ctx = SimpleNamespace(logger=StepLogger("t"))
    result = await cls().execute(
        {
            "sources": ["交通运输部"],
            "start_date": "2026-07-23",
            "end_date": "2026-07-01",
        },
        ctx,
    )
    assert not result.success
    assert "start_date" in result.error
