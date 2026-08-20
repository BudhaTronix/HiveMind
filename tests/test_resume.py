"""Resume uses completed checkpoints rather than repeating model tasks."""

import asyncio

import aiosqlite
from typer.testing import CliRunner

from hivemind.cli import app
from hivemind.config import Settings
from hivemind.events import EventBus
from hivemind.persistence import ArtifactStore, HiveMindRepository
from hivemind.providers.fake_provider import FakeLLMProvider
from hivemind.runtime import HiveMindRuntime

runner = CliRunner()


async def test_completed_tasks_are_not_repeated_during_resume(tmp_path) -> None:
    settings = Settings(
        HIVEMIND_PROVIDER="fake",
        HIVEMIND_ENABLE_WEB=False,
        HIVEMIND_DB_PATH=tmp_path / "hivemind.db",
        HIVEMIND_RUNS_DIR=tmp_path / "runs",
    )
    repository = HiveMindRepository(settings.db_path)
    provider = FakeLLMProvider()
    runtime = HiveMindRuntime(
        settings,
        provider,
        EventBus(),
        repository=repository,
        artifacts=ArtifactStore(settings.runs_dir),
    )
    result = await runtime.run("Research a software architecture")
    calls_after_run = provider.call_count
    tasks_after_run = await repository.list_tasks(result.run.run_id)

    resumed = await runtime.resume(result.run.run_id)
    tasks_after_resume = await repository.list_tasks(result.run.run_id)

    assert resumed.final_report == result.final_report
    assert provider.call_count == calls_after_run
    assert len(tasks_after_resume) == len(tasks_after_run)


async def test_stage_resume_reuses_completed_task_outputs(tmp_path) -> None:
    settings = Settings(
        HIVEMIND_PROVIDER="fake",
        HIVEMIND_ENABLE_WEB=False,
        HIVEMIND_DB_PATH=tmp_path / "hivemind.db",
        HIVEMIND_RUNS_DIR=tmp_path / "runs",
    )
    repository = HiveMindRepository(settings.db_path)
    provider = FakeLLMProvider()
    bus = EventBus()
    runtime = HiveMindRuntime(settings, provider, bus, repository=repository)
    result = await runtime.run("Research a software architecture")
    initial_calls = provider.call_count
    initial_tasks = await repository.list_tasks(result.run.run_id)
    # Simulate interruption before the aggregate checkpoint became durable. Individual
    # validated task outputs remain usable by the stage-level resume path.
    async with aiosqlite.connect(settings.db_path) as db:
        await db.execute(
            "DELETE FROM reports WHERE run_id = ? AND report_type = ?",
            (result.run.run_id, "checkpoint:completed"),
        )
        await db.commit()

    await runtime.resume(result.run.run_id)
    resumed_tasks = await repository.list_tasks(result.run.run_id)

    assert provider.call_count == initial_calls
    assert len(resumed_tasks) == len(initial_tasks)
    assert any(item.metadata.get("checkpoint_reused") for item in bus.events)


def test_status_command_reconstructs_saved_hierarchy(tmp_path, monkeypatch) -> None:
    settings = Settings(
        HIVEMIND_PROVIDER="fake",
        HIVEMIND_ENABLE_WEB=False,
        HIVEMIND_DB_PATH=tmp_path / "hivemind.db",
        HIVEMIND_RUNS_DIR=tmp_path / "runs",
    )

    async def prepare_run():
        repository = HiveMindRepository(settings.db_path)
        bus = EventBus()
        bus.subscribe(repository.save_event)
        return await HiveMindRuntime(settings, FakeLLMProvider(), bus, repository=repository).run(
            "Research a software architecture"
        )

    result = asyncio.run(prepare_run())
    monkeypatch.setenv("HIVEMIND_DB_PATH", str(settings.db_path))

    command = runner.invoke(app, ["status", result.run.run_id])

    assert command.exit_code == 0
    assert "CEO Agent" in command.stdout
    assert "COMPLETED" in command.stdout
