"""Render HiveMind activity in a terminal that works without a browser.

The initial renderer uses clear timestamped Rich lines. A live dashboard can subscribe to
the exact same event bus, so presentation never controls orchestration.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from hivemind.schemas import EventType, FinalReport, HiveEvent


class TerminalRenderer:
    """Display event lines and the final report with readable text labels."""

    def __init__(
        self, *, console: Console | None = None, plain: bool = False, explain: bool = False
    ) -> None:
        self.console = console or Console()
        self.plain = plain
        self.explain = explain

    async def handle(self, event: HiveEvent) -> None:
        """Handle one event-bus message."""

        timestamp = event.timestamp.astimezone().strftime("%H:%M:%S")
        label = event.event_type.value.upper()
        if self.plain:
            self.console.print(f"{timestamp} [{label}] {event.message}", markup=False)
        else:
            color = _EVENT_COLORS.get(event.event_type, "white")
            line = Text(f"{timestamp} ")
            line.append(f"[{label}]", style=f"bold {color}")
            line.append(f" {event.message}")
            self.console.print(line)
        if self.explain and "learning_note" in event.metadata:
            self.console.print(
                f"  Learning: {event.metadata['learning_note']}", style="italic cyan"
            )

    def show_header(self, *, prompt: str, provider: str, model: str) -> None:
        """Introduce a run before its event stream starts."""

        message = f"Prompt: {prompt}\nProvider: {provider} / {model}"
        self.console.print(Panel(message, title="HiveMind", border_style="cyan"))

    def show_report(self, report: FinalReport) -> None:
        """Render the completed structured report."""

        body = [report.executive_summary, "", report.answer, "", "Key findings:"]
        body.extend(f"• {item}" for item in report.key_findings)
        body.extend(["", "Recommendations:"])
        body.extend(f"• {item}" for item in report.recommendations)
        self.console.print(Panel("\n".join(body), title=report.title, border_style="green"))


_EVENT_COLORS = {
    EventType.RUN_CREATED: "cyan",
    EventType.STAGE_CHANGED: "blue",
    EventType.AGENT_SPAWNED: "magenta",
    EventType.AGENT_FAILED: "red",
    EventType.TOOL_FAILED: "red",
    EventType.RUN_FAILED: "red",
    EventType.RUN_COMPLETED: "green",
    EventType.AGENT_COMPLETED: "green",
    EventType.PLAN_VALIDATED: "green",
}
