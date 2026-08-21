"""Reconstruct browser presentation state solely from public persisted records."""

from __future__ import annotations

import json
from collections import Counter
from contextlib import suppress

from hivemind.persistence import HiveMindRepository
from hivemind.schemas import (
    AgentKind,
    AgentStatus,
    EventType,
    FinalReport,
    RunMetrics,
    TaskStatus,
)
from hivemind.web.models import AgentDetails, AgentNodeState, EvidenceSummary, RunSnapshot


async def build_snapshot(repository: HiveMindRepository, run_id: str) -> RunSnapshot | None:
    run = await repository.get_run(run_id)
    if run is None:
        return None
    events = await repository.list_events(run_id)
    tasks = await repository.list_tasks(run_id)
    handoffs = await repository.list_handoffs(run_id)
    evidence = await repository.list_evidence(run_id)
    tool_activity = await repository.list_tool_calls(run_id)

    spawn_events = {}
    for event in events:
        if event.event_type == EventType.AGENT_SPAWNED and event.agent_id:
            spawn_events.setdefault(event.agent_id, event)
    member_ids = list(spawn_events)
    profiles = [await repository.get_agent(agent_id) for agent_id in member_ids]
    task_map = _latest_active_tasks(tasks)
    states = []
    for profile in profiles:
        if profile is None:
            continue
        spawn = spawn_events[profile.agent_id]
        kind = profile.kind
        with suppress(ValueError):
            kind = AgentKind(str(spawn.metadata.get("kind", profile.kind.value)))
        profile = profile.model_copy(
            update={
                "name": str(spawn.metadata.get("name", profile.name)),
                "role_key": str(spawn.metadata.get("role_key", profile.role_key)),
                "kind": kind,
                "parent_agent_id": spawn.parent_agent_id,
            }
        )
        related = [event for event in events if event.agent_id == profile.agent_id]
        state = _agent_state(profile.status, related)
        counters = Counter()
        for event in related:
            counters["claims"] += int(event.metadata.get("claims_added", 0))
            counters["evidence"] += int(event.metadata.get("evidence_added", 0))
            counters["retries"] += event.event_type == EventType.TASK_RETRYING
        states.append(
            AgentNodeState(
                profile=profile,
                status=state,
                active_task_title=task_map.get(profile.agent_id),
                claim_count=counters["claims"],
                evidence_count=counters["evidence"],
                retry_count=counters["retries"],
                last_activity_at=related[-1].timestamp if related else profile.created_at,
            )
        )

    final_json = await repository.get_report_json(run_id, "final")
    final_report = FinalReport.model_validate_json(final_json) if final_json else None
    metrics = RunMetrics(
        llm_call_count=sum(int(event.metadata.get("llm_calls", 0)) for event in events),
        web_search_count=sum(
            item["tool_name"] == "web_search" for item in tool_activity
        ),
        web_fetch_count=sum(item["tool_name"] == "web_fetch" for item in tool_activity),
        agent_count=len(states),
        task_count=len(tasks),
        retry_count=sum(event.event_type == EventType.TASK_RETRYING for event in events),
        claim_count=sum(item.claim_count for item in states),
        evidence_count=len(evidence),
        failed_task_count=sum(task.status == TaskStatus.FAILED for task in tasks),
    )
    return RunSnapshot(
        run=run,
        agents=states,
        tasks=tasks,
        events=events,
        handoffs=handoffs,
        evidence=[EvidenceSummary.from_evidence(item) for item in evidence],
        tool_activity=tool_activity,
        metrics=metrics,
        final_report=final_report,
        error=run.error_message,
    )


async def build_agent_details(
    repository: HiveMindRepository, run_id: str, agent_id: str
) -> AgentDetails | None:
    snapshot = await build_snapshot(repository, run_id)
    if snapshot is None:
        return None
    state = next((item for item in snapshot.agents if item.profile.agent_id == agent_id), None)
    if state is None:
        return None
    handoffs = await repository.list_handoffs_for_agent(run_id, agent_id)
    reports = await repository.list_reports_for_agent(run_id, agent_id)
    if state.profile.kind.value in {"verifier", "qa"}:
        report_type = "verification" if state.profile.kind.value == "verifier" else "qa"
        report_json = await repository.get_report_json(run_id, report_type)
        if report_json:
            reports.append({"report_type": report_type, "data": json.loads(report_json)})
    return AgentDetails(
        agent=state.profile,
        current_status=state.status,
        tasks=[task for task in snapshot.tasks if task.agent_id == agent_id],
        incoming_handoffs=[item for item in handoffs if item.target_agent_id == agent_id],
        outgoing_handoffs=[item for item in handoffs if item.source_agent_id == agent_id],
        status_history=[event for event in snapshot.events if event.agent_id == agent_id],
        tool_calls=[item for item in snapshot.tool_activity if item["agent_id"] == agent_id],
        evidence=[item for item in snapshot.evidence if item.agent_id == agent_id],
        reports=reports,
    )


def _agent_state(default: AgentStatus, events: list) -> AgentStatus:
    status = default
    for event in events:
        candidate = event.metadata.get("status")
        if candidate:
            with suppress(ValueError):
                status = AgentStatus(candidate)
        if event.event_type == EventType.AGENT_COMPLETED:
            status = AgentStatus.COMPLETED
        elif event.event_type == EventType.AGENT_FAILED:
            status = AgentStatus.FAILED
    return status


def _latest_active_tasks(tasks: list) -> dict[str, str]:
    active = {
        TaskStatus.PENDING,
        TaskStatus.QUEUED,
        TaskStatus.RUNNING,
        TaskStatus.WAITING_FOR_TOOL,
        TaskStatus.WAITING_FOR_CHILDREN,
        TaskStatus.RETRYING,
    }
    result: dict[str, str] = {}
    for task in tasks:
        if task.status in active:
            result[task.agent_id] = task.title
    return result
