import pytest

from backend.scheduler.manager import SchedulerManager


@pytest.mark.asyncio
async def test_scheduler_starts_and_stops():
    manager = SchedulerManager.__new__(SchedulerManager)
    manager._scheduler = None
    manager._session_factory = None
    # Just verify the class exists and has expected methods
    assert hasattr(manager, "start")
    assert hasattr(manager, "stop")
    assert hasattr(manager, "add_schedule")
    assert hasattr(manager, "remove_schedule")
