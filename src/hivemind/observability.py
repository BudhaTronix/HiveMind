"""Public, bounded agent-to-agent handoff observability.

Handoffs describe validated workflow data at real orchestration boundaries. They never
contain prompts, provider request/response bodies, or hidden reasoning. The default observer
is intentionally inert so existing runtime consumers do not need to opt in.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from hivemind.events import redact
from hivemind.schemas import utc_now


class HandoffKind(StrEnum):
    ASSIGNMENT = "assignment"
    WORKER_REPORT = "worker_report"
    MANAGER_REPORT = "manager_report"
    VERIFICATION = "verification"
    QUALITY_REVIEW = "quality_review"
    FOLLOW_UP = "follow_up"
    MEMORY_CANDIDATE = "memory_candidate"
    FINAL_INPUT = "final_input"


class PublicationStatus(StrEnum):
    PUBLISHED = "published"


class AgentHandoff(BaseModel):
    """A safe public preview of one real transfer between runtime roles."""

    handoff_id: str
    run_id: str
    round_number: int = 0
    source_agent_id: str
    target_agent_id: str
    task_id: str | None = None
    kind: HandoffKind
    title: str = Field(max_length=160)
    summary: str = Field(max_length=600)
    payload_preview: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    publication_status: PublicationStatus = PublicationStatus.PUBLISHED


class RuntimeObserver(Protocol):
    """Optional runtime boundary that can publish safe handoff records."""

    async def publish_handoff(self, handoff: AgentHandoff) -> None: ...


class NullRuntimeObserver:
    """No-op observer used by the CLI and embedders that do not request handoffs."""

    async def publish_handoff(self, handoff: AgentHandoff) -> None:
        return None


def create_handoff(
    *,
    run_id: str,
    round_number: int,
    source_agent_id: str,
    target_agent_id: str,
    kind: HandoffKind,
    title: str,
    summary: str,
    payload_preview: dict[str, Any],
    task_id: str | None = None,
) -> AgentHandoff:
    """Create a redacted, recursively bounded, idempotently identified handoff."""

    identity = "\x1f".join(
        [
            run_id,
            str(round_number),
            source_agent_id,
            target_agent_id,
            kind.value,
            task_id or "",
        ]
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
    safe_payload = _bounded(redact(payload_preview))
    assert isinstance(safe_payload, dict)
    return AgentHandoff(
        handoff_id=f"handoff_{digest}",
        run_id=run_id,
        round_number=round_number,
        source_agent_id=source_agent_id,
        target_agent_id=target_agent_id,
        task_id=task_id,
        kind=kind,
        title=str(_bounded(redact(title), text_limit=160)),
        summary=str(_bounded(redact(summary), text_limit=600)),
        payload_preview=safe_payload,
    )


def _bounded(
    value: Any,
    *,
    depth: int = 0,
    text_limit: int = 800,
    collection_limit: int = 20,
) -> Any:
    """Recursively cap public previews so observability cannot become a data dump."""

    if depth >= 4:
        return "[preview truncated]"
    if isinstance(value, str):
        return value[:text_limit]
    if isinstance(value, dict):
        return {
            str(key)[:80]: _bounded(item, depth=depth + 1)
            for key, item in list(value.items())[:collection_limit]
        }
    if isinstance(value, (list, tuple, set)):
        return [
            _bounded(item, depth=depth + 1)
            for item in list(value)[:collection_limit]
        ]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:text_limit]
