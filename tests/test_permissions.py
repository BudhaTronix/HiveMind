"""Models cannot grant themselves tools or bypass approval requirements."""

import pytest

from hivemind.schemas import AgentKind, ToolMetadata
from hivemind.tools import ApprovalGate, ToolRegistry, build_default_tool_registry


async def test_worker_cannot_use_manager_only_tool() -> None:
    calls = 0

    async def handler() -> str:
        nonlocal calls
        calls += 1
        return "result"

    registry = ToolRegistry()
    registry.register(
        ToolMetadata(
            name="manager_tool",
            description="Manager only",
            allowed_agent_kinds={AgentKind.MANAGER},
        ),
        handler,
    )

    with pytest.raises(PermissionError, match="may not use"):
        await registry.execute("manager_tool", agent_kind=AgentKind.WORKER)
    assert calls == 0


async def test_approval_required_tool_does_not_execute_without_approval() -> None:
    calls = 0

    async def handler() -> str:
        nonlocal calls
        calls += 1
        return "side effect"

    registry = ToolRegistry()
    registry.register(
        ToolMetadata(
            name="future_side_effect",
            description="Demonstrate a consequential future tool",
            allowed_agent_kinds={AgentKind.CEO},
            side_effect=True,
            requires_approval=True,
        ),
        handler,
    )

    with pytest.raises(PermissionError, match="requires approval"):
        await registry.execute("future_side_effect", agent_kind=AgentKind.CEO)
    assert calls == 0


class AllowingGate(ApprovalGate):
    async def request_approval(self, metadata, *, agent_kind, arguments) -> bool:
        return True


async def test_explicit_approval_gate_can_allow_future_tool() -> None:
    registry = ToolRegistry(approval_gate=AllowingGate())

    async def handler() -> str:
        return "approved"

    registry.register(
        ToolMetadata(
            name="approved_tool",
            description="Approved side effect",
            allowed_agent_kinds={AgentKind.CEO},
            side_effect=True,
            requires_approval=True,
        ),
        handler,
    )

    assert await registry.execute("approved_tool", agent_kind=AgentKind.CEO) == "approved"


async def test_default_evidence_tool_is_registered_and_role_checked() -> None:
    registry = build_default_tool_registry()
    evidence = {"evidence_1": {"title": "Saved source"}}

    result = await registry.execute(
        "evidence_read",
        agent_kind=AgentKind.VERIFIER,
        evidence_by_id=evidence,
        evidence_id="evidence_1",
    )

    assert result == evidence["evidence_1"]
    with pytest.raises(PermissionError, match="may not use"):
        await registry.execute(
            "evidence_read",
            agent_kind=AgentKind.WORKER,
            evidence_by_id=evidence,
            evidence_id="evidence_1",
        )
