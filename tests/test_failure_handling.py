"""Concurrent worker failures must remain isolated from successful siblings."""

import pytest

from hivemind.config import Settings
from hivemind.events import EventBus
from hivemind.providers.base import ProviderError
from hivemind.providers.fake_provider import FakeLLMProvider
from hivemind.runtime import HiveMindRuntime
from hivemind.schemas import EventType, RunStage, WorkerPlan


def _settings(tmp_path, *, concurrency: int = 3) -> Settings:
    return Settings(
        HIVEMIND_PROVIDER="fake",
        HIVEMIND_ENABLE_WEB=False,
        HIVEMIND_DB_PATH=tmp_path / "hivemind.db",
        HIVEMIND_RUNS_DIR=tmp_path / "runs",
        HIVEMIND_MAX_CONCURRENT_LLM_CALLS=concurrency,
    )


async def test_llm_semaphore_limits_concurrency(tmp_path) -> None:
    provider = FakeLLMProvider(delay_seconds=0.01)

    await HiveMindRuntime(_settings(tmp_path, concurrency=2), provider, EventBus()).run(
        "Research a software architecture"
    )

    assert provider.max_active_calls == 2


async def test_one_worker_failure_keeps_partial_department_and_run(tmp_path) -> None:
    provider = FakeLLMProvider(fail_roles={"market-research-demand"})
    bus = EventBus()

    result = await HiveMindRuntime(_settings(tmp_path), provider, bus).run(
        "Research a startup market"
    )

    market = next(
        item for item in result.manager_reports if item.department_name == "Market Research"
    )
    assert result.run.stage == RunStage.COMPLETED
    assert len(market.merged_claims) == 1
    assert market.research_gaps == ["1 worker task(s) failed."]
    assert any(item.event_type == EventType.AGENT_FAILED for item in bus.events)


class AllManagerPlansFailProvider(FakeLLMProvider):
    async def generate_structured(self, schema, system_prompt, user_prompt):
        if schema is WorkerPlan:
            raise ProviderError("Local generation timed out.", retryable=False)
        return await super().generate_structured(schema, system_prompt, user_prompt)


async def test_all_manager_plan_failures_fail_instead_of_producing_empty_report(tmp_path) -> None:
    bus = EventBus()
    runtime = HiveMindRuntime(_settings(tmp_path), AllManagerPlansFailProvider(), bus)

    with pytest.raises(ProviderError, match="All manager planning requests failed"):
        await runtime.run("Research a startup market")

    assert runtime._active_run is not None
    assert runtime._active_run.stage == RunStage.FAILED
    assert any(item.event_type == EventType.RUN_FAILED for item in bus.events)
