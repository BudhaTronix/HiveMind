"""Publish visible runtime events without coupling work to a terminal renderer.

The event bus is intentionally tiny. The terminal, JSONL writer, and SQLite repository can
all subscribe to the same events, which makes live output and later reconstruction agree.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from hivemind.schemas import EventType, HiveEvent

EventSink = Callable[[HiveEvent], Awaitable[None]]

_SECRET_KEYS = re.compile(r"(api[_-]?key|authorization|cookie|token|secret)", re.IGNORECASE)


def redact(value: Any, *, key: str = "") -> Any:
    """Remove common secret-bearing fields before data enters events or logs."""

    if key and _SECRET_KEYS.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): redact(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class EventBus:
    """Fan events out to subscribers while retaining an in-memory run history."""

    def __init__(self) -> None:
        self.events: list[HiveEvent] = []
        self._sinks: list[EventSink] = []

    def subscribe(self, sink: EventSink) -> None:
        """Register an asynchronous event consumer."""

        self._sinks.append(sink)

    async def emit(
        self,
        event_type: EventType,
        run_id: str,
        message: str,
        *,
        round_number: int = 0,
        task_id: str | None = None,
        agent_id: str | None = None,
        parent_agent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> HiveEvent:
        """Create, redact, retain, and publish one event."""

        event = HiveEvent(
            event_type=event_type,
            run_id=run_id,
            message=message,
            round_number=round_number,
            task_id=task_id,
            agent_id=agent_id,
            parent_agent_id=parent_agent_id,
            metadata=redact(metadata or {}),
        )
        self.events.append(event)
        for sink in self._sinks:
            await sink(event)
        return event
