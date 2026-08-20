"""Coordinate the educational multi-agent workflow in one Python process.

This first runtime already demonstrates the core meaning of an agent: a role, identity,
status, prompt, model call, and result. Later subsystems add persistence and web tools, but
Python—not the model—always decides what is created and executed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from hivemind.config import Settings
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
    AgentKind,
    AgentProfile,
    AgentStatus,
    CompanyPlan,
    EventType,
    Evidence,
    FinalReport,
    ManagerReport,
    QAReport,
    RunRecord,
    RunStage,
    SourceReference,
    VerificationReport,
    WorkerPlan,
    WorkerReport,
    new_id,
)


@dataclass(slots=True)
class RuntimeResult:
    """The useful in-memory outputs of a completed run."""

    run: RunRecord
    plan: CompanyPlan
    agents: list[AgentProfile]
    evidence: list[Evidence]
    manager_reports: list[ManagerReport]
    verification: VerificationReport
    qa: QAReport
    final_report: FinalReport


class HiveMindRuntime:
    """Run a transparent CEO → manager → worker research workflow."""

    def __init__(self, settings: Settings, provider: LLMProvider, event_bus: EventBus) -> None:
        self.settings = settings
        self.provider = provider
        self.events = event_bus

    async def run(self, prompt: str, *, project_id: str = "demo-project") -> RuntimeResult:
        """Complete an offline-capable first-round workflow."""

        run = RunRecord(
            project_id=project_id,
            prompt=prompt,
            provider=self.provider.name,
            model=self.provider.model,
            max_rounds=self.settings.max_research_rounds,
        )
        agents: list[AgentProfile] = []
        evidence: list[Evidence] = []
        manager_reports: list[ManagerReport] = []

        await self.events.emit(EventType.RUN_CREATED, run.run_id, f"Created run {run.run_id}.")
        ceo = AgentProfile(
            project_id=project_id,
            role_key="ceo",
            name="CEO Agent",
            kind=AgentKind.CEO,
            role_description="Plans the organization and synthesizes the final report.",
            status=AgentStatus.PLANNING,
        )
        agents.append(ceo)
        await self._spawn(run, ceo)
        await self._stage(run, RunStage.CEO_PLANNING, "CEO is designing the organization.")
        await self.events.emit(
            EventType.PLAN_REQUESTED,
            run.run_id,
            "CEO is proposing prompt-specific departments.",
            agent_id=ceo.agent_id,
        )
        plan = await self.provider.generate_structured(
            CompanyPlan, CEO_PLAN_SYSTEM, json.dumps({"prompt": prompt})
        )
        # Learning note: a model response is only a proposal. Slicing here is a first visible
        # guardrail; the dedicated Governor later owns all related limits.
        plan = plan.model_copy(
            update={"departments": plan.departments[: self.settings.max_managers]}
        )
        await self.events.emit(
            EventType.PLAN_RECEIVED,
            run.run_id,
            f"CEO requested {len(plan.departments)} departments.",
            agent_id=ceo.agent_id,
        )
        await self.events.emit(
            EventType.PLAN_VALIDATED,
            run.run_id,
            f"Runtime approved {len(plan.departments)} departments.",
            agent_id=ceo.agent_id,
            metadata={
                "learning_note": (
                    "The CEO returned data; Python is now creating the approved agents."
                )
            },
        )

        for department in plan.departments:
            manager = AgentProfile(
                project_id=project_id,
                role_key=department.role_key,
                name=department.manager_name,
                kind=AgentKind.MANAGER,
                role_description=department.objective,
                parent_agent_id=ceo.agent_id,
                status=AgentStatus.PLANNING,
            )
            agents.append(manager)
            await self._spawn(run, manager)
            worker_plan = await self.provider.generate_structured(
                WorkerPlan,
                MANAGER_PLAN_SYSTEM,
                department.model_dump_json(),
            )
            reports: list[WorkerReport] = []
            for worker_spec in worker_plan.workers[: self.settings.max_workers_per_manager]:
                worker = AgentProfile(
                    project_id=project_id,
                    role_key=worker_spec.role_key,
                    name=worker_spec.name,
                    kind=AgentKind.WORKER,
                    role_description=worker_spec.objective,
                    parent_agent_id=manager.agent_id,
                    status=AgentStatus.RUNNING,
                )
                agents.append(worker)
                await self._spawn(run, worker)
                task_id = new_id("task")
                item = Evidence(
                    run_id=run.run_id,
                    task_id=task_id,
                    agent_id=worker.agent_id,
                    title=f"Simulated offline evidence for {worker_spec.name}",
                    source_type="demo_simulation",
                    snippet="Synthetic evidence used only to exercise the workflow.",
                    search_query=worker_spec.search_queries[0]
                    if worker_spec.search_queries
                    else None,
                )
                evidence.append(item)
                report = await self.provider.generate_structured(
                    WorkerReport,
                    WORKER_SYSTEM,
                    json.dumps({"role_key": worker.role_key, "evidence_ids": [item.evidence_id]}),
                )
                reports.append(report)
                worker.status = AgentStatus.COMPLETED
                await self.events.emit(
                    EventType.AGENT_COMPLETED,
                    run.run_id,
                    f"{worker.name} completed with {len(report.claims)} claim(s).",
                    agent_id=worker.agent_id,
                    parent_agent_id=manager.agent_id,
                )
            manager.status = AgentStatus.SYNTHESIZING
            manager_report = await self.provider.generate_structured(
                ManagerReport,
                MANAGER_SYNTHESIS_SYSTEM,
                json.dumps(
                    {
                        "name": department.name,
                        "worker_reports": [item.model_dump(mode="json") for item in reports],
                        "failed_workers": 0,
                    }
                ),
            )
            manager_reports.append(manager_report)
            manager.status = AgentStatus.COMPLETED
            await self.events.emit(
                EventType.AGENT_COMPLETED,
                run.run_id,
                f"{manager.name} synthesized {len(reports)} worker report(s).",
                agent_id=manager.agent_id,
                parent_agent_id=ceo.agent_id,
            )

        claims = [claim for report in manager_reports for claim in report.merged_claims]
        await self._stage(run, RunStage.VERIFYING, "Verifier is checking claim references.")
        verification = await self.provider.generate_structured(
            VerificationReport,
            VERIFIER_SYSTEM,
            json.dumps(
                {
                    "claims": [item.model_dump(mode="json") for item in claims],
                    "evidence_ids": [item.evidence_id for item in evidence],
                }
            ),
        )
        await self.events.emit(
            EventType.VERIFICATION_COMPLETED,
            run.run_id,
            f"Verifier checked {len(verification.findings)} claim(s).",
        )
        await self._stage(run, RunStage.QUALITY_REVIEW, "QA is reviewing coverage and evidence.")
        qa = await self.provider.generate_structured(
            QAReport,
            QA_SYSTEM,
            json.dumps(
                {
                    "round_number": 1,
                    "request_demo_follow_up": False,
                    "verification_findings": [
                        item.model_dump(mode="json") for item in verification.findings
                    ],
                }
            ),
        )
        await self.events.emit(
            EventType.QA_COMPLETED,
            run.run_id,
            f"QA quality score: {qa.quality_score:.0%}.",
        )
        await self._stage(run, RunStage.FINAL_SYNTHESIS, "CEO is writing the final report.")
        evidence_by_id = {item.evidence_id: item for item in evidence}
        sources = []
        for finding in verification.findings:
            for evidence_id in finding.supporting_evidence_ids:
                item = evidence_by_id[evidence_id]
                sources.append(
                    SourceReference(
                        evidence_id=item.evidence_id,
                        title=item.title,
                        url=item.url,
                        retrieved_at=item.retrieved_at,
                        claims_supported=[finding.claim_id],
                        verification_status=finding.status,
                    )
                )
        final_report = await self.provider.generate_structured(
            FinalReport,
            FINAL_SYSTEM,
            json.dumps(
                {
                    "prompt": prompt,
                    "verification_findings": [
                        item.model_dump(mode="json") for item in verification.findings
                    ],
                    "sources": [item.model_dump(mode="json") for item in sources],
                }
            ),
        )
        ceo.status = AgentStatus.COMPLETED
        await self._stage(run, RunStage.COMPLETED, "Research workflow completed.")
        await self.events.emit(
            EventType.RUN_COMPLETED,
            run.run_id,
            "Final report is ready.",
            agent_id=ceo.agent_id,
        )
        return RuntimeResult(
            run=run,
            plan=plan,
            agents=agents,
            evidence=evidence,
            manager_reports=manager_reports,
            verification=verification,
            qa=qa,
            final_report=final_report,
        )

    async def _spawn(self, run: RunRecord, agent: AgentProfile) -> None:
        await self.events.emit(
            EventType.AGENT_SPAWNED,
            run.run_id,
            f"Created {agent.name} ({agent.kind.value}).",
            agent_id=agent.agent_id,
            parent_agent_id=agent.parent_agent_id,
            metadata={"name": agent.name, "kind": agent.kind.value},
        )

    async def _stage(self, run: RunRecord, stage: RunStage, message: str) -> None:
        run.stage = stage
        await self.events.emit(EventType.STAGE_CHANGED, run.run_id, message)
