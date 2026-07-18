import asyncio

import pytest

from backend.services.broadcaster import LogBroadcaster


@pytest.fixture
def broadcaster():
    return LogBroadcaster()


@pytest.mark.asyncio
async def test_subscribe_and_publish(broadcaster):
    queue = broadcaster.subscribe(1)
    await broadcaster.publish(1, {"step": "test", "message": "hello"})
    entry = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert entry["step"] == "test"
    assert entry["message"] == "hello"
    broadcaster.unsubscribe(1, queue)


@pytest.mark.asyncio
async def test_publish_no_subscribers(broadcaster):
    # Should not raise
    await broadcaster.publish(99, {"step": "x", "message": "y"})


@pytest.mark.asyncio
async def test_multiple_subscribers(broadcaster):
    q1 = broadcaster.subscribe(1)
    q2 = broadcaster.subscribe(1)
    await broadcaster.publish(1, {"msg": "hi"})
    e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    e2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert e1 == e2 == {"msg": "hi"}
    broadcaster.unsubscribe(1, q1)
    broadcaster.unsubscribe(1, q2)
