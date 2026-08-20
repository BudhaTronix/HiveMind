"""SQLite and portable artifacts must describe the same completed run."""

from hivemind.config import Settings
from hivemind.events import EventBus
from hivemind.persistence import ArtifactStore, HiveMindRepository, JsonlEventSink
from hivemind.providers.fake_provider import FakeLLMProvider
from hivemind.runtime import HiveMindRuntime
from hivemind.schemas import RunStage


async def test_run_persists_state_events_tasks_and_artifacts(tmp_path) -> None:
    settings = Settings(
        HIVEMIND_PROVIDER="fake",
        HIVEMIND_ENABLE_WEB=False,
        HIVEMIND_DB_PATH=tmp_path / "data" / "hivemind.db",
        HIVEMIND_RUNS_DIR=tmp_path / "runs",
    )
    repository = HiveMindRepository(settings.db_path)
    artifacts = ArtifactStore(settings.runs_dir)
    bus = EventBus()
    bus.subscribe(repository.save_event)
    bus.subscribe(JsonlEventSink(artifacts))

    result = await HiveMindRuntime(
        settings,
        FakeLLMProvider(),
        bus,
        repository=repository,
        artifacts=artifacts,
    ).run("Research a startup market", project_id="persistence-test")

    saved = await repository.get_run(result.run.run_id)
    tasks = await repository.list_tasks(result.run.run_id)
    events = await repository.list_events(result.run.run_id)
    expected = {
        "user_prompt.txt",
        "plan.json",
        "events.jsonl",
        "evidence.json",
        "verification.json",
        "qa_report.json",
        "final_report.json",
        "final_report.md",
        "run_summary.json",
    }
    assert saved and saved.stage == RunStage.COMPLETED
    assert tasks and all(item.status.value == "completed" for item in tasks)
    assert events[-1].event_type.value == "run_completed"
    assert expected <= {item.name for item in artifacts.run_dir(result.run.run_id).iterdir()}


async def test_registry_reuses_stable_project_roles(tmp_path) -> None:
    settings = Settings(
        HIVEMIND_PROVIDER="fake",
        HIVEMIND_ENABLE_WEB=False,
        HIVEMIND_DB_PATH=tmp_path / "hivemind.db",
        HIVEMIND_RUNS_DIR=tmp_path / "runs",
    )
    repository = HiveMindRepository(settings.db_path)
    first = await HiveMindRuntime(
        settings, FakeLLMProvider(), EventBus(), repository=repository
    ).run("Research a startup market", project_id="stable-project")
    second = await HiveMindRuntime(
        settings, FakeLLMProvider(), EventBus(), repository=repository
    ).run("Research another startup market", project_id="stable-project")

    first_ceo = next(item for item in first.agents if item.role_key == "ceo")
    second_ceo = next(item for item in second.agents if item.role_key == "ceo")
    assert first_ceo.agent_id == second_ceo.agent_id
