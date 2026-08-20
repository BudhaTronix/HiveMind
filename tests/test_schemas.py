"""Tests for the structured boundaries that keep Python in control."""

import pytest
from pydantic import ValidationError

from hivemind.schemas import DepartmentSpec, WorkerSpec


def test_role_keys_are_machine_safe() -> None:
    with pytest.raises(ValidationError):
        DepartmentSpec(
            role_key="Not a safe key",
            name="Research",
            manager_name="Manager",
            objective="Research a topic",
            rationale_summary="Needed for coverage",
        )


def test_worker_search_queries_are_bounded_by_schema() -> None:
    with pytest.raises(ValidationError):
        WorkerSpec(
            role_key="researcher",
            name="Researcher",
            role="Research",
            objective="Find evidence",
            research_questions=[],
            search_queries=["one", "two", "three", "four"],
            rationale_summary="Focused work",
        )
