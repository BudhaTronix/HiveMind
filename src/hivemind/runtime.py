"""Coordinate the governed multi-agent workflow in one Python process.

The runtime turns validated model proposals into scheduled work. Manager planning and
independent worker research can overlap, but a shared semaphore limits model calls. Results
are gathered individually so one failed worker does not discard successful siblings.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from hivemind.agents import (
    AgentExecutor,
    run_ceo_follow_up_planner,
    run_ceo_planner,
    run_final_synthesis,
    run_manager_planner,
    run_manager_synthesis,
    run_memory_curator,
    run_qa,
    run_verifier,
    run_worker,
)
from hivemind.config import Settings
from hivemind.events import EventBus
from hivemind.governor import Governor
from hivemind.memory import MemoryStore, create_memory_store
from hivemind.persistence import ArtifactStore, HiveMindRepository
from hivemind.providers.base import LLMProvider
from hivemind.registry import AgentRegistry
from hivemind.schemas import (
    AgentKind,
    AgentProfile,
    AgentStatus,
    CompanyPlan,
    CurationDecision,
    DepartmentSpec,
    EventType,
    Evidence,
    FinalReport,
    ManagerReport,
    MemoryCandidate,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    QAReport,
    RunMetrics,
    RunRecord,
    RunStage,
    RunSummary,
    RuntimeCheckpoint,
    SourceReference,
    VerificationReport,
    WorkerPlan,
    WorkerReport,
    WorkerSpec,
    new_id,
    utc_now,
)
from hivemind.tools import ToolRegistry, build_default_tool_registry

_SUPPORTING_AGENT_RESERVE = 3  # Verifier, QA, and memory curator.


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


@dataclass(slots=True)
class DepartmentTeam:
    """One approved manager and the workers Python actually created for it."""

    department: DepartmentSpec
    manager: AgentProfile
    workers: list[tuple[WorkerSpec, AgentProfile]]


@dataclass(slots=True)
class WorkerOutcome:
    """Represent worker success or failure without raising through sibling tasks."""

    report: WorkerReport | None
    error: str | None = None


class HiveMindRuntime:
    """Run a transparent CEO → manager → worker research workflow."""

    def __init__(
        self,
        settings: Settings,
        provider: LLMProvider,
        event_bus: EventBus,
        *,
        governor: Governor | None = None,
        repository: HiveMindRepository | None = None,
        artifacts: ArtifactStore | None = None,
        registry: AgentRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
        memory_store: MemoryStore | None = None,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.events = event_bus
        self.governor = governor or Governor.from_settings(settings)
        self.repository = repository
        self.artifacts = artifacts
        self.registry = registry or AgentRegistry(repository)
        self.tools = tool_registry or build_default_tool_registry()
        self.memory_store = memory_store or create_memory_store(settings, repository)
        self.memory_candidates: list[tuple[MemoryCandidate, str]] = []
        self.web_semaphore = asyncio.Semaphore(self.governor.limits.max_concurrent_web_requests)
        self.executor = AgentExecutor(
            provider,
            event_bus,
            max_concurrent_calls=self.governor.limits.max_concurrent_llm_calls,
            max_attempts=self.governor.limits.max_retries_per_task,
            repository=repository,
        )

    async def run(
        self,
        prompt: str,
        *,
        project_id: str = "demo-project",
        existing_run: RunRecord | None = None,
    ) -> RuntimeResult:
        """Complete a governed research round and synthesize partial results safely."""

        run = existing_run or RunRecord(
            project_id=project_id,
            prompt=prompt,
            provider=self.provider.name,
            model=self.provider.model,
            max_rounds=self.governor.limits.max_research_rounds,
            round_number=1,
        )
        # Incomplete resume replays stage scheduling from round one, while the executor
        # reuses each valid per-round task output instead of making another model call.
        run.round_number = 1 if existing_run else max(1, run.round_number)
        if self.repository:
            await self.repository.create_project(project_id, project_id)
            await self.repository.save_run(run)
        if self.artifacts:
            await self.artifacts.prepare(run)
        agents: list[AgentProfile] = []
        evidence: list[Evidence] = []
        self.memory_candidates = []
        await self.events.emit(
            EventType.RUN_CREATED,
            run.run_id,
            f"Created run {run.run_id}.",
            round_number=run.round_number,
        )

        ceo = await self._profile(
            project_id,
            role_key="ceo",
            name="CEO Agent",
            kind=AgentKind.CEO,
            objective="Plan the organization and synthesize the final report.",
            status=AgentStatus.PLANNING,
        )
        agents.append(ceo)
        await self._spawn(run, ceo)
        await self._stage(run, RunStage.CEO_PLANNING, "CEO is designing the organization.")
        await self.events.emit(
            EventType.PLAN_REQUESTED,
            run.run_id,
            "CEO is proposing prompt-specific departments.",
            round_number=run.round_number,
            agent_id=ceo.agent_id,
        )
        ceo_memories = await self._retrieve_memories(run, ceo)
        proposed_plan = await run_ceo_planner(self.executor, run, ceo, ceo_memories)
        await self.events.emit(
            EventType.PLAN_RECEIVED,
            run.run_id,
            f"CEO requested {len(proposed_plan.departments)} departments.",
            round_number=run.round_number,
            agent_id=ceo.agent_id,
        )
        await self._stage(run, RunStage.VALIDATING_PLAN, "Governor is validating the CEO plan.")
        decision = self.governor.validate_company_plan(proposed_plan)
        assert isinstance(decision.plan, CompanyPlan)
        plan = decision.plan
        await self._publish_governor_decision(run, decision.reductions)
        if self.repository:
            await self.repository.save_report(
                run.run_id, "company_plan", plan, round_number=run.round_number
            )
        if self.artifacts:
            path = await self.artifacts.write_json(run.run_id, "plan.json", plan)
            if self.repository:
                await self.repository.save_artifact(run.run_id, "plan", path)

        manager_reports = await self._run_departments(
            run,
            project_id,
            ceo,
            plan.departments,
            agents,
            evidence,
        )

        verifier = await self._profile(
            project_id,
            role_key="verifier",
            name="Evidence Verifier",
            kind=AgentKind.VERIFIER,
            objective="Check claims against referenced evidence.",
            parent_agent_id=ceo.agent_id,
        )
        qa_agent = await self._profile(
            project_id,
            role_key="quality-assurance",
            name="Quality Assurance Agent",
            kind=AgentKind.QA,
            objective="Review coverage, contradictions, and evidence quality.",
            parent_agent_id=ceo.agent_id,
        )
        agents.extend([verifier, qa_agent])
        await self._spawn(run, verifier)
        await self._spawn(run, qa_agent)

        verification, qa = await self._verify_and_review(
            run,
            verifier,
            qa_agent,
            manager_reports,
            evidence,
            request_demo_follow_up=self.provider.name == "fake",
        )

        while not qa.can_finalize and run.round_number < run.max_rounds:
            await self.events.emit(
                EventType.REPLAN_REQUESTED,
                run.run_id,
                f"QA found {len(qa.identified_gaps)} important gap(s).",
                round_number=run.round_number,
                agent_id=qa_agent.agent_id,
            )
            await self._stage(
                run, RunStage.REPLANNING, "CEO is planning focused follow-up research."
            )
            run.round_number += 1
            if self.repository:
                await self.repository.save_run(run)
            follow_up = await run_ceo_follow_up_planner(self.executor, run, ceo, qa, verification)
            if not follow_up.needed or not follow_up.departments:
                break
            follow_company_plan = CompanyPlan(
                objective="Close the QA gaps without repeating completed research.",
                departments=follow_up.departments,
                rationale_summary=follow_up.rationale_summary,
            )
            follow_decision = self.governor.validate_company_plan(follow_company_plan)
            assert isinstance(follow_decision.plan, CompanyPlan)
            existing_roles = {item.role_key for item in agents}
            follow_departments = [
                item
                for item in follow_decision.plan.departments
                if item.role_key not in existing_roles
            ]
            await self._publish_governor_decision(run, follow_decision.reductions)
            await self.events.emit(
                EventType.REPLAN_APPROVED,
                run.run_id,
                f"Governor approved research round {run.round_number} of {run.max_rounds}.",
                round_number=run.round_number,
                agent_id=ceo.agent_id,
            )
            if self.repository:
                await self.repository.save_report(
                    run.run_id,
                    "follow_up_plan",
                    follow_up,
                    round_number=run.round_number,
                )
            if not follow_departments:
                break
            follow_reports = await self._run_departments(
                run,
                project_id,
                ceo,
                follow_departments,
                agents,
                evidence,
            )
            manager_reports.extend(follow_reports)
            verification, qa = await self._verify_and_review(
                run,
                verifier,
                qa_agent,
                manager_reports,
                evidence,
                request_demo_follow_up=False,
            )

        curator = await self._profile(
            project_id,
            role_key="memory-curator",
            name="Memory Curator",
            kind=AgentKind.MEMORY_CURATOR,
            objective="Approve only concise, durable, evidence-linked memories.",
            parent_agent_id=ceo.agent_id,
        )
        agents.append(curator)
        await self._spawn(run, curator)
        approved_memories = await self._curate_memories(run, curator, evidence)

        await self._stage(run, RunStage.FINAL_SYNTHESIS, "CEO is writing the final report.")
        await self.events.emit(
            EventType.FINAL_REPORT_STARTED,
            run.run_id,
            "Final report synthesis started.",
            round_number=run.round_number,
            agent_id=ceo.agent_id,
        )
        sources = _verified_sources(verification, evidence)
        final_report = await run_final_synthesis(
            self.executor,
            run,
            ceo,
            verification,
            qa,
            manager_reports,
            sources,
            approved_memories,
        )
        if not qa.can_finalize:
            final_report.research_limitations.append(
                f"QA gaps remained after the maximum of {run.max_rounds} research round(s)."
            )
        ceo.status = AgentStatus.COMPLETED
        await self._agent_completed(run, ceo, "CEO Agent completed final synthesis.", llm_calls=1)
        await self._stage(run, RunStage.COMPLETED, "Research workflow completed.")
        await self.events.emit(
            EventType.RUN_COMPLETED,
            run.run_id,
            "Final report is ready.",
            round_number=run.round_number,
            agent_id=ceo.agent_id,
        )
        result = RuntimeResult(
            run=run,
            plan=plan,
            agents=agents,
            evidence=evidence,
            manager_reports=manager_reports,
            verification=verification,
            qa=qa,
            final_report=final_report,
        )
        await self._persist_completed_run(result)
        return result

    async def resume(self, run_id: str) -> RuntimeResult:
        """Return a completed checkpoint or restart the earliest incomplete stage."""

        if not self.repository:
            raise RuntimeError("Resume requires a configured HiveMindRepository.")
        run = await self.repository.get_run(run_id)
        if run is None:
            raise ValueError(f"Run '{run_id}' was not found.")
        await self.repository.reset_stale_tasks(run_id)
        checkpoint_json = await self.repository.get_checkpoint(run_id, "completed")
        if checkpoint_json:
            checkpoint = RuntimeCheckpoint.model_validate_json(checkpoint_json)
            return RuntimeResult(
                run=checkpoint.run,
                plan=checkpoint.plan,
                agents=checkpoint.agents,
                evidence=checkpoint.evidence,
                manager_reports=checkpoint.manager_reports,
                verification=checkpoint.verification,
                qa=checkpoint.qa,
                final_report=checkpoint.final_report,
            )
        # Learning note: this is stage-level recovery, not a durable workflow engine. The
        # stable run ID and agent registry are reused; later checkpoints can skip more work.
        return await self.run(run.prompt, project_id=run.project_id, existing_run=run)

    async def _run_departments(
        self,
        run: RunRecord,
        project_id: str,
        ceo: AgentProfile,
        departments: list[DepartmentSpec],
        agents: list[AgentProfile],
        evidence: list[Evidence],
    ) -> list[ManagerReport]:
        """Plan and execute only the departments approved for the current round."""

        await self._stage(run, RunStage.SPAWNING_MANAGERS, "Creating approved managers.")
        managers = [await self._manager_profile(project_id, ceo, item) for item in departments]
        agents.extend(managers)
        for manager in managers:
            await self._spawn(run, manager)

        await self._stage(
            run, RunStage.MANAGERS_PLANNING, "Managers are planning teams concurrently."
        )
        manager_plan_results = await asyncio.gather(
            *[
                self._plan_manager(run, manager, department)
                for manager, department in zip(managers, departments, strict=True)
            ],
            return_exceptions=True,
        )
        await self._stage(run, RunStage.SPAWNING_WORKERS, "Creating approved workers.")
        teams: list[DepartmentTeam] = []
        supporting = sum(
            item.kind in {AgentKind.VERIFIER, AgentKind.QA, AgentKind.MEMORY_CURATOR}
            for item in agents
        )
        counted_agents = len(agents) + max(0, _SUPPORTING_AGENT_RESERVE - supporting)
        for department, manager, proposed_workers in zip(
            departments, managers, manager_plan_results, strict=True
        ):
            if isinstance(proposed_workers, BaseException):
                manager.status = AgentStatus.FAILED
                await self._agent_failed(run, manager, str(proposed_workers))
                teams.append(DepartmentTeam(department, manager, []))
                continue
            worker_decision = self.governor.validate_worker_plan(
                proposed_workers, current_organization_agents=counted_agents
            )
            assert isinstance(worker_decision.plan, WorkerPlan)
            await self._publish_governor_decision(run, worker_decision.reductions)
            worker_profiles = []
            for spec in worker_decision.plan.workers:
                profile = await self._profile(
                    project_id,
                    role_key=spec.role_key,
                    name=spec.name,
                    kind=AgentKind.WORKER,
                    objective=spec.objective,
                    parent_agent_id=manager.agent_id,
                    status=AgentStatus.QUEUED,
                )
                worker_profiles.append((spec, profile))
            counted_agents += len(worker_profiles)
            agents.extend(profile for _, profile in worker_profiles)
            for _, profile in worker_profiles:
                await self._spawn(run, profile)
            teams.append(DepartmentTeam(department, manager, worker_profiles))

        await self._stage(
            run, RunStage.WORKERS_RESEARCHING, "Approved workers are researching concurrently."
        )
        department_results = await asyncio.gather(
            *[self._execute_department(run, team, evidence) for team in teams],
            return_exceptions=True,
        )
        reports = []
        for team, result in zip(teams, department_results, strict=True):
            if isinstance(result, BaseException):
                await self._agent_failed(run, team.manager, str(result))
                reports.append(_fallback_manager_report(team, str(result)))
            else:
                reports.append(result)
        return reports

    async def _verify_and_review(
        self,
        run: RunRecord,
        verifier: AgentProfile,
        qa_agent: AgentProfile,
        manager_reports: list[ManagerReport],
        evidence: list[Evidence],
        *,
        request_demo_follow_up: bool,
    ) -> tuple[VerificationReport, QAReport]:
        """Verify all accumulated claims, then independently review research quality."""

        claims = [claim for report in manager_reports for claim in report.merged_claims]
        await self._stage(run, RunStage.VERIFYING, "Verifier is checking claim references.")
        await self.events.emit(
            EventType.VERIFICATION_STARTED,
            run.run_id,
            f"Verifier is checking {len(claims)} claim(s).",
            round_number=run.round_number,
            agent_id=verifier.agent_id,
        )
        verification = await run_verifier(self.executor, run, verifier, claims, evidence)
        if self.repository:
            await self.repository.save_report(
                run.run_id, "verification", verification, round_number=run.round_number
            )
        if self.artifacts:
            path = await self.artifacts.write_json(run.run_id, "verification.json", verification)
            if self.repository:
                await self.repository.save_artifact(run.run_id, "verification", path)
        verifier.status = AgentStatus.COMPLETED
        await self._agent_completed(
            run,
            verifier,
            f"Verifier checked {len(verification.findings)} claim(s).",
            llm_calls=1,
        )
        await self.events.emit(
            EventType.VERIFICATION_COMPLETED,
            run.run_id,
            f"Verifier checked {len(verification.findings)} claim(s).",
            round_number=run.round_number,
            agent_id=verifier.agent_id,
        )

        await self._stage(run, RunStage.QUALITY_REVIEW, "QA is reviewing coverage and evidence.")
        await self.events.emit(
            EventType.QA_STARTED,
            run.run_id,
            "Quality review started.",
            round_number=run.round_number,
            agent_id=qa_agent.agent_id,
        )
        qa = await run_qa(
            self.executor,
            run,
            qa_agent,
            verification,
            request_demo_follow_up=request_demo_follow_up,
        )
        if self.repository:
            await self.repository.save_report(run.run_id, "qa", qa, round_number=run.round_number)
        if self.artifacts:
            path = await self.artifacts.write_json(run.run_id, "qa_report.json", qa)
            if self.repository:
                await self.repository.save_artifact(run.run_id, "qa", path)
        qa_agent.status = AgentStatus.COMPLETED
        await self._agent_completed(
            run, qa_agent, f"QA quality score: {qa.quality_score:.0%}.", llm_calls=1
        )
        await self.events.emit(
            EventType.QA_COMPLETED,
            run.run_id,
            f"QA found {len(qa.identified_gaps)} gap(s); can finalize: {qa.can_finalize}.",
            round_number=run.round_number,
            agent_id=qa_agent.agent_id,
        )
        return verification, qa

    async def _plan_manager(
        self, run: RunRecord, manager: AgentProfile, department: DepartmentSpec
    ) -> WorkerPlan:
        memories = await self._retrieve_memories(run, manager)
        return await run_manager_planner(self.executor, run, manager, department, memories)

    async def _execute_department(
        self,
        run: RunRecord,
        team: DepartmentTeam,
        evidence: list[Evidence],
    ) -> ManagerReport:
        manager = team.manager
        if manager.status == AgentStatus.FAILED:
            return _fallback_manager_report(team, "Manager planning failed.")
        manager.status = AgentStatus.WAITING_FOR_CHILDREN
        await self.events.emit(
            EventType.AGENT_STATUS_CHANGED,
            run.run_id,
            f"{manager.name} is waiting for workers.",
            round_number=run.round_number,
            agent_id=manager.agent_id,
            parent_agent_id=manager.parent_agent_id,
            metadata={"status": manager.status.value},
        )
        outcomes = await asyncio.gather(
            *[self._execute_worker(run, spec, worker, evidence) for spec, worker in team.workers]
        )
        reports = [item.report for item in outcomes if item.report is not None]
        failed = sum(item.report is None for item in outcomes)
        await self._stage(
            run,
            RunStage.MANAGERS_SYNTHESIZING,
            f"{manager.name} is combining {len(reports)} result(s).",
        )
        report = await run_manager_synthesis(
            self.executor,
            run,
            manager,
            department_name=team.department.name,
            reports=reports,
            failed_workers=failed,
        )
        if self.repository:
            await self.repository.save_report(
                run.run_id,
                f"manager:{manager.role_key}",
                report,
                round_number=run.round_number,
                task_id=manager.agent_id,
            )
            await self.repository.save_claims(run.run_id, report.merged_claims)
        manager.status = AgentStatus.COMPLETED
        await self._agent_completed(
            run,
            manager,
            f"{manager.name} synthesized {len(reports)} worker report(s).",
            llm_calls=1,
        )
        return report

    async def _execute_worker(
        self,
        run: RunRecord,
        spec: WorkerSpec,
        worker: AgentProfile,
        evidence: list[Evidence],
    ) -> WorkerOutcome:
        task_id = new_id("task")
        worker_evidence: list[Evidence] = []
        if self.provider.name == "fake":
            worker_evidence.append(
                Evidence(
                    run_id=run.run_id,
                    task_id=task_id,
                    agent_id=worker.agent_id,
                    title=f"Simulated offline evidence for {spec.name}",
                    source_type="demo_simulation",
                    snippet="Synthetic evidence used only to exercise the workflow.",
                    search_query=spec.search_queries[0] if spec.search_queries else None,
                )
            )
            evidence.extend(worker_evidence)
            if self.repository:
                for item in worker_evidence:
                    await self.repository.save_evidence(item)
        elif self.settings.enable_web:
            worker_evidence = await self._research_web(run, spec, worker, task_id)
            evidence.extend(worker_evidence)
        try:
            memories = await self._retrieve_memories(run, worker)
            report = await run_worker(
                self.executor,
                run,
                worker,
                worker_evidence,
                memories,
            )
        except Exception as exc:  # noqa: BLE001 - task isolation intentionally catches providers.
            worker.status = AgentStatus.FAILED
            worker.tasks_failed += 1
            await self._agent_failed(run, worker, str(exc))
            return WorkerOutcome(report=None, error=str(exc))
        if self.repository:
            await self.repository.save_report(
                run.run_id,
                f"worker:{worker.role_key}",
                report,
                round_number=run.round_number,
                task_id=worker.agent_id,
            )
            await self.repository.save_claims(run.run_id, report.claims)
        self.memory_candidates.extend(
            (candidate, worker.agent_id) for candidate in report.memory_candidates
        )
        worker.status = AgentStatus.COMPLETED
        worker.tasks_completed += 1
        await self._agent_completed(
            run,
            worker,
            f"{worker.name} completed with {len(report.claims)} claim(s).",
            claims=len(report.claims),
            evidence=len(worker_evidence),
            llm_calls=1,
            learning_note=(
                "A semaphore limits simultaneous model requests; the model server decides "
                "how those requests use its hardware."
            ),
        )
        return WorkerOutcome(report=report)

    async def _retrieve_memories(self, run: RunRecord, agent: AgentProfile) -> list[MemoryRecord]:
        """Retrieve a few role-appropriate scopes rather than dumping all memory."""

        if self.memory_store is None:
            return []
        scope_map = {
            AgentKind.CEO: [
                (MemoryScope.COMPANY, "hivemind-company"),
                (MemoryScope.PROJECT, run.project_id),
                (MemoryScope.USER, "local-user"),
                (MemoryScope.RUN, run.run_id),
            ],
            AgentKind.MANAGER: [
                (MemoryScope.COMPANY, "hivemind-company"),
                (MemoryScope.PROJECT, run.project_id),
                (MemoryScope.AGENT, agent.agent_id),
                (MemoryScope.RUN, run.run_id),
            ],
            AgentKind.WORKER: [
                (MemoryScope.PROJECT, run.project_id),
                (MemoryScope.AGENT, agent.agent_id),
                (MemoryScope.RUN, run.run_id),
            ],
        }
        scopes = scope_map.get(agent.kind, [(MemoryScope.PROJECT, run.project_id)])
        await self.events.emit(
            EventType.MEMORY_SEARCH_STARTED,
            run.run_id,
            f"{agent.name} is searching relevant memory.",
            round_number=run.round_number,
            agent_id=agent.agent_id,
        )
        try:
            memories = await self.memory_store.search(
                f"{run.prompt} {agent.role_description}", scopes, limit=5
            )
        except Exception as exc:  # noqa: BLE001 - memory failure should not erase research.
            await self.events.emit(
                EventType.MEMORY_SEARCH_COMPLETED,
                run.run_id,
                f"Memory retrieval failed for {agent.name}; continuing without it.",
                round_number=run.round_number,
                agent_id=agent.agent_id,
                metadata={"count": 0, "error": str(exc)[:300]},
            )
            return []
        await self.events.emit(
            EventType.MEMORY_SEARCH_COMPLETED,
            run.run_id,
            f"{agent.name} retrieved {len(memories)} relevant memory item(s).",
            round_number=run.round_number,
            agent_id=agent.agent_id,
            metadata={
                "count": len(memories),
                "learning_note": (
                    "Memory is retrieved database text placed into context; it does not "
                    "change the model's weights."
                ),
            },
        )
        return memories

    async def _curate_memories(
        self,
        run: RunRecord,
        curator: AgentProfile,
        evidence: list[Evidence],
    ) -> list[MemoryRecord]:
        """Ask the curator for decisions, then let Python perform approved writes."""

        await self._stage(run, RunStage.CURATING_MEMORY, "Curating durable project memory.")
        if self.memory_store is None or not self.memory_candidates:
            curator.status = AgentStatus.COMPLETED
            await self._agent_completed(
                run, curator, "Memory curator had no durable candidates to review."
            )
            return []
        existing = await self.memory_store.search(
            run.prompt, [(MemoryScope.PROJECT, run.project_id)], limit=20
        )
        existing_text = {item.text.casefold().strip(): item for item in existing}
        valid_evidence_ids = {item.evidence_id for item in evidence}
        approved: list[MemoryRecord] = []
        for index, (candidate, source_agent_id) in enumerate(self.memory_candidates, start=1):
            if candidate.text.casefold().strip() in existing_text:
                await self.events.emit(
                    EventType.MEMORY_REJECTED,
                    run.run_id,
                    "Memory curator rejected a duplicate candidate.",
                    round_number=run.round_number,
                    agent_id=curator.agent_id,
                    metadata={"decision": CurationDecision.REJECT.value},
                )
                continue
            candidate = candidate.model_copy(
                update={
                    "source_evidence_ids": [
                        item for item in candidate.source_evidence_ids if item in valid_evidence_ids
                    ]
                }
            )
            decision = await run_memory_curator(
                self.executor,
                run,
                curator,
                candidate,
                existing,
                candidate_number=index,
            )
            if decision.decision not in {
                CurationDecision.SAVE,
                CurationDecision.SUPERSEDES_EXISTING,
            }:
                await self.events.emit(
                    EventType.MEMORY_REJECTED,
                    run.run_id,
                    f"Memory candidate was classified {decision.decision.value}.",
                    round_number=run.round_number,
                    agent_id=curator.agent_id,
                    metadata={"decision": decision.decision.value},
                )
                continue
            if (
                decision.decision == CurationDecision.SUPERSEDES_EXISTING
                and decision.supersedes_memory_id
            ):
                superseded = (
                    await self.repository.get_memory(decision.supersedes_memory_id)
                    if self.repository
                    else None
                )
                if superseded:
                    superseded.status = MemoryStatus.SUPERSEDED
                    superseded.updated_at = utc_now()
                    await self.memory_store.save(superseded)
            record = MemoryRecord(
                scope=MemoryScope.PROJECT,
                scope_id=run.project_id,
                text=candidate.text,
                memory_type=candidate.memory_type,
                source_agent_id=source_agent_id,
                source_run_id=run.run_id,
                source_evidence_ids=candidate.source_evidence_ids,
                confidence=candidate.confidence,
            )
            await self.memory_store.save(record)
            existing.append(record)
            existing_text[record.text.casefold().strip()] = record
            approved.append(record)
            await self.events.emit(
                EventType.MEMORY_SAVED,
                run.run_id,
                "Memory curator approved a durable project memory.",
                round_number=run.round_number,
                agent_id=curator.agent_id,
                metadata={"memory_id": record.memory_id, "scope": record.scope.value},
            )
        curator.status = AgentStatus.COMPLETED
        await self._agent_completed(
            run,
            curator,
            f"Memory curator approved {len(approved)} item(s).",
            llm_calls=len(self.memory_candidates),
        )
        return approved

    async def _research_web(
        self,
        run: RunRecord,
        spec: WorkerSpec,
        worker: AgentProfile,
        task_id: str,
    ) -> list[Evidence]:
        """Execute only the approved search queries and fetch one top result each."""

        collected: list[Evidence] = []
        for query in spec.search_queries:
            await self.events.emit(
                EventType.TOOL_STARTED,
                run.run_id,
                f"{worker.name} started web search.",
                round_number=run.round_number,
                task_id=task_id,
                agent_id=worker.agent_id,
                metadata={"tool": "web_search", "query": query},
            )
            try:
                async with self.web_semaphore:
                    results = await self.tools.execute(
                        "web_search",
                        agent_kind=AgentKind.WORKER,
                        query=query,
                        max_results=3,
                    )
            except Exception as exc:  # noqa: BLE001 - tool failure stays local to the worker.
                await self._tool_failed(run, worker, task_id, "web_search", exc)
                continue
            await self.events.emit(
                EventType.TOOL_COMPLETED,
                run.run_id,
                f"Web search returned {len(results)} result(s).",
                round_number=run.round_number,
                task_id=task_id,
                agent_id=worker.agent_id,
                metadata={"tool": "web_search", "results": len(results)},
            )
            query_evidence = [
                Evidence(
                    run_id=run.run_id,
                    task_id=task_id,
                    agent_id=worker.agent_id,
                    url=result.url,
                    title=result.title,
                    source_type="search_result_snippet",
                    snippet=result.snippet[:1_500],
                    search_query=query,
                )
                for result in results
            ]
            collected.extend(query_evidence)
            if query_evidence:
                await self._fetch_top_result(run, worker, task_id, query_evidence[0])
            if self.repository:
                for item in query_evidence:
                    await self.repository.save_evidence(item)
        return collected

    async def _fetch_top_result(
        self,
        run: RunRecord,
        worker: AgentProfile,
        task_id: str,
        evidence: Evidence,
    ) -> None:
        """Enrich one search snippet with a bounded page excerpt when safe and available."""

        assert evidence.url is not None
        await self.events.emit(
            EventType.TOOL_STARTED,
            run.run_id,
            f"{worker.name} started web fetch.",
            round_number=run.round_number,
            task_id=task_id,
            agent_id=worker.agent_id,
            metadata={"tool": "web_fetch", "url": evidence.url},
        )
        try:
            async with self.web_semaphore:
                page = await self.tools.execute(
                    "web_fetch",
                    agent_kind=AgentKind.WORKER,
                    url=evidence.url,
                )
        except Exception as exc:  # noqa: BLE001 - the search snippet remains usable evidence.
            await self._tool_failed(run, worker, task_id, "web_fetch", exc)
            return
        evidence.url = page.url
        evidence.title = page.title or evidence.title
        evidence.content_excerpt = page.excerpt
        evidence.source_type = "web_page"
        await self.events.emit(
            EventType.TOOL_COMPLETED,
            run.run_id,
            f"Web fetch extracted {len(page.excerpt)} character(s).",
            round_number=run.round_number,
            task_id=task_id,
            agent_id=worker.agent_id,
            metadata={"tool": "web_fetch", "url": page.url},
        )

    async def _tool_failed(
        self,
        run: RunRecord,
        worker: AgentProfile,
        task_id: str,
        tool: str,
        error: Exception,
    ) -> None:
        await self.events.emit(
            EventType.TOOL_FAILED,
            run.run_id,
            f"{tool} failed for {worker.name}; research will continue.",
            round_number=run.round_number,
            task_id=task_id,
            agent_id=worker.agent_id,
            metadata={"tool": tool, "error": str(error)[:300]},
        )

    async def _publish_governor_decision(self, run: RunRecord, reductions: tuple[str, ...]) -> None:
        for message in reductions:
            await self.events.emit(
                EventType.PLAN_REDUCED_BY_GOVERNOR,
                run.run_id,
                message,
                round_number=run.round_number,
            )
        await self.events.emit(
            EventType.PLAN_VALIDATED,
            run.run_id,
            "Governor approved the bounded plan.",
            round_number=run.round_number,
            metadata={
                "learning_note": (
                    "The model proposed roles as data; Python validated limits before "
                    "creating any of them."
                )
            },
        )

    async def _spawn(self, run: RunRecord, agent: AgentProfile) -> None:
        await self.registry.save(agent)
        await self.events.emit(
            EventType.AGENT_SPAWNED,
            run.run_id,
            f"Created {agent.name} ({agent.kind.value}).",
            round_number=run.round_number,
            agent_id=agent.agent_id,
            parent_agent_id=agent.parent_agent_id,
            metadata={
                "name": agent.name,
                "kind": agent.kind.value,
                "status": agent.status.value,
            },
        )

    async def _agent_completed(
        self,
        run: RunRecord,
        agent: AgentProfile,
        message: str,
        *,
        claims: int = 0,
        evidence: int = 0,
        llm_calls: int = 0,
        learning_note: str | None = None,
    ) -> None:
        metadata: dict[str, object] = {
            "status": agent.status.value,
            "claims": claims,
            "evidence": evidence,
            "claims_added": claims,
            "evidence_added": evidence,
            "llm_calls": llm_calls,
        }
        if learning_note:
            metadata["learning_note"] = learning_note
        await self.registry.save(agent)
        await self.events.emit(
            EventType.AGENT_COMPLETED,
            run.run_id,
            message,
            round_number=run.round_number,
            agent_id=agent.agent_id,
            parent_agent_id=agent.parent_agent_id,
            metadata=metadata,
        )

    async def _agent_failed(self, run: RunRecord, agent: AgentProfile, error: str) -> None:
        agent.status = AgentStatus.FAILED
        await self.registry.save(agent)
        await self.events.emit(
            EventType.AGENT_FAILED,
            run.run_id,
            f"{agent.name} failed; the run will continue with partial results.",
            round_number=run.round_number,
            agent_id=agent.agent_id,
            parent_agent_id=agent.parent_agent_id,
            metadata={"status": agent.status.value, "error": error[:300]},
        )

    async def _stage(self, run: RunRecord, stage: RunStage, message: str) -> None:
        run.stage = stage
        run.updated_at = utc_now()
        if self.repository:
            await self.repository.save_run(run)
        await self.events.emit(
            EventType.STAGE_CHANGED,
            run.run_id,
            message,
            round_number=run.round_number,
            metadata={"stage": stage.value},
        )

    async def _profile(
        self,
        project_id: str,
        *,
        role_key: str,
        name: str,
        kind: AgentKind,
        objective: str,
        parent_agent_id: str | None = None,
        status: AgentStatus = AgentStatus.CREATED,
    ) -> AgentProfile:
        return await self.registry.create_or_get(
            project_id=project_id,
            role_key=role_key,
            name=name,
            kind=kind,
            role_description=objective,
            parent_agent_id=parent_agent_id,
            status=status,
        )

    async def _manager_profile(
        self, project_id: str, ceo: AgentProfile, department: DepartmentSpec
    ) -> AgentProfile:
        return await self._profile(
            project_id,
            role_key=department.role_key,
            name=department.manager_name,
            kind=AgentKind.MANAGER,
            objective=department.objective,
            parent_agent_id=ceo.agent_id,
            status=AgentStatus.QUEUED,
        )

    async def _persist_completed_run(self, result: RuntimeResult) -> None:
        """Save the final checkpoint and every available portable artifact."""

        if self.repository:
            await self.repository.save_run(result.run)
            await self.repository.save_report(
                result.run.run_id,
                "final",
                result.final_report,
                round_number=result.run.round_number,
            )
        final_path = None
        if self.artifacts:
            run_id = result.run.run_id
            evidence_path = await self.artifacts.write_json(
                run_id, "evidence.json", result.evidence
            )
            final_json = await self.artifacts.write_json(
                run_id, "final_report.json", result.final_report
            )
            final_path = await self.artifacts.write_final_markdown(run_id, result.final_report)
            if self.repository:
                await self.repository.save_artifact(run_id, "evidence", evidence_path)
                await self.repository.save_artifact(run_id, "final_json", final_json)
                await self.repository.save_artifact(run_id, "final_markdown", final_path)
        metrics = RunMetrics(
            llm_call_count=sum(
                int(item.metadata.get("llm_calls", 0)) for item in self.events.events
            ),
            agent_count=len(result.agents),
            task_count=(
                len(await self.repository.list_tasks(result.run.run_id)) if self.repository else 0
            ),
            retry_count=sum(
                item.event_type == EventType.TASK_RETRYING for item in self.events.events
            ),
            claim_count=sum(len(item.merged_claims) for item in result.manager_reports),
            evidence_count=len(result.evidence),
            verified_claim_count=sum(
                item.status.value == "verified" for item in result.verification.findings
            ),
            failed_task_count=sum(
                item.event_type == EventType.AGENT_FAILED for item in self.events.events
            ),
        )
        summary = RunSummary(
            run=result.run,
            metrics=metrics,
            agents=result.agents,
            final_report_path=str(final_path) if final_path else None,
        )
        if self.artifacts:
            summary_path = await self.artifacts.write_json(
                result.run.run_id, "run_summary.json", summary
            )
            if self.repository:
                await self.repository.save_artifact(result.run.run_id, "run_summary", summary_path)
        if self.repository:
            checkpoint = RuntimeCheckpoint(
                run=result.run,
                plan=result.plan,
                agents=result.agents,
                evidence=result.evidence,
                manager_reports=result.manager_reports,
                verification=result.verification,
                qa=result.qa,
                final_report=result.final_report,
            )
            await self.repository.save_checkpoint(result.run.run_id, "completed", checkpoint)


def _fallback_manager_report(team: DepartmentTeam, error: str) -> ManagerReport:
    """Keep final synthesis possible when a whole department fails."""

    return ManagerReport(
        department_name=team.department.name,
        summary="The department could not produce a model-generated report.",
        research_gaps=[error[:300]],
        recommended_follow_up=[f"Retry {team.department.name} research."],
    )


def _verified_sources(
    verification: VerificationReport, evidence: list[Evidence]
) -> list[SourceReference]:
    """Build source references only from evidence records that actually exist."""

    evidence_by_id = {item.evidence_id: item for item in evidence}
    sources: dict[str, SourceReference] = {}
    for finding in verification.findings:
        for evidence_id in finding.supporting_evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if item is None:
                continue
            if evidence_id not in sources:
                sources[evidence_id] = SourceReference(
                    evidence_id=item.evidence_id,
                    title=item.title,
                    url=item.url,
                    retrieved_at=item.retrieved_at,
                    claims_supported=[finding.claim_id],
                    verification_status=finding.status,
                )
            else:
                sources[evidence_id].claims_supported.append(finding.claim_id)
    return list(sources.values())
