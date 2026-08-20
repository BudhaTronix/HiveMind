"""Expose HiveMind as a beginner-friendly Typer command-line application.

Commands assemble configuration, providers, persistence, events, and presentation. Agent
logic remains in the runtime so every command is a thin, testable entry point.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sqlite3
import sys
from collections.abc import Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from hivemind.config import Settings, load_settings
from hivemind.events import EventBus
from hivemind.memory import SimpleSQLiteMemoryStore
from hivemind.persistence import ArtifactStore, HiveMindRepository, JsonlEventSink
from hivemind.providers import create_provider
from hivemind.providers.base import ProviderError
from hivemind.runtime import HiveMindRuntime, RuntimeResult
from hivemind.schemas import MemoryScope
from hivemind.terminal_ui import TerminalRenderer

app = typer.Typer(
    name="hivemind",
    help="Learn multi-agent orchestration through a local-first research system.",
    no_args_is_help=True,
)
runs_app = typer.Typer(help="Inspect saved research runs.", no_args_is_help=True)
agents_app = typer.Typer(help="Inspect stable project agent profiles.", no_args_is_help=True)
memories_app = typer.Typer(help="Inspect curated durable memories.", no_args_is_help=True)
app.add_typer(runs_app, name="runs")
app.add_typer(agents_app, name="agents")
app.add_typer(memories_app, name="memories")
console = Console()


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    """One concise health result displayed by ``hivemind doctor``."""

    name: str
    status: str
    detail: str


@app.callback()
def main() -> None:
    """Run HiveMind commands."""


@app.command()
def demo(
    prompt: str = typer.Argument(
        "Should a startup enter the German EV charging market?",
        help="A research prompt for the offline simulation.",
    ),
    project: str = typer.Option("demo-project", "--project", help="Project memory scope."),
    plain: bool = typer.Option(False, "--plain", help="Print timestamped event lines."),
    explain: bool = typer.Option(False, "--explain", help="Show extra learning notes."),
    debug: bool = typer.Option(False, "--debug", help="Show tracebacks for development."),
) -> None:
    """Run the complete workflow without a model server, API key, or internet."""

    settings = load_settings(provider="fake", enable_web=False)
    _run_async(
        _execute_new_run(
            settings,
            prompt=prompt,
            project=project,
            plain=plain,
            explain=explain,
        ),
        debug=debug,
    )


@app.command("run")
def run_research(
    prompt: str = typer.Argument(..., help="The research question for the CEO."),
    project: str = typer.Option("default-project", "--project", help="Project memory scope."),
    provider: str | None = typer.Option(None, "--provider", help="ollama or openai"),
    model: str | None = typer.Option(None, "--model", help="Override the selected model."),
    no_web: bool = typer.Option(False, "--no-web", help="Disable all web research."),
    plain: bool = typer.Option(False, "--plain", help="Print timestamped event lines."),
    explain: bool = typer.Option(False, "--explain", help="Show extra learning notes."),
    max_managers: int | None = typer.Option(None, "--max-managers", min=1, max=10),
    max_workers: int | None = typer.Option(None, "--max-workers", min=1, max=10),
    max_rounds: int | None = typer.Option(None, "--max-rounds", min=1, max=5),
    max_concurrent: int | None = typer.Option(None, "--max-concurrent", min=1, max=20),
    debug: bool = typer.Option(False, "--debug", help="Show tracebacks for development."),
) -> None:
    """Run real research with the configured Ollama or optional OpenAI provider."""

    selected = provider or load_settings().provider
    if selected not in {"ollama", "openai", "fake"}:
        raise typer.BadParameter("provider must be ollama, openai, or fake")
    overrides: dict[str, object] = {
        "provider": selected,
        "enable_web": not no_web,
        "max_managers": max_managers,
        "max_workers_per_manager": max_workers,
        "max_research_rounds": max_rounds,
        "max_concurrent_llm_calls": max_concurrent,
    }
    if model and selected == "openai":
        overrides["openai_model"] = model
    elif model:
        overrides["ollama_model"] = model
    settings = load_settings(**overrides)
    _run_async(
        _execute_new_run(
            settings,
            prompt=prompt,
            project=project,
            plain=plain,
            explain=explain,
        ),
        debug=debug,
    )


@app.command()
def resume(
    run_id: str = typer.Argument(..., help="Saved run identifier."),
    plain: bool = typer.Option(False, "--plain"),
    explain: bool = typer.Option(False, "--explain"),
    debug: bool = typer.Option(False, "--debug"),
) -> None:
    """Continue a saved run, reusing a completed checkpoint when available."""

    _run_async(
        _resume_run(run_id, plain=plain, explain=explain),
        debug=debug,
    )


@app.command()
def status(run_id: str = typer.Argument(..., help="Saved run identifier.")) -> None:
    """Reconstruct the latest organization and status after a process stops."""

    _run_async(_show_status(run_id), debug=False)


@runs_app.command("list")
def list_runs(limit: int = typer.Option(20, "--limit", min=1, max=200)) -> None:
    """List recently saved runs."""

    _run_async(_list_runs(limit), debug=False)


@agents_app.command("list")
def list_agents(
    project: str | None = typer.Option(None, "--project", help="Filter by project ID."),
) -> None:
    """List stable agent profiles and basic task history."""

    _run_async(_list_agents(project), debug=False)


@agents_app.command("show")
def show_agent(agent_id: str = typer.Argument(...)) -> None:
    """Show one agent profile."""

    _run_async(_show_agent(agent_id), debug=False)


@memories_app.command("list")
def list_memories(
    project: str = typer.Option(..., "--project", help="Project memory scope."),
) -> None:
    """List active memories approved for one project."""

    _run_async(_list_memories(project), debug=False)


@memories_app.command("search")
def search_memories(
    query: str = typer.Argument(..., help="Keywords to retrieve."),
    project: str = typer.Option(..., "--project", help="Project memory scope."),
) -> None:
    """Search project memory using the default transparent ranking."""

    _run_async(_search_memories(query, project), debug=False)


@app.command()
def doctor(
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="Check ollama, openai, or fake instead of the configured provider.",
    ),
    model: str | None = typer.Option(None, "--model", help="Override the model to check."),
) -> None:
    """Check local setup and print actionable pass, warning, and failure results."""

    if provider not in {None, "ollama", "openai", "fake"}:
        raise typer.BadParameter("provider must be ollama, openai, or fake")
    overrides: dict[str, object] = {"provider": provider}
    if model and provider == "openai":
        overrides["openai_model"] = model
    elif model:
        overrides["ollama_model"] = model
    settings = load_settings(**overrides)
    checks = asyncio.run(_doctor_checks(settings))
    table = Table(title="HiveMind doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")
    for check in checks:
        style = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}[check.status]
        table.add_row(check.name, f"[{style}]{check.status}[/]", check.detail)
    console.print(table)
    if any(item.status == "FAIL" for item in checks):
        raise typer.Exit(1)


async def _execute_new_run(
    settings: Settings,
    *,
    prompt: str,
    project: str,
    plain: bool,
    explain: bool,
) -> RuntimeResult:
    settings.ensure_directories()
    repository = HiveMindRepository(settings.db_path)
    artifacts = ArtifactStore(settings.runs_dir)
    provider = create_provider(settings)
    event_bus = EventBus()
    renderer = TerminalRenderer(console=console, plain=plain, explain=explain)
    renderer.start(
        prompt=prompt,
        provider=provider.name,
        model=provider.model,
        max_rounds=settings.max_research_rounds,
    )
    event_bus.subscribe(renderer.handle)
    event_bus.subscribe(repository.save_event)
    event_bus.subscribe(JsonlEventSink(artifacts))
    try:
        result = await HiveMindRuntime(
            settings,
            provider,
            event_bus,
            repository=repository,
            artifacts=artifacts,
        ).run(prompt, project_id=project)
    finally:
        renderer.stop()
    renderer.show_report(result.final_report)
    console.print(
        f"Run ID: [bold]{result.run.run_id}[/]  Artifacts: {artifacts.run_dir(result.run.run_id)}"
    )
    return result


async def _resume_run(run_id: str, *, plain: bool, explain: bool) -> RuntimeResult:
    base = load_settings()
    repository = HiveMindRepository(base.db_path)
    run = await repository.get_run(run_id)
    if run is None:
        raise ValueError(f"Run '{run_id}' was not found in {base.db_path}.")
    overrides: dict[str, object] = {"provider": run.provider}
    if run.provider == "openai":
        overrides["openai_model"] = run.model
    else:
        overrides["ollama_model"] = run.model
    settings = load_settings(**overrides)
    artifacts = ArtifactStore(settings.runs_dir)
    provider = create_provider(settings)
    event_bus = EventBus()
    renderer = TerminalRenderer(console=console, plain=plain, explain=explain)
    renderer.start(
        prompt=run.prompt,
        provider=run.provider,
        model=run.model,
        max_rounds=run.max_rounds,
    )
    event_bus.subscribe(renderer.handle)
    event_bus.subscribe(repository.save_event)
    event_bus.subscribe(JsonlEventSink(artifacts))
    try:
        result = await HiveMindRuntime(
            settings,
            provider,
            event_bus,
            repository=repository,
            artifacts=artifacts,
        ).resume(run_id)
    finally:
        renderer.stop()
    renderer.show_report(result.final_report)
    console.print(f"Resumed run: [bold]{run_id}[/]")
    return result


async def _show_status(run_id: str) -> None:
    settings = load_settings()
    repository = HiveMindRepository(settings.db_path)
    run = await repository.get_run(run_id)
    if run is None:
        raise ValueError(f"Run '{run_id}' was not found in {settings.db_path}.")
    events = await repository.list_events(run_id)
    TerminalRenderer(console=console).show_saved_run(run, events)


async def _list_runs(limit: int) -> None:
    repository = HiveMindRepository(load_settings().db_path)
    runs = await repository.list_runs(limit)
    table = Table(title="HiveMind runs")
    for title in ("Run ID", "Project", "Stage", "Round", "Created"):
        table.add_column(title)
    for run in runs:
        table.add_row(
            run.run_id,
            run.project_id,
            run.stage.value,
            f"{run.round_number}/{run.max_rounds}",
            run.created_at.astimezone().strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


async def _list_agents(project: str | None) -> None:
    repository = HiveMindRepository(load_settings().db_path)
    agents = await repository.list_agents(project)
    table = Table(title="HiveMind agents")
    for title in ("Agent ID", "Project", "Role", "Kind", "Status", "Completed/Failed"):
        table.add_column(title)
    for agent in agents:
        table.add_row(
            agent.agent_id,
            agent.project_id,
            agent.role_key,
            agent.kind.value,
            agent.status.value,
            f"{agent.tasks_completed}/{agent.tasks_failed}",
        )
    console.print(table)


async def _show_agent(agent_id: str) -> None:
    repository = HiveMindRepository(load_settings().db_path)
    agent = await repository.get_agent(agent_id)
    if agent is None:
        raise ValueError(f"Agent '{agent_id}' was not found.")
    console.print_json(agent.model_dump_json(indent=2))


async def _list_memories(project: str) -> None:
    repository = HiveMindRepository(load_settings().db_path)
    memories = await repository.list_memories([(MemoryScope.PROJECT, project)])
    _print_memories(memories, title=f"Project memories: {project}")


async def _search_memories(query: str, project: str) -> None:
    repository = HiveMindRepository(load_settings().db_path)
    memories = await SimpleSQLiteMemoryStore(repository).search(
        query, [(MemoryScope.PROJECT, project)], limit=10
    )
    _print_memories(memories, title=f"Memory search: {query}")


def _print_memories(memories: list[Any], *, title: str) -> None:
    table = Table(title=title)
    for heading in ("Memory ID", "Type", "Confidence", "Text", "Updated"):
        table.add_column(heading)
    for memory in memories:
        table.add_row(
            memory.memory_id,
            memory.memory_type.value,
            f"{memory.confidence:.0%}",
            memory.text,
            memory.updated_at.astimezone().strftime("%Y-%m-%d"),
        )
    console.print(table)


async def _doctor_checks(settings: Settings) -> list[DoctorCheck]:
    """Run setup checks without making billable model calls."""

    checks = [
        DoctorCheck(
            "Python",
            "PASS" if sys.version_info >= (3, 11) else "FAIL",
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        ),
        DoctorCheck(
            "Configuration",
            "PASS" if Path(".env").exists() else "WARN",
            ".env loaded" if Path(".env").exists() else "No .env; using defaults/environment",
        ),
    ]
    try:
        settings.ensure_directories()
        checks.append(DoctorCheck("Data directory", "PASS", str(settings.db_path.parent)))
        with sqlite3.connect(settings.db_path) as connection:
            connection.execute("SELECT 1").fetchone()
        checks.append(DoctorCheck("SQLite", "PASS", str(settings.db_path)))
    except (OSError, sqlite3.Error) as exc:
        checks.append(DoctorCheck("SQLite", "FAIL", str(exc)))
    has_ddgs = importlib.util.find_spec("ddgs") is not None
    checks.append(
        DoctorCheck(
            "Web search",
            "PASS" if has_ddgs else "FAIL",
            "ddgs is installed" if has_ddgs else "Install ddgs",
        )
    )
    if settings.memory_backend == "mem0":
        installed = importlib.util.find_spec("mem0") is not None
        checks.append(
            DoctorCheck(
                "Memory backend",
                "PASS" if installed else "FAIL",
                "Mem0 is installed" if installed else "Install with: pip install -e '.[mem0]'",
            )
        )
    else:
        checks.append(DoctorCheck("Memory backend", "PASS", "Simple SQLite memory selected"))
    selected = create_provider(settings)
    health = await selected.check_health()
    checks.append(
        DoctorCheck(
            f"Provider ({selected.name})",
            "PASS" if health.ok else "FAIL",
            health.message,
        )
    )
    return checks


def _run_async(operation: Coroutine[Any, Any, Any], *, debug: bool) -> Any:
    """Keep expected CLI failures concise unless the learner opts into tracebacks."""

    try:
        return asyncio.run(operation)
    except (ProviderError, ValueError, RuntimeError, OSError, sqlite3.Error) as exc:
        if debug:
            raise
        console.print(f"[red]HiveMind could not continue:[/] {exc}")
        raise typer.Exit(1) from None
