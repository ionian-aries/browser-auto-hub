# packages/backend/tests/test_pipeline_patch.py
import inspect

from backend.api.pipelines import update_pipeline, PipelineUpdate


def test_pipeline_update_schema():
    schema = PipelineUpdate.model_json_schema()
    assert "max_concurrent" in schema["properties"]
    assert "timeout_seconds" in schema["properties"]


def test_patch_endpoint_exists():
    sig = inspect.signature(update_pipeline)
    assert "name" in sig.parameters
    assert "body" in sig.parameters
