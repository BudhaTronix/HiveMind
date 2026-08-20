"""Runtime web research tests use registered stubs, never the live internet."""

from hivemind.config import Settings
from hivemind.events import EventBus
from hivemind.providers.fake_provider import FakeLLMProvider
from hivemind.runtime import HiveMindRuntime
from hivemind.schemas import (
    AgentKind,
    EventType,
    FetchedPage,
    SearchResult,
    ToolMetadata,
)
from hivemind.tools import ToolRegistry


class WebAwareFakeProvider(FakeLLMProvider):
    name = "stub-real-provider"


async def fake_search(*, query: str, max_results: int) -> list[SearchResult]:
    return [
        SearchResult(
            title=f"Source for {query}",
            url="https://example.com/research",
            snippet="A bounded search snippet.",
        )
    ]


async def fake_fetch(*, url: str) -> FetchedPage:
    return FetchedPage(
        url=url,
        title="Fetched source",
        content_type="text/html",
        excerpt="A bounded fetched excerpt.",
    )


def fake_registry() -> ToolRegistry:
    registry = ToolRegistry()
    allowed = {AgentKind.WORKER, AgentKind.VERIFIER}
    registry.register(
        ToolMetadata(
            name="web_search",
            description="Test search",
            allowed_agent_kinds=allowed,
        ),
        fake_search,
    )
    registry.register(
        ToolMetadata(
            name="web_fetch",
            description="Test fetch",
            allowed_agent_kinds=allowed,
        ),
        fake_fetch,
    )
    return registry


async def test_runtime_turns_search_and_fetch_results_into_evidence(tmp_path) -> None:
    settings = Settings(
        HIVEMIND_PROVIDER="fake",
        HIVEMIND_ENABLE_WEB=True,
        HIVEMIND_DB_PATH=tmp_path / "hivemind.db",
        HIVEMIND_RUNS_DIR=tmp_path / "runs",
    )
    bus = EventBus()

    result = await HiveMindRuntime(
        settings,
        WebAwareFakeProvider(),
        bus,
        tool_registry=fake_registry(),
    ).run("Research a software architecture")

    assert result.evidence
    assert all(item.url == "https://example.com/research" for item in result.evidence)
    assert all(item.source_type == "web_page" for item in result.evidence)
    assert result.final_report.sources
    assert any(
        item.event_type == EventType.TOOL_COMPLETED and item.metadata.get("tool") == "web_fetch"
        for item in bus.events
    )
