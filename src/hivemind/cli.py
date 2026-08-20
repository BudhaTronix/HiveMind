"""Expose HiveMind as a beginner-friendly Typer command-line application.

Commands translate user choices into settings and runtime dependencies. They do not contain
agent logic, which keeps the path from the terminal to orchestration easy to follow.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from hivemind.config import load_settings
from hivemind.events import EventBus
from hivemind.providers import create_provider
from hivemind.providers.fake_provider import FakeLLMProvider
from hivemind.runtime import HiveMindRuntime
from hivemind.terminal_ui import TerminalRenderer

app = typer.Typer(
    name="hivemind",
    help="Learn multi-agent orchestration through a local-first research system.",
    no_args_is_help=True,
)
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
    plain: bool = typer.Option(False, "--plain", help="Print timestamped event lines."),
    explain: bool = typer.Option(False, "--explain", help="Show extra learning notes."),
) -> None:
    """Run the entire simulated workflow without a model server, API key, or internet."""

    asyncio.run(_demo(prompt, plain=plain, explain=explain))


@app.command()
def doctor(
    provider: str | None = typer.Option(
        None, "--provider", help="Check ollama, openai, or fake instead of the configured provider."
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


async def _demo(prompt: str, *, plain: bool, explain: bool) -> None:
    settings = load_settings(provider="fake", enable_web=False)
    provider = FakeLLMProvider()
    event_bus = EventBus()
    renderer = TerminalRenderer(console=console, plain=plain, explain=explain)
    event_bus.subscribe(renderer.handle)
    renderer.start(
        prompt=prompt,
        provider=provider.name,
        model=provider.model,
        max_rounds=settings.max_research_rounds,
    )
    try:
        result = await HiveMindRuntime(settings, provider, event_bus).run(prompt)
    finally:
        renderer.stop()
    renderer.show_report(result.final_report)


async def _doctor_checks(settings: object) -> list[DoctorCheck]:
    """Run setup checks without making billable model calls."""

    # This import is local to keep CLI startup and the beginner-facing file compact.
    from hivemind.config import Settings

    assert isinstance(settings, Settings)
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
    checks.append(
        DoctorCheck(
            "Web search",
            "PASS" if importlib.util.find_spec("ddgs") else "FAIL",
            "ddgs is installed" if importlib.util.find_spec("ddgs") else "Install ddgs",
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
