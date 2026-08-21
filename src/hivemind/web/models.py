"""Validated public request and response contracts for the browser UI."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hivemind.observability import AgentHandoff
from hivemind.schemas import (
    AgentProfile,
    AgentStatus,
    Evidence,
    FinalReport,
    HiveEvent,
    RunMetrics,
    RunRecord,
    TaskRecord,
)


class NewRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=12_000)
    project_id: str = Field(default="web-project", min_length=1, max_length=100)
    provider: Literal["fake", "ollama", "openai"] = "fake"
    model: str | None = Field(default=None, min_length=1, max_length=200)
    enable_web: bool = False
    max_managers: int = Field(default=3, ge=1, le=10)
    max_workers_per_manager: int = Field(default=3, ge=1, le=10)
    max_research_rounds: int = Field(default=2, ge=1, le=5)
    max_concurrent_llm_calls: int = Field(default=3, ge=1, le=20)

    @field_validator("prompt", "project_id", "model")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class ScheduledRun(BaseModel):
    run_id: str
    status: Literal["scheduled"] = "scheduled"


class PublicSettings(BaseModel):
    default_provider: str
    default_model: str
    enable_web: bool
    limits: dict[str, int]
    providers: list[str] = Field(default_factory=lambda: ["fake", "ollama", "openai"])


class EvidenceSummary(BaseModel):
    evidence_id: str
    agent_id: str
    task_id: str
    title: str
    url: str | None
    source_type: str
    retrieved_at: datetime
    verification_status: str

    @classmethod
    def from_evidence(cls, item: Evidence) -> EvidenceSummary:
        return cls(**item.model_dump(include=set(cls.model_fields)))


class AgentNodeState(BaseModel):
    profile: AgentProfile
    status: AgentStatus
    active_task_title: str | None = None
    claim_count: int = 0
    evidence_count: int = 0
    retry_count: int = 0
    last_activity_at: datetime


class RunSnapshot(BaseModel):
    run: RunRecord
    agents: list[AgentNodeState]
    tasks: list[TaskRecord]
    events: list[HiveEvent]
    handoffs: list[AgentHandoff]
    evidence: list[EvidenceSummary]
    tool_activity: list[dict[str, Any]]
    metrics: RunMetrics
    final_report: FinalReport | None = None
    error: str | None = None


class AgentDetails(BaseModel):
    agent: AgentProfile
    current_status: AgentStatus
    tasks: list[TaskRecord]
    incoming_handoffs: list[AgentHandoff]
    outgoing_handoffs: list[AgentHandoff]
    status_history: list[HiveEvent]
    tool_calls: list[dict[str, Any]]
    evidence: list[EvidenceSummary]
    reports: list[dict[str, Any]]
