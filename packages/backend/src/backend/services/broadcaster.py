import asyncio
from collections import defaultdict


class LogBroadcaster:
    """In-memory pub/sub for SSE log streaming."""

    def __init__(self):
        self._subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, execution_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[execution_id].add(queue)
        return queue

    def unsubscribe(self, execution_id: str, queue: asyncio.Queue) -> None:
        self._subscribers[execution_id].discard(queue)
        if not self._subscribers[execution_id]:
            del self._subscribers[execution_id]

    async def publish(self, execution_id: str, log_entry: dict) -> None:
        for queue in self._subscribers.get(execution_id, set()):
            await queue.put(log_entry)


# Singleton instance
log_broadcaster = LogBroadcaster()
