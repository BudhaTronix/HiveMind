"""Enforce Python-side limits on organizations proposed by language models.

The governor is deliberately deterministic: it sorts proposals by priority, removes
duplicate role keys, clamps counts, and shortens search-query lists. A model can suggest a
large company, but it cannot grant itself more agents, rounds, or calls.
"""

from __future__ import annotations

from dataclasses import dataclass

from hivemind.config import Settings
from hivemind.schemas import CompanyPlan, GovernorLimits, WorkerPlan


@dataclass(frozen=True, slots=True)
class GovernorDecision:
    """A validated plan plus public explanations of any reductions."""

    plan: CompanyPlan | WorkerPlan
    reductions: tuple[str, ...] = ()


class Governor:
    """Validate CEO and manager proposals against fixed runtime limits."""

    def __init__(self, limits: GovernorLimits) -> None:
        self.limits = limits

    @classmethod
    def from_settings(cls, settings: Settings) -> Governor:
        """Construct limits from the same validated settings used by the CLI."""

        return cls(
            GovernorLimits(
                max_managers=settings.max_managers,
                max_workers_per_manager=settings.max_workers_per_manager,
                max_total_agents=settings.max_total_agents,
                max_concurrent_llm_calls=settings.max_concurrent_llm_calls,
                max_concurrent_web_requests=settings.max_concurrent_web_requests,
                max_research_rounds=settings.max_research_rounds,
                max_search_queries_per_worker=settings.max_search_queries_per_worker,
                max_retries_per_task=settings.max_retries,
                max_runtime_seconds=settings.max_runtime_seconds,
            )
        )

    def validate_company_plan(self, plan: CompanyPlan) -> GovernorDecision:
        """Keep the highest-priority unique departments within the manager limit."""

        departments = _unique_by_role_key(plan.departments)
        allowed = sorted(departments, key=lambda item: item.priority, reverse=True)[
            : self.limits.max_managers
        ]
        reductions: list[str] = []
        if len(allowed) < len(plan.departments):
            reductions.append(
                f"CEO requested {len(plan.departments)} departments; governor allowed "
                f"{len(allowed)}."
            )
        return GovernorDecision(
            plan=plan.model_copy(update={"departments": allowed}),
            reductions=tuple(reductions),
        )

    def validate_worker_plan(
        self, plan: WorkerPlan, *, current_organization_agents: int
    ) -> GovernorDecision:
        """Clamp workers, total organization size, duplicate roles, and search queries."""

        unique = _unique_by_role_key(plan.workers)
        remaining = max(0, self.limits.max_total_agents - current_organization_agents)
        allowed_count = min(self.limits.max_workers_per_manager, remaining)
        selected = sorted(unique, key=lambda item: item.priority, reverse=True)[:allowed_count]
        selected = [
            item.model_copy(
                update={
                    "search_queries": item.search_queries[
                        : self.limits.max_search_queries_per_worker
                    ]
                }
            )
            for item in selected
        ]
        reductions: list[str] = []
        if len(selected) < len(plan.workers):
            reductions.append(
                f"Manager requested {len(plan.workers)} workers; governor allowed {len(selected)}."
            )
        if any(
            len(item.search_queries) > self.limits.max_search_queries_per_worker
            for item in plan.workers
        ):
            reductions.append(
                "Search queries were reduced to "
                f"{self.limits.max_search_queries_per_worker} per worker."
            )
        return GovernorDecision(
            plan=plan.model_copy(update={"workers": selected}),
            reductions=tuple(reductions),
        )


def _unique_by_role_key(items: list[object]) -> list[object]:
    """Keep the first proposal for each stable role key."""

    seen: set[str] = set()
    result = []
    for item in items:
        role_key = str(item.role_key)  # type: ignore[attr-defined]
        if role_key not in seen:
            seen.add(role_key)
            result.append(item)
    return result
