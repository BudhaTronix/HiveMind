"""Expose HiveMind as a beginner-friendly Typer command-line application.

Commands translate user choices into settings and runtime dependencies. They do not contain
agent logic, which keeps the path from the terminal to orchestration easy to follow.
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console

from hivemind.config import load_settings
from hivemind.events import EventBus
from hivemind.providers.fake_provider import FakeLLMProvider
from hivemind.runtime import HiveMindRuntime
from hivemind.terminal_ui import TerminalRenderer

app = typer.Typer(
    name="hivemind",
    help="Learn multi-agent orchestration through a local-first research system.",
    no_args_is_help=True,
)
console = Console()


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


async def _demo(prompt: str, *, plain: bool, explain: bool) -> None:
    settings = load_settings(provider="fake", enable_web=False)
    provider = FakeLLMProvider()
    event_bus = EventBus()
    renderer = TerminalRenderer(console=console, plain=plain, explain=explain)
    event_bus.subscribe(renderer.handle)
    renderer.show_header(prompt=prompt, provider=provider.name, model=provider.model)
    result = await HiveMindRuntime(settings, provider, event_bus).run(prompt)
    renderer.show_report(result.final_report)
