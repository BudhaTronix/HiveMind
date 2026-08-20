"""Execute logical agent roles through one bounded model-call helper.

Agent functions remain ordinary async functions rather than a class hierarchy. The shared
executor adds visible status events and a semaphore, while each function connects one role
prompt to one Pydantic result.
"""

from __future__ import annotations

import asyncio
import json
from typing import TypeVar

from pydantic import BaseModel

from hivemind.events import EventBus
from hivemind.prompts import (
    CEO_PLAN_SYSTEM,
    FINAL_SYSTEM,
    MANAGER_PLAN_SYSTEM,
    MANAGER_SYNTHESIS_SYSTEM,
    QA_SYSTEM,
    VERIFIER_SYSTEM,
    WORKER_SYSTEM,
)
from hivemind.providers.base import LLMProvider
from hivemind.schemas import (
    AgentProfile,
    AgentStatus,
    CompanyPlan,
    EventType,
    FinalReport,
    ManagerReport,
    QAReport,
    RunRecord,
    VerificationReport,
    WorkerPlan,
    WorkerReport,
)

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class AgentExecutor:
    """Bound concurrent model calls and publish public execution state."""

    def __init__(
        self,
        provider: LLMProvider,
        event_bus: EventBus,
        *,
        max_concurrent_calls: int,
    ) -> None:
        self.provider = provider
        self.events = event_bus
        self.semaphore = asyncio.Semaphore(max_concurrent_calls)

    async def structured(
        self,
        run: RunRecord,
        agent: AgentProfile,
        schema: type[SchemaT],
        system_prompt: str,
        payload: dict[str, object],
        *,
        status: AgentStatus = AgentStatus.RUNNING,
    ) -> SchemaT:
        """Make one validated model call while respecting global concurrency."""

        agent.status = status
        await self.events.emit(
            EventType.AGENT_STARTED,
            run.run_id,
            f"{agent.name} started {status.value}.",
            round_number=run.round_number,
            agent_id=agent.agent_id,
            parent_agent_id=agent.parent_agent_id,
            metadata={"status": status.value},
        )
        # Learning note: a semaphore bounds requests made by this Python process. A local
        # model server may still serialize work internally depending on its own resources.
        async with self.semaphore:
            before = int(getattr(self.provider, "validation_failures", 0))
            try:
                result = await self.provider.generate_structured(
                    schema, system_prompt, json.dumps(payload)
                )
            finally:
                after = int(getattr(self.provider, "validation_failures", before))
                for _ in range(max(0, after - before)):
                    await self.events.emit(
                        EventType.VALIDATION_FAILED,
                        run.run_id,
                        f"Invalid {schema.__name__} output; requested one repair.",
                        round_number=run.round_number,
                        agent_id=agent.agent_id,
                        metadata={"schema": schema.__name__},
                    )
        return result


async def run_ceo_planner(
    executor: AgentExecutor, run: RunRecord, ceo: AgentProfile
) -> CompanyPlan:
    return await executor.structured(
        run, ceo, CompanyPlan, CEO_PLAN_SYSTEM, {"prompt": run.prompt}, status=AgentStatus.PLANNING
    )


async def run_manager_planner(
    executor: AgentExecutor,
    run: RunRecord,
    manager: AgentProfile,
    department: BaseModel,
) -> WorkerPlan:
    return await executor.structured(
        run,
        manager,
        WorkerPlan,
        MANAGER_PLAN_SYSTEM,
        department.model_dump(mode="json"),
        status=AgentStatus.PLANNING,
    )


async def run_worker(
    executor: AgentExecutor,
    run: RunRecord,
    worker: AgentProfile,
    evidence_ids: list[str],
) -> WorkerReport:
    return await executor.structured(
        run,
        worker,
        WorkerReport,
        WORKER_SYSTEM,
        {"role_key": worker.role_key, "evidence_ids": evidence_ids},
    )


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
    claims: list[BaseModel],
    evidence_ids: list[str],
) -> VerificationReport:
    return await executor.structured(
        run,
        verifier,
        VerificationReport,
        VERIFIER_SYSTEM,
        {
            "claims": [item.model_dump(mode="json") for item in claims],
            "evidence_ids": evidence_ids,
        },
        status=AgentStatus.VERIFYING,
    )


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
    sources: list[BaseModel],
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
            "sources": [item.model_dump(mode="json") for item in sources],
        },
        status=AgentStatus.SYNTHESIZING,
    )
