"""Execute logical agent roles through one bounded model-call helper.

Agent functions remain ordinary async functions rather than a class hierarchy. The shared
executor adds visible status events and a semaphore, while each function connects one role
prompt to one Pydantic result.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel

from hivemind.events import EventBus, redact_text
from hivemind.prompts import (
    CEO_FOLLOW_UP_SYSTEM,
    CEO_PLAN_SYSTEM,
    FINAL_SYSTEM,
    MANAGER_PLAN_SYSTEM,
    MANAGER_SYNTHESIS_SYSTEM,
    MEMORY_CURATOR_SYSTEM,
    QA_SYSTEM,
    VERIFIER_SYSTEM,
    WORKER_SYSTEM,
)
from hivemind.providers.base import LLMProvider, ProviderError
from hivemind.schemas import (
    AgentProfile,
    AgentStatus,
    Claim,
    CompanyPlan,
    CurationResult,
    EventType,
    Evidence,
    FinalReport,
    FollowUpPlan,
    ManagerReport,
    MemoryCandidate,
    MemoryRecord,
    QAReport,
    RunRecord,
    TaskRecord,
    TaskStatus,
    VerificationFinding,
    VerificationReport,
    VerificationStatus,
    WorkerPlan,
    WorkerReport,
    utc_now,
)
from hivemind.security import wrap_untrusted_content

if TYPE_CHECKING:
    from hivemind.persistence import HiveMindRepository

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class AgentExecutor:
    """Bound concurrent model calls and publish public execution state."""

    def __init__(
        self,
        provider: LLMProvider,
        event_bus: EventBus,
        *,
        max_concurrent_calls: int,
        max_attempts: int = 2,
        call_timeout_seconds: float = 180,
        repository: HiveMindRepository | None = None,
        provider_router: Callable[[AgentProfile], LLMProvider] | None = None,
    ) -> None:
        self.provider = provider
        self.events = event_bus
        self.semaphore = asyncio.Semaphore(max_concurrent_calls)
        self.max_attempts = max_attempts
        self.call_timeout_seconds = call_timeout_seconds
        self.repository = repository
        self.provider_router = provider_router

    async def structured(
        self,
        run: RunRecord,
        agent: AgentProfile,
        schema: type[SchemaT],
        system_prompt: str,
        payload: dict[str, object],
        *,
        status: AgentStatus = AgentStatus.RUNNING,
        task_label: str | None = None,
    ) -> SchemaT:
        """Make one validated model call while respecting global concurrency."""

        agent.status = status
        active_provider = self.provider_router(agent) if self.provider_router else self.provider
        title = f"Round {run.round_number}: Produce {schema.__name__}"
        if task_label:
            title += f" ({task_label})"
        if self.repository:
            cached = await self.repository.get_completed_task_output(
                run.run_id, agent.agent_id, title
            )
            if cached:
                try:
                    result = schema.model_validate_json(cached)
                except ValueError:
                    # A corrupt or obsolete checkpoint is treated as missing and replaced.
                    pass
                else:
                    await self.events.emit(
                        EventType.AGENT_STATUS_CHANGED,
                        run.run_id,
                        f"Reused completed {schema.__name__} for {agent.name}.",
                        round_number=run.round_number,
                        agent_id=agent.agent_id,
                        parent_agent_id=agent.parent_agent_id,
                        metadata={"status": status.value, "checkpoint_reused": True},
                    )
                    return result
        task = TaskRecord(
            run_id=run.run_id,
            agent_id=agent.agent_id,
            title=title,
            objective=f"Run the {agent.kind.value} role and validate {schema.__name__}.",
            status=TaskStatus.RUNNING,
            attempt=1,
            max_attempts=self.max_attempts,
            started_at=utc_now(),
        )
        if self.repository:
            await self.repository.save_task(task)
        await self.events.emit(
            EventType.AGENT_STARTED,
            run.run_id,
            f"{agent.name} started {status.value}.",
            round_number=run.round_number,
            agent_id=agent.agent_id,
            parent_agent_id=agent.parent_agent_id,
            task_id=task.task_id,
            metadata={"status": status.value},
        )
        # Learning note: a semaphore bounds requests made by this Python process. A local
        # model server may still serialize work internally depending on its own resources.
        result: SchemaT | None = None
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            task.attempt = attempt
            task.status = TaskStatus.RUNNING
            if self.repository:
                await self.repository.save_task(task)
            before = int(getattr(active_provider, "validation_failures", 0))
            try:
                async with self.semaphore:
                    async with asyncio.timeout(self.call_timeout_seconds):
                        result = await active_provider.generate_structured(
                            schema, system_prompt, json.dumps(payload)
                        )
            except TimeoutError:
                last_error = ProviderError(
                    (
                        f"{active_provider.name} model '{active_provider.model}' did not finish "
                        f"within {self.call_timeout_seconds:g} seconds. Try a smaller model, "
                        "reduce concurrency, or increase HIVEMIND_LLM_CALL_TIMEOUT_SECONDS."
                    ),
                    retryable=False,
                )
            except Exception as exc:  # noqa: BLE001 - retry policy classifies the exception.
                last_error = exc
            after = int(getattr(active_provider, "validation_failures", before))
            for _ in range(max(0, after - before)):
                await self.events.emit(
                    EventType.VALIDATION_FAILED,
                    run.run_id,
                    f"Invalid {schema.__name__} output; requested one repair.",
                    round_number=run.round_number,
                    agent_id=agent.agent_id,
                    task_id=task.task_id,
                    metadata={"schema": schema.__name__},
                )
            if result is not None:
                break
            retryable = not isinstance(last_error, ProviderError) or last_error.retryable
            if not retryable or attempt >= self.max_attempts:
                task.status = TaskStatus.FAILED
                task.completed_at = utc_now()
                task.error_message = redact_text(str(last_error))[:500]
                if self.repository:
                    await self.repository.save_task(task)
                assert last_error is not None
                raise last_error
            task.status = TaskStatus.RETRYING
            agent.status = AgentStatus.RETRYING
            if self.repository:
                await self.repository.save_task(task)
            await self.events.emit(
                EventType.TASK_RETRYING,
                run.run_id,
                f"{agent.name} will retry after attempt {attempt}.",
                round_number=run.round_number,
                agent_id=agent.agent_id,
                task_id=task.task_id,
                metadata={
                    "status": AgentStatus.RETRYING.value,
                    "attempt": attempt + 1,
                    "max_attempts": self.max_attempts,
                    "error": str(last_error)[:300],
                },
            )
            await asyncio.sleep(min(0.25 * (2 ** (attempt - 1)), 2.0))
        assert result is not None
        task.status = TaskStatus.COMPLETED
        task.completed_at = utc_now()
        if self.repository:
            await self.repository.save_task(task, result)
        return result


async def run_ceo_planner(
    executor: AgentExecutor,
    run: RunRecord,
    ceo: AgentProfile,
    memories: list[MemoryRecord] | None = None,
) -> CompanyPlan:
    return await executor.structured(
        run,
        ceo,
        CompanyPlan,
        CEO_PLAN_SYSTEM,
        {"prompt": run.prompt, "memories": _memory_text(memories or [])},
        status=AgentStatus.PLANNING,
    )


async def run_ceo_follow_up_planner(
    executor: AgentExecutor,
    run: RunRecord,
    ceo: AgentProfile,
    qa: QAReport,
    verification: VerificationReport,
) -> FollowUpPlan:
    """Ask for only the additional organization needed to close QA gaps."""

    return await executor.structured(
        run,
        ceo,
        FollowUpPlan,
        CEO_FOLLOW_UP_SYSTEM,
        {
            "identified_gaps": qa.identified_gaps,
            "follow_up_questions": qa.follow_up_questions,
            "verification_findings": [
                item.model_dump(mode="json") for item in verification.findings
            ],
        },
        status=AgentStatus.PLANNING,
    )


async def run_manager_planner(
    executor: AgentExecutor,
    run: RunRecord,
    manager: AgentProfile,
    department: BaseModel,
    memories: list[MemoryRecord] | None = None,
) -> WorkerPlan:
    return await executor.structured(
        run,
        manager,
        WorkerPlan,
        MANAGER_PLAN_SYSTEM,
        {
            **department.model_dump(mode="json"),
            "memories": _memory_text(memories or []),
        },
        status=AgentStatus.PLANNING,
    )


async def run_worker(
    executor: AgentExecutor,
    run: RunRecord,
    worker: AgentProfile,
    evidence: list[Evidence],
    memories: list[MemoryRecord] | None = None,
) -> WorkerReport:
    aliases = {f"evidence_{index}": item.evidence_id for index, item in enumerate(evidence)}
    report = await executor.structured(
        run,
        worker,
        WorkerReport,
        WORKER_SYSTEM,
        {
            "role_key": worker.role_key,
            "evidence_ids": list(aliases),
            "evidence": [
                _evidence_for_prompt(item, evidence_id=alias)
                for alias, item in zip(aliases, evidence, strict=True)
            ],
            "memories": _memory_text(memories or []),
        },
    )
    return _resolve_worker_evidence_aliases(report, aliases)


async def run_manager_synthesis(
    executor: AgentExecutor,
    run: RunRecord,
    manager: AgentProfile,
    *,
    department_name: str,
    reports: list[WorkerReport],
    failed_workers: int,
) -> ManagerReport:
    return await executor.structured(
        run,
        manager,
        ManagerReport,
        MANAGER_SYNTHESIS_SYSTEM,
        {
            "name": department_name,
            "worker_reports": [item.model_dump(mode="json") for item in reports],
            "failed_workers": failed_workers,
        },
        status=AgentStatus.SYNTHESIZING,
    )


async def run_verifier(
    executor: AgentExecutor,
    run: RunRecord,
    verifier: AgentProfile,
    claims: list[Claim],
    evidence: list[Evidence],
) -> VerificationReport:
    aliases = {f"evidence_{index}": item.evidence_id for index, item in enumerate(evidence)}
    aliases_by_id = {evidence_id: alias for alias, evidence_id in aliases.items()}
    claim_aliases = {f"claim_{index}": item.claim_id for index, item in enumerate(claims, start=1)}
    claim_payloads = []
    for alias, item in zip(claim_aliases, claims, strict=True):
        payload = item.model_dump(mode="json")
        payload["claim_id"] = alias
        payload["evidence_ids"] = [
            aliases_by_id[evidence_id]
            for evidence_id in payload.get("evidence_ids", [])
            if evidence_id in aliases_by_id
        ]
        claim_payloads.append(payload)
    report = await executor.structured(
        run,
        verifier,
        VerificationReport,
        VERIFIER_SYSTEM,
        {
            "claims": claim_payloads,
            "evidence_ids": list(aliases),
            "evidence": [
                _evidence_for_prompt(item, evidence_id=alias)
                for alias, item in zip(aliases, evidence, strict=True)
            ],
        },
        status=AgentStatus.VERIFYING,
    )
    report = _resolve_verification_aliases(report, aliases, claim_aliases)
    return _enforce_verification_integrity(report, claims)


def _evidence_for_prompt(item: Evidence, *, evidence_id: str | None = None) -> dict[str, object]:
    """Expose bounded evidence while keeping external text inside trust markers."""

    content = item.content_excerpt or item.snippet
    return {
        "evidence_id": evidence_id or item.evidence_id,
        "title": item.title,
        "url": item.url,
        "source_type": item.source_type,
        "retrieved_at": item.retrieved_at.isoformat(),
        "content": wrap_untrusted_content(content, source_url=item.url),
    }


def _resolve_worker_evidence_aliases(report: WorkerReport, aliases: dict[str, str]) -> WorkerReport:
    """Resolve short prompt aliases and discard references the worker never received."""

    allowed = set(aliases.values())
    claims = []
    for claim in report.claims:
        resolved = [
            actual
            for reference in claim.evidence_ids
            if (actual := aliases.get(reference, reference)) in allowed
        ]
        resolved = list(dict.fromkeys(resolved))
        limitations = list(claim.limitations)
        if claim.evidence_ids and not resolved:
            limitations.append("The model returned no valid evidence reference for this claim.")
        claims.append(
            claim.model_copy(
                update={
                    "evidence_ids": resolved,
                    "limitations": list(dict.fromkeys(limitations)),
                }
            )
        )
    candidates = [
        candidate.model_copy(
            update={
                "source_evidence_ids": list(
                    dict.fromkeys(
                        actual
                        for reference in candidate.source_evidence_ids
                        if (actual := aliases.get(reference, reference)) in allowed
                    )
                )
            }
        )
        for candidate in report.memory_candidates
    ]
    return report.model_copy(update={"claims": claims, "memory_candidates": candidates})


def _resolve_verification_aliases(
    report: VerificationReport,
    evidence_aliases: dict[str, str],
    claim_aliases: dict[str, str],
) -> VerificationReport:
    """Resolve short verifier IDs while rejecting evidence it was never supplied."""

    allowed = set(evidence_aliases.values())

    def resolve(references: list[str]) -> list[str]:
        return list(
            dict.fromkeys(
                actual
                for reference in references
                if (actual := evidence_aliases.get(reference, reference)) in allowed
            )
        )

    findings = [
        finding.model_copy(
            update={
                "claim_id": claim_aliases.get(finding.claim_id, finding.claim_id),
                "supporting_evidence_ids": resolve(finding.supporting_evidence_ids),
                "conflicting_evidence_ids": resolve(finding.conflicting_evidence_ids),
            }
        )
        for finding in report.findings
    ]
    return report.model_copy(update={"findings": findings})


def _enforce_verification_integrity(
    report: VerificationReport, claims: list[Claim]
) -> VerificationReport:
    """Require every finding to name a supplied claim and evidence before verification."""

    claims_by_id = {item.claim_id: item for item in claims}
    accepted: dict[str, VerificationFinding] = {}
    for finding in report.findings:
        claim = claims_by_id.get(finding.claim_id)
        if claim is None or finding.claim_id in accepted:
            continue
        allowed_evidence = set(claim.evidence_ids)
        supporting = [item for item in finding.supporting_evidence_ids if item in allowed_evidence]
        conflicting = [
            item for item in finding.conflicting_evidence_ids if item in allowed_evidence
        ]
        status = finding.status
        explanation = finding.explanation
        if (
            status
            in {
                VerificationStatus.VERIFIED,
                VerificationStatus.PARTIALLY_VERIFIED,
            }
            and not supporting
        ):
            status = VerificationStatus.UNVERIFIED
            explanation = (
                "The verifier supplied no valid supporting evidence, so Python downgraded "
                "this finding to unverified."
            )
        elif status == VerificationStatus.CONTRADICTED and not conflicting:
            status = VerificationStatus.UNVERIFIED
            explanation = (
                "The verifier supplied no valid conflicting evidence, so Python downgraded "
                "this finding to unverified."
            )
        accepted[finding.claim_id] = finding.model_copy(
            update={
                "status": status,
                "explanation": explanation,
                "supporting_evidence_ids": supporting,
                "conflicting_evidence_ids": conflicting,
            }
        )
    for claim_id in claims_by_id:
        if claim_id not in accepted:
            accepted[claim_id] = VerificationFinding(
                claim_id=claim_id,
                status=VerificationStatus.UNVERIFIED,
                explanation="The verifier returned no valid finding for this claim.",
            )
    return report.model_copy(update={"findings": list(accepted.values())})


async def run_qa(
    executor: AgentExecutor,
    run: RunRecord,
    qa_agent: AgentProfile,
    verification: VerificationReport,
    *,
    request_demo_follow_up: bool,
) -> QAReport:
    return await executor.structured(
        run,
        qa_agent,
        QAReport,
        QA_SYSTEM,
        {
            "round_number": run.round_number,
            "request_demo_follow_up": request_demo_follow_up,
            "verification_findings": [
                item.model_dump(mode="json") for item in verification.findings
            ],
        },
    )


async def run_final_synthesis(
    executor: AgentExecutor,
    run: RunRecord,
    ceo: AgentProfile,
    verification: VerificationReport,
    qa: QAReport,
    manager_reports: list[ManagerReport],
    sources: list[BaseModel],
    approved_memories: list[MemoryRecord] | None = None,
) -> FinalReport:
    return await executor.structured(
        run,
        ceo,
        FinalReport,
        FINAL_SYSTEM,
        {
            "prompt": run.prompt,
            "verification_findings": [
                item.model_dump(mode="json") for item in verification.findings
            ],
            "qa": qa.model_dump(mode="json"),
            "manager_reports": [item.model_dump(mode="json") for item in manager_reports],
            "sources": [item.model_dump(mode="json") for item in sources],
            "approved_memories": _memory_text(approved_memories or []),
        },
        status=AgentStatus.SYNTHESIZING,
    )


async def run_memory_curator(
    executor: AgentExecutor,
    run: RunRecord,
    curator: AgentProfile,
    candidate: MemoryCandidate,
    existing_memories: list[MemoryRecord],
    *,
    candidate_number: int,
) -> CurationResult:
    """Classify one candidate without granting the model direct write access."""

    return await executor.structured(
        run,
        curator,
        CurationResult,
        MEMORY_CURATOR_SYSTEM,
        {
            "candidate": candidate.model_dump(mode="json"),
            "existing_memories": _memory_text(existing_memories),
        },
        task_label=f"candidate-{candidate_number}",
    )


def _memory_text(memories: list[MemoryRecord]) -> list[dict[str, object]]:
    """Provide only concise public memory fields, never the entire database."""

    return [
        {
            "memory_id": item.memory_id,
            "text": item.text,
            "memory_type": item.memory_type.value,
            "confidence": item.confidence,
        }
        for item in memories
    ]
