"""The governor, rather than the model, owns every organization limit."""

from hivemind.governor import Governor
from hivemind.schemas import (
    CompanyPlan,
    DepartmentSpec,
    GovernorLimits,
    WorkerPlan,
    WorkerSpec,
)


def _department(index: int) -> DepartmentSpec:
    return DepartmentSpec(
        role_key=f"department-{index}",
        name=f"Department {index}",
        manager_name=f"Manager {index}",
        objective="Research",
        rationale_summary="Coverage",
        priority=index,
    )


def _worker(index: int) -> WorkerSpec:
    return WorkerSpec(
        role_key=f"worker-{index}",
        name=f"Worker {index}",
        role="Researcher",
        objective="Research",
        research_questions=[],
        search_queries=["one", "two", "three"],
        rationale_summary="Focused task",
        priority=index,
    )


def test_governor_clamps_oversized_company_plan_by_priority() -> None:
    governor = Governor(GovernorLimits(max_managers=3))
    plan = CompanyPlan(
        objective="Research",
        departments=[_department(index) for index in range(7)],
        rationale_summary="Broad plan",
    )

    decision = governor.validate_company_plan(plan)

    assert isinstance(decision.plan, CompanyPlan)
    assert [item.priority for item in decision.plan.departments] == [6, 5, 4]
    assert decision.reductions


def test_governor_clamps_workers_queries_and_remaining_total() -> None:
    governor = Governor(
        GovernorLimits(
            max_workers_per_manager=3,
            max_total_agents=10,
            max_search_queries_per_worker=2,
        )
    )
    plan = WorkerPlan(
        department_role_key="department",
        workers=[_worker(index) for index in range(5)],
        rationale_summary="Worker plan",
    )

    decision = governor.validate_worker_plan(plan, current_organization_agents=8)

    assert isinstance(decision.plan, WorkerPlan)
    assert len(decision.plan.workers) == 2
    assert all(len(item.search_queries) == 2 for item in decision.plan.workers)
