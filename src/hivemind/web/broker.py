"""Bounded, non-blocking process-local fan-out for browser clients."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from hivemind.observability import AgentHandoff
from hivemind.schemas import HiveEvent


@dataclass(frozen=True, slots=True)
class Subscription:
    client_id: str
    run_id: str
    queue: asyncio.Queue[dict[str, Any]]


class LiveBroker:
    """Fan out live records without ever awaiting browser network I/O."""

    def __init__(self, *, queue_size: int = 256) -> None:
        self.queue_size = queue_size
        self._subscriptions: dict[str, Subscription] = {}

    def subscribe(self, run_id: str) -> Subscription:
        subscription = Subscription(
            client_id=uuid4().hex,
            run_id=run_id,
            queue=asyncio.Queue(maxsize=self.queue_size),
        )
        self._subscriptions[subscription.client_id] = subscription
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        self._subscriptions.pop(subscription.client_id, None)

    async def event_sink(self, event: HiveEvent) -> None:
        self.publish(
            event.run_id,
            {"type": "event", "data": event.model_dump(mode="json")},
        )

    async def publish_handoff(self, handoff: AgentHandoff) -> None:
        self.publish(
            handoff.run_id,
            {"type": "handoff", "data": handoff.model_dump(mode="json")},
        )

    def publish(self, run_id: str, envelope: dict[str, Any]) -> None:
        for subscription in tuple(self._subscriptions.values()):
            if subscription.run_id != run_id:
                continue
            try:
                subscription.queue.put_nowait(envelope)
            except asyncio.QueueFull:
                self._request_resync(subscription.queue)

    @staticmethod
    def _request_resync(queue: asyncio.Queue[dict[str, Any]]) -> None:
        while not queue.empty():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        queue.put_nowait(
            {
                "type": "error",
                "data": {
                    "code": "resync_required",
                    "message": "Live updates overflowed; reconnect for a fresh snapshot.",
                },
            }
        )
