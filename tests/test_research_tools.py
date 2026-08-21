"""Runtime web research tests use registered stubs, never the live internet."""

from pydantic import BaseModel

from hivemind.config import Settings
from hivemind.events import EventBus
from hivemind.providers.fake_provider import FakeLLMProvider
from hivemind.runtime import HiveMindRuntime
from hivemind.schemas import (
    AgentKind,
    Claim,
    EventType,
    FetchedPage,
    ManagerReport,
    SearchResult,
    ToolMetadata,
    WorkerReport,
)
from hivemind.tools import ToolRegistry


class WebAwareFakeProvider(FakeLLMProvider):
    name = "stub-real-provider"


class AliasAndDroppingManagerProvider(WebAwareFakeProvider):
    async def generate_structured(
        self,
        schema: type[BaseModel],
        system_prompt: str,
        user_prompt: str,
    ) -> BaseModel:
        result = await super().generate_structured(schema, system_prompt, user_prompt)
        if schema is WorkerReport:
            return WorkerReport(
                summary="One grounded finding.",
                claims=[
                    Claim(
                        text="The supplied source supports this finding.",
                        confidence=0.8,
                        evidence_ids=["evidence_0", "evidence_never_supplied"],
                    )
                ],
            )
        if schema is ManagerReport:
            return result.model_copy(update={"merged_claims": []})
        return result


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


async def test_runtime_resolves_evidence_aliases_and_preserves_worker_claims(tmp_path) -> None:
    settings = Settings(
        HIVEMIND_PROVIDER="fake",
        HIVEMIND_ENABLE_WEB=True,
        HIVEMIND_DB_PATH=tmp_path / "hivemind.db",
        HIVEMIND_RUNS_DIR=tmp_path / "runs",
        HIVEMIND_MAX_RESEARCH_ROUNDS=1,
    )

    result = await HiveMindRuntime(
        settings,
        AliasAndDroppingManagerProvider(),
        EventBus(),
        tool_registry=fake_registry(),
    ).run("Research a software architecture")

    evidence_ids = {item.evidence_id for item in result.evidence}
    claims = [claim for report in result.manager_reports for claim in report.merged_claims]
    assert claims
    assert all(claim.evidence_ids for claim in claims)
    assert all(set(claim.evidence_ids) <= evidence_ids for claim in claims)
    assert all("evidence_never_supplied" not in claim.evidence_ids for claim in claims)
    assert result.final_report.sources
    assert all(source.evidence_id in evidence_ids for source in result.final_report.sources)
