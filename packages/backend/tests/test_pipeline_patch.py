# packages/backend/tests/test_pipeline_patch.py
import inspect

from backend.api.pipelines import update_pipeline, PipelineUpdate


def test_pipeline_update_schema():
    """PATCH 仅允许 status（spec 1 二十次修订：max_concurrent/timeout_seconds 退役）。"""
    schema = PipelineUpdate.model_json_schema()
    assert set(schema["properties"]) == {"status"}


def test_patch_endpoint_exists():
    sig = inspect.signature(update_pipeline)
    assert "name" in sig.parameters
    assert "body" in sig.parameters
