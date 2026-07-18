import pytest

from backend.services.broadcaster import LogBroadcaster


@pytest.mark.asyncio
async def test_broadcaster_subscribe_publish():
    """Basic integration check for broadcaster used by runner."""
    b = LogBroadcaster()
    q = b.subscribe(1)
    await b.publish(1, {"type": "complete", "status": "success"})
    entry = await q.get()
    assert entry["type"] == "complete"
    b.unsubscribe(1, q)
