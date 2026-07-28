import uuid

from backend.models.pipeline import Pipeline
from backend.models.schedule import Schedule
from backend.models.execution import TaskExecution, TaskLog


def test_pipeline_id_is_uuid_string():
    p = Pipeline(
        id=str(uuid.uuid4()),
        name="test",
        display_name="Test",
        description="",
        trigger_modes=["manual"],
    )
    assert isinstance(p.id, str)
    assert len(p.id) == 36
    # UUID format: 8-4-4-4-12
    uuid.UUID(p.id)  # should not raise


def test_schedule_has_retry_fields():
    s = Schedule(
        id=str(uuid.uuid4()),
        pipeline_id=str(uuid.uuid4()),
        name="test",
        trigger_type="cron",
    )
    assert s.max_retries == 0
    assert s.retry_delay_seconds == 60


def test_execution_has_retry_count():
    e = TaskExecution(
        id=str(uuid.uuid4()),
        pipeline_id=str(uuid.uuid4()),
        trigger_type="manual",
    )
    assert e.retry_count == 0


def test_task_log_id_is_uuid():
    log = TaskLog(
        id=str(uuid.uuid4()),
        execution_id=str(uuid.uuid4()),
        step_name="test",
        message="hello",
    )
    uuid.UUID(log.id)
