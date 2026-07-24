"""Thread-safe estimate events shared by FastAPI and the desktop HTTP server."""

from __future__ import annotations

import json
from dataclasses import dataclass
from queue import SimpleQueue
from threading import Lock
from typing import TYPE_CHECKING, Final, Literal, final

from anyio.to_thread import run_sync

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

EstimateEventName = Literal["estimate-saved", "estimate-deleted"]


@dataclass(frozen=True, slots=True)
class EstimateEvent:
    """One persisted estimate change sent to connected browsers."""

    name: EstimateEventName
    estimate_id: str

    def as_sse(self) -> str:
        """Encode the event using the browser EventSource wire format."""
        data = json.dumps({"id": self.estimate_id}, separators=(",", ":"))
        return f"event: {self.name}\ndata: {data}\n\n"


@final
class EstimateEventBroker:
    """Own the mutable subscriber set used by concurrent HTTP request threads."""

    def __init__(self) -> None:
        """Create an empty thread-safe subscriber registry."""
        self._lock = Lock()
        self._subscribers: set[SimpleQueue[EstimateEvent]] = set()

    def subscribe(self) -> SimpleQueue[EstimateEvent]:
        """Register and return one subscriber queue."""
        subscriber: SimpleQueue[EstimateEvent] = SimpleQueue()
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: SimpleQueue[EstimateEvent]) -> None:
        """Remove one subscriber queue."""
        with self._lock:
            self._subscribers.discard(subscriber)

    def publish(self, event: EstimateEvent) -> None:
        """Deliver an event to every currently connected subscriber."""
        with self._lock:
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            subscriber.put(event)


ESTIMATE_EVENTS: Final = EstimateEventBroker()


async def estimate_event_stream() -> AsyncIterator[str]:
    """Yield estimate changes until the SSE client disconnects."""
    subscriber = ESTIMATE_EVENTS.subscribe()
    try:
        yield "event: ready\ndata: {}\n\n"
        while True:
            event = await run_sync(
                subscriber.get,
                abandon_on_cancel=True,
            )
            yield event.as_sse()
    finally:
        ESTIMATE_EVENTS.unsubscribe(subscriber)
