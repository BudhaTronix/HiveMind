"""Concurrent worker failures must remain isolated from successful siblings."""

from hivemind.config import Settings
from hivemind.events import EventBus
from hivemind.providers.fake_provider import FakeLLMProvider
from hivemind.runtime import HiveMindRuntime
from hivemind.schemas import EventType, RunStage


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
