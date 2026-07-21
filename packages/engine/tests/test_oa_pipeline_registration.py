def test_oa_pipeline_registers():
    from engine.registry import PipelineRegistry

    PipelineRegistry._pipelines.clear()
    PipelineRegistry.discover()
    assert "oa.communicate_todos" in PipelineRegistry.all()


def test_oa_pipeline_metadata():
    from engine.registry import PipelineRegistry

    PipelineRegistry._pipelines.clear()
    PipelineRegistry.discover()
    cls = PipelineRegistry.get("oa.communicate_todos")
    assert cls is not None
    assert cls.metadata.display_name == "OA 沟通待办采集"
    assert "cron" in cls.metadata.trigger_modes
    assert "username" in cls.metadata.config_schema["required"]
    assert "password" in cls.metadata.config_schema["required"]
