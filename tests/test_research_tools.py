"""Runtime web research tests use registered stubs, never the live internet."""

from pydantic import BaseModel

from hivemind.config import Settings
from hivemind.events import EventBus
from hivemind.providers.fake_provider import FakeLLMProvider
from hivemind.runtime import (
    HiveMindRuntime,
    _current_search_query,
    _disambiguate_worker_role_keys,
)
from hivemind.schemas import (
    AgentKind,
    Claim,
    EventType,
    FetchedPage,
    ManagerReport,
    SearchResult,
    ToolMetadata,
    WorkerPlan,
    WorkerReport,
    WorkerSpec,
    utc_now,
)
from hivemind.tools import ToolError, ToolRegistry


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


def fallback_registry() -> ToolRegistry:
    async def search(*, query: str, max_results: int) -> list[SearchResult]:
        return [
            SearchResult(
                title="Unavailable result",
                url="https://example.com/unavailable",
                snippet=f"First snippet for {query}",
            ),
            SearchResult(
                title="Available result",
                url="https://example.com/available",
                snippet=f"Second snippet for {query}",
            ),
        ][:max_results]

    async def fetch(*, url: str) -> FetchedPage:
        if url.endswith("/unavailable"):
            raise ToolError("The first result rejected automated fetching.")
        return FetchedPage(
            url=url,
            title="Available source",
            content_type="text/html",
            excerpt="A bounded excerpt from the second result.",
        )

    registry = ToolRegistry()
    allowed = {AgentKind.WORKER, AgentKind.VERIFIER}
    registry.register(
        ToolMetadata(
            name="web_search",
            description="Test search with a blocked first result",
            allowed_agent_kinds=allowed,
        ),
        search,
    )
    registry.register(
        ToolMetadata(
            name="web_fetch",
            description="Test fetch with a usable second result",
            allowed_agent_kinds=allowed,
        ),
        fetch,
    )
    return registry


def test_worker_role_collisions_are_repaired_before_agent_creation() -> None:
    workers = [
        WorkerSpec(
            role_key="data",
            name=name,
            role="Researcher",
            objective="Collect evidence.",
            rationale_summary="Focused coverage.",
        )
        for name in ("Model Collector", "Release Tracker", "Capability Analyst")
    ]
    plan = WorkerPlan(
        department_role_key="data",
        workers=workers,
        rationale_summary="Cover the model landscape.",
    )

    repaired, reductions = _disambiguate_worker_role_keys(
        plan,
        reserved_role_keys={"ceo", "data"},
    )

    role_keys = [worker.role_key for worker in repaired.workers]
    assert role_keys == ["model-collector", "release-tracker", "capability-analyst"]
    assert len(set(role_keys)) == len(workers)
    assert reductions


def test_current_requests_replace_stale_search_years() -> None:
    current_year = str(utc_now().year)

    assert _current_search_query(
        "LLM releases 2023-2024", "What are the latest LLM models?"
    ) == f"LLM releases {current_year}"
    assert _current_search_query(
        "LLM releases 2023-2024", "Summarize LLM releases during 2023-2024"
    ) == "LLM releases 2023-2024"


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


async def test_runtime_fetches_the_next_search_result_when_the_first_is_unavailable(
    tmp_path,
) -> None:
    settings = Settings(
        HIVEMIND_PROVIDER="fake",
        HIVEMIND_ENABLE_WEB=True,
        HIVEMIND_DB_PATH=tmp_path / "hivemind.db",
        HIVEMIND_RUNS_DIR=tmp_path / "runs",
        HIVEMIND_MAX_RESEARCH_ROUNDS=1,
    )
    bus = EventBus()

    result = await HiveMindRuntime(
        settings,
        WebAwareFakeProvider(),
        bus,
        tool_registry=fallback_registry(),
    ).run("Research a software architecture")

    assert any(
        item.url == "https://example.com/available" and item.source_type == "web_page"
        for item in result.evidence
    )
    assert any(
        item.event_type == EventType.TOOL_FAILED and item.metadata.get("tool") == "web_fetch"
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
