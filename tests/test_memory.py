"""Memory is scoped, ranked, curated, and independent of model weights."""

from hivemind.config import Settings
from hivemind.events import EventBus
from hivemind.memory import SimpleSQLiteMemoryStore
from hivemind.persistence import HiveMindRepository
from hivemind.providers.fake_provider import FakeLLMProvider
from hivemind.runtime import HiveMindRuntime
from hivemind.schemas import EventType, MemoryRecord, MemoryScope, MemoryType


def settings_for(tmp_path) -> Settings:
    return Settings(
        HIVEMIND_PROVIDER="fake",
        HIVEMIND_ENABLE_WEB=False,
        HIVEMIND_DB_PATH=tmp_path / "hivemind.db",
        HIVEMIND_RUNS_DIR=tmp_path / "runs",
    )


async def test_memory_retrieval_respects_project_and_agent_scopes(tmp_path) -> None:
    repository = HiveMindRepository(tmp_path / "hivemind.db")
    store = SimpleSQLiteMemoryStore(repository)
    visible = MemoryRecord(
        scope=MemoryScope.PROJECT,
        scope_id="project-a",
        text="German regulation requires a compliance review.",
        memory_type=MemoryType.RISK,
        confidence=0.9,
    )
    hidden_project = MemoryRecord(
        scope=MemoryScope.PROJECT,
        scope_id="project-b",
        text="German regulation differs for another project.",
        memory_type=MemoryType.FACT,
        confidence=1,
    )
    hidden_agent = MemoryRecord(
        scope=MemoryScope.AGENT,
        scope_id="agent-b",
        text="German regulation agent lesson.",
        memory_type=MemoryType.LESSON,
        confidence=1,
    )
    for memory in (visible, hidden_project, hidden_agent):
        await store.save(memory)

    results = await store.search(
        "German regulation",
        [(MemoryScope.PROJECT, "project-a"), (MemoryScope.AGENT, "agent-a")],
    )

    assert [item.memory_id for item in results] == [visible.memory_id]


async def test_fake_workflow_saves_only_curator_approved_candidates(tmp_path) -> None:
    settings = settings_for(tmp_path)
    repository = HiveMindRepository(settings.db_path)
    bus = EventBus()
    bus.subscribe(repository.save_event)

    result = await HiveMindRuntime(settings, FakeLLMProvider(), bus, repository=repository).run(
        "Research a startup market", project_id="curated-project"
    )
    memories = await repository.list_memories([(MemoryScope.PROJECT, "curated-project")])

    assert memories
    assert all(item.source_evidence_ids for item in memories)
    assert all(item.source_run_id == result.run.run_id for item in memories)
    assert any(item.event_type == EventType.MEMORY_SAVED for item in bus.events)


class NoEvidenceFakeProvider(FakeLLMProvider):
    name = "stub-no-evidence"


async def test_unsupported_candidates_are_not_written(tmp_path) -> None:
    settings = settings_for(tmp_path)
    repository = HiveMindRepository(settings.db_path)

    await HiveMindRuntime(
        settings, NoEvidenceFakeProvider(), EventBus(), repository=repository
    ).run("Research a startup market", project_id="unsupported-project")
    memories = await repository.list_memories([(MemoryScope.PROJECT, "unsupported-project")])

    assert memories == []


async def test_later_run_retrieves_project_memory_without_duplicating_it(tmp_path) -> None:
    settings = settings_for(tmp_path)
    repository = HiveMindRepository(settings.db_path)
    first_bus = EventBus()
    await HiveMindRuntime(settings, FakeLLMProvider(), first_bus, repository=repository).run(
        "Research a startup market", project_id="repeat-project"
    )
    first_memories = await repository.list_memories([(MemoryScope.PROJECT, "repeat-project")])
    second_bus = EventBus()

    await HiveMindRuntime(settings, FakeLLMProvider(), second_bus, repository=repository).run(
        "Research the same startup market", project_id="repeat-project"
    )
    second_memories = await repository.list_memories([(MemoryScope.PROJECT, "repeat-project")])

    assert len(second_memories) == len(first_memories)
    assert any(
        item.event_type == EventType.MEMORY_SEARCH_COMPLETED and item.metadata.get("count", 0) > 0
        for item in second_bus.events
    )
