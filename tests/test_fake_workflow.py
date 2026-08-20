"""The most important smoke test: the complete demo is local and deterministic."""

from hivemind.config import Settings
from hivemind.events import EventBus
from hivemind.providers.fake_provider import FakeLLMProvider
from hivemind.runtime import HiveMindRuntime
from hivemind.schemas import EventType, RunStage


async def test_fake_provider_completes_dynamic_workflow(tmp_path) -> None:
    settings = Settings(
        HIVEMIND_PROVIDER="fake",
        HIVEMIND_ENABLE_WEB=False,
        HIVEMIND_DB_PATH=tmp_path / "hivemind.db",
        HIVEMIND_RUNS_DIR=tmp_path / "runs",
    )
    provider = FakeLLMProvider()
    bus = EventBus()

    result = await HiveMindRuntime(settings, provider, bus).run(
        "Should a startup enter an EV charging market?"
    )

    assert result.run.stage == RunStage.COMPLETED
    assert {item.role_key for item in result.plan.departments} == {
        "market-research",
        "regulation",
        "competition",
    }
    assert any(item.parent_agent_id for item in result.agents)
    assert result.final_report.sources
    assert bus.events[-1].event_type == EventType.RUN_COMPLETED


async def test_fake_provider_changes_organization_for_technical_prompt(tmp_path) -> None:
    settings = Settings(
        HIVEMIND_PROVIDER="fake",
        HIVEMIND_ENABLE_WEB=False,
        HIVEMIND_DB_PATH=tmp_path / "hivemind.db",
        HIVEMIND_RUNS_DIR=tmp_path / "runs",
    )

    result = await HiveMindRuntime(settings, FakeLLMProvider(), EventBus()).run(
        "Research a secure software architecture"
    )

    assert result.plan.departments[0].role_key == "technical-feasibility"
