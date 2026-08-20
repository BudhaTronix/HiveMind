"""Define the validated contracts exchanged across HiveMind.

Models are deliberately collected in one module for learners: an agent's output becomes
ordinary validated data before Python acts on it. This is the boundary that keeps an LLM's
proposal separate from the runtime's permissions and limits.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    """Create a readable, collision-resistant identifier."""

    return f"{prefix}_{uuid4().hex[:16]}"


class RunStage(StrEnum):
    CREATED = "created"
    LOADING_MEMORY = "loading_memory"
    CEO_PLANNING = "ceo_planning"
    VALIDATING_PLAN = "validating_plan"
    SPAWNING_MANAGERS = "spawning_managers"
    MANAGERS_PLANNING = "managers_planning"
    SPAWNING_WORKERS = "spawning_workers"
    WORKERS_RESEARCHING = "workers_researching"
    MANAGERS_SYNTHESIZING = "managers_synthesizing"
    VERIFYING = "verifying"
    QUALITY_REVIEW = "quality_review"
    REPLANNING = "replanning"
    CURATING_MEMORY = "curating_memory"
    FINAL_SYNTHESIS = "final_synthesis"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentKind(StrEnum):
    CEO = "ceo"
    MANAGER = "manager"
    WORKER = "worker"
    VERIFIER = "verifier"
    QA = "qa"
    MEMORY_CURATOR = "memory_curator"


class AgentStatus(StrEnum):
    CREATED = "created"
    QUEUED = "queued"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_FOR_TOOL = "waiting_for_tool"
    WAITING_FOR_CHILDREN = "waiting_for_children"
    SYNTHESIZING = "synthesizing"
    VERIFYING = "verifying"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_TOOL = "waiting_for_tool"
    WAITING_FOR_CHILDREN = "waiting_for_children"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventType(StrEnum):
    RUN_CREATED = "run_created"
    STAGE_CHANGED = "stage_changed"
    PLAN_REQUESTED = "plan_requested"
    PLAN_RECEIVED = "plan_received"
    PLAN_VALIDATED = "plan_validated"
    PLAN_REDUCED_BY_GOVERNOR = "plan_reduced_by_governor"
    AGENT_SPAWNED = "agent_spawned"
    AGENT_STARTED = "agent_started"
    AGENT_STATUS_CHANGED = "agent_status_changed"
    MEMORY_SEARCH_STARTED = "memory_search_started"
    MEMORY_SEARCH_COMPLETED = "memory_search_completed"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    TASK_RETRYING = "task_retrying"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_COMPLETED = "verification_completed"
    QA_STARTED = "qa_started"
    QA_COMPLETED = "qa_completed"
    REPLAN_REQUESTED = "replan_requested"
    REPLAN_APPROVED = "replan_approved"
    MEMORY_SAVED = "memory_saved"
    MEMORY_REJECTED = "memory_rejected"
    FINAL_REPORT_STARTED = "final_report_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    VALIDATION_FAILED = "validation_failed"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    PARTIALLY_VERIFIED = "partially_verified"
    UNVERIFIED = "unverified"
    CONTRADICTED = "contradicted"


class MemoryScope(StrEnum):
    COMPANY = "company"
    PROJECT = "project"
    AGENT = "agent"
    RUN = "run"
    USER = "user"


class MemoryType(StrEnum):
    FACT = "fact"
    DECISION = "decision"
    PREFERENCE = "preference"
    LESSON = "lesson"
    RISK = "risk"
    SUMMARY = "summary"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    UNCERTAIN = "uncertain"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class CurationDecision(StrEnum):
    SAVE = "save"
    REJECT = "reject"
    TEMPORARY_ONLY = "temporary_only"
    SUPERSEDES_EXISTING = "supersedes_existing"
    UNCERTAIN = "uncertain"


class DepartmentSpec(BaseModel):
    """A department proposed by the CEO; Python still decides whether it is allowed."""

    role_key: str = Field(min_length=2, pattern=r"^[a-z0-9-]+$")
    name: str
    manager_name: str
    objective: str
    rationale_summary: str
    suggested_tools: list[str] = Field(default_factory=list)
    priority: int = Field(default=50, ge=0, le=100)


class WorkerSpec(BaseModel):
    """A narrow research role proposed by a manager."""

    role_key: str = Field(min_length=2, pattern=r"^[a-z0-9-]+$")
    name: str
    role: str
    objective: str
    research_questions: list[str] = Field(default_factory=list, max_length=5)
    search_queries: list[str] = Field(default_factory=list, max_length=3)
    rationale_summary: str
    priority: int = Field(default=50, ge=0, le=100)


class CompanyPlan(BaseModel):
    objective: str
    departments: list[DepartmentSpec]
    rationale_summary: str


class WorkerPlan(BaseModel):
    department_role_key: str
    workers: list[WorkerSpec]
    rationale_summary: str


class FollowUpPlan(BaseModel):
    needed: bool = False
    departments: list[DepartmentSpec] = Field(default_factory=list)
    rationale_summary: str


class GovernorLimits(BaseModel):
    max_managers: int = 3
    max_workers_per_manager: int = 3
    max_total_agents: int = 15
    max_concurrent_llm_calls: int = 3
    max_concurrent_web_requests: int = 4
    max_research_rounds: int = 2
    max_search_queries_per_worker: int = 2
    max_retries_per_task: int = 2
    max_runtime_seconds: int = 900


class AgentProfile(BaseModel):
    agent_id: str = Field(default_factory=lambda: new_id("agent"))
    project_id: str
    role_key: str
    name: str
    kind: AgentKind
    role_description: str
    parent_agent_id: str | None = None
    status: AgentStatus = AgentStatus.CREATED
    created_at: datetime = Field(default_factory=utc_now)
    last_used_at: datetime = Field(default_factory=utc_now)
    tasks_completed: int = 0
    tasks_failed: int = 0
    average_verification_score: float | None = None


class TaskRecord(BaseModel):
    task_id: str = Field(default_factory=lambda: new_id("task"))
    run_id: str
    parent_task_id: str | None = None
    agent_id: str
    title: str
    objective: str
    status: TaskStatus = TaskStatus.PENDING
    priority: int = 50
    attempt: int = 0
    max_attempts: int = 2
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


class RunRecord(BaseModel):
    run_id: str = Field(default_factory=lambda: new_id("run"))
    project_id: str
    prompt: str
    provider: str
    model: str
    stage: RunStage = RunStage.CREATED
    round_number: int = 0
    max_rounds: int = 2
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    error_message: str | None = None


class Evidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: new_id("evidence"))
    run_id: str
    task_id: str
    agent_id: str
    url: str | None = None
    title: str
    source_type: str
    snippet: str = ""
    content_excerpt: str = ""
    search_query: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime = Field(default_factory=utc_now)
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED


class SearchResult(BaseModel):
    """A normalized result from a search provider, not yet a fetched webpage."""

    title: str
    url: str
    snippet: str = ""


class FetchedPage(BaseModel):
    """Bounded text extracted from one safely fetched public web page."""

    url: str
    title: str
    content_type: str
    excerpt: str


class ToolMetadata(BaseModel):
    """Python-owned permissions and side-effect metadata for one registered tool."""

    name: str
    description: str
    allowed_agent_kinds: set[AgentKind]
    side_effect: bool = False
    requires_approval: bool = False


class Claim(BaseModel):
    claim_id: str = Field(default_factory=lambda: new_id("claim"))
    text: str
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("evidence_ids")
    @classmethod
    def evidence_ids_are_unique(cls, values: list[str]) -> list[str]:
        """Avoid inflating support by repeating the same evidence identifier."""

        return list(dict.fromkeys(values))


class MemoryCandidate(BaseModel):
    text: str
    memory_type: MemoryType
    confidence: float = Field(ge=0, le=1)
    source_evidence_ids: list[str] = Field(default_factory=list)


class WorkerReport(BaseModel):
    summary: str
    claims: list[Claim] = Field(default_factory=list)
    important_findings: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    memory_candidates: list[MemoryCandidate] = Field(default_factory=list)


class ManagerReport(BaseModel):
    department_name: str
    summary: str
    merged_claims: list[Claim] = Field(default_factory=list)
    agreements: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    research_gaps: list[str] = Field(default_factory=list)
    recommended_follow_up: list[str] = Field(default_factory=list)


class VerificationFinding(BaseModel):
    claim_id: str
    status: VerificationStatus
    explanation: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    conflicting_evidence_ids: list[str] = Field(default_factory=list)


class VerificationReport(BaseModel):
    findings: list[VerificationFinding] = Field(default_factory=list)
    summary: str


class QAReport(BaseModel):
    quality_score: float = Field(ge=0, le=1)
    coverage_score: float = Field(ge=0, le=1)
    evidence_score: float = Field(ge=0, le=1)
    identified_gaps: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    can_finalize: bool


class SourceReference(BaseModel):
    evidence_id: str
    title: str
    url: str | None = None
    retrieved_at: datetime
    claims_supported: list[str] = Field(default_factory=list)
    verification_status: VerificationStatus


class FinalReport(BaseModel):
    title: str
    executive_summary: str
    answer: str
    key_findings: list[str]
    risks: list[str]
    uncertainties: list[str]
    recommendations: list[str]
    research_limitations: list[str] = Field(default_factory=list)
    sources: list[SourceReference] = Field(default_factory=list)


class MemoryRecord(BaseModel):
    memory_id: str = Field(default_factory=lambda: new_id("memory"))
    scope: MemoryScope
    scope_id: str
    text: str
    memory_type: MemoryType
    source_agent_id: str | None = None
    source_run_id: str | None = None
    source_evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    status: MemoryStatus = MemoryStatus.ACTIVE


class CurationResult(BaseModel):
    candidate: MemoryCandidate
    decision: CurationDecision
    rationale_summary: str
    supersedes_memory_id: str | None = None


class HiveEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("event"))
    event_type: EventType
    timestamp: datetime = Field(default_factory=utc_now)
    run_id: str
    round_number: int = 0
    task_id: str | None = None
    agent_id: str | None = None
    parent_agent_id: str | None = None
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunMetrics(BaseModel):
    llm_call_count: int = 0
    llm_duration_seconds: float = 0
    web_search_count: int = 0
    web_fetch_count: int = 0
    agent_count: int = 0
    task_count: int = 0
    retry_count: int = 0
    claim_count: int = 0
    evidence_count: int = 0
    verified_claim_count: int = 0
    failed_task_count: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class RunSummary(BaseModel):
    run: RunRecord
    metrics: RunMetrics
    agents: list[AgentProfile]
    final_report_path: str | None = None


class RuntimeCheckpoint(BaseModel):
    """A compact stage-level snapshot used by the educational resume implementation."""

    run: RunRecord
    plan: CompanyPlan
    agents: list[AgentProfile]
    evidence: list[Evidence]
    manager_reports: list[ManagerReport]
    verification: VerificationReport
    qa: QAReport
    final_report: FinalReport
