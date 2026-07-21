from engine.context import ExecutionContext
from engine.logger import StepLogger


def test_execution_context_fields():
    logger = StepLogger("test-id")
    ctx = ExecutionContext(
        logger=logger,
        db=None,
        minio=None,
        settings=None,
        execution_id="test-id",
    )
    assert ctx.execution_id == "test-id"
    assert ctx.logger is logger
    assert ctx.db is None
    assert ctx.minio is None
    assert ctx.settings is None
