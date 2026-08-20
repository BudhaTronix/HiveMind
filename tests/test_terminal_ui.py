"""The terminal view must be reconstructible from public events alone."""

from io import StringIO

from rich.console import Console

from hivemind.schemas import AgentStatus, EventType, HiveEvent
from hivemind.terminal_ui import DashboardState, TerminalRenderer


def test_dashboard_reconstructs_parent_child_status_and_counts() -> None:
    state = DashboardState(prompt="Research", provider="fake", model="demo", max_rounds=2)
    ceo = HiveEvent(
        event_type=EventType.AGENT_SPAWNED,
        run_id="run_test",
        round_number=1,
        agent_id="ceo",
        message="Created CEO",
        metadata={"name": "CEO", "kind": "ceo", "status": "planning"},
    )
    worker = HiveEvent(
        event_type=EventType.AGENT_SPAWNED,
        run_id="run_test",
        round_number=1,
        agent_id="worker",
        parent_agent_id="ceo",
        message="Created worker",
        metadata={"name": "Worker", "kind": "worker", "status": "running"},
    )
    completed = HiveEvent(
        event_type=EventType.AGENT_COMPLETED,
        run_id="run_test",
        round_number=1,
        agent_id="worker",
        message="Worker completed",
        metadata={
            "status": AgentStatus.COMPLETED.value,
            "claims": 2,
            "evidence": 3,
            "claims_added": 2,
            "evidence_added": 3,
        },
    )

    for event in (ceo, worker, completed):
        state.apply(event)

    assert state.agents["worker"].parent_agent_id == "ceo"
    assert state.agents["worker"].status == "completed"
    assert state.claim_count == 2
    assert state.evidence_count == 3


async def test_plain_explain_mode_outputs_status_and_learning_note() -> None:
    stream = StringIO()
    renderer = TerminalRenderer(
        console=Console(file=stream, force_terminal=False), plain=True, explain=True
    )
    renderer.start(prompt="Research", provider="fake", model="demo", max_rounds=2)
    await renderer.handle(
        HiveEvent(
            event_type=EventType.PLAN_VALIDATED,
            run_id="run_test",
            message="Governor approved the plan.",
            metadata={"learning_note": "Python creates approved agents."},
        )
    )

    output = stream.getvalue()
    assert "[PLAN_VALIDATED] Governor approved the plan." in output
    assert "Learning: Python creates approved agents." in output
