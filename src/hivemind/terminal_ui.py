"""Render live and log-friendly views of the same HiveMind event stream.

The dashboard owns presentation state only. It reconstructs its tree, counters, stage, and
recent activity from public events, which is the same strategy used later by ``status``.
Plain mode prints stable timestamped lines for CI and redirected logs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from rich.columns import Columns
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from hivemind.schemas import AgentStatus, EventType, FinalReport, HiveEvent


@dataclass(slots=True)
class DisplayAgent:
    """Small event-derived view of an agent; it is not orchestration state."""

    agent_id: str
    name: str
    kind: str
    parent_agent_id: str | None
    status: str = AgentStatus.CREATED.value
    claims: int = 0
    evidence: int = 0


class DashboardState:
    """Reduce public events into data needed by terminal renderers."""

    def __init__(self, *, prompt: str, provider: str, model: str, max_rounds: int) -> None:
        self.prompt = prompt
        self.provider = provider
        self.model = model
        self.max_rounds = max_rounds
        self.run_id = "pending"
        self.stage = "created"
        self.round_number = 0
        self.started_at = datetime.now(UTC)
        self.agents: dict[str, DisplayAgent] = {}
        self.recent_events: list[HiveEvent] = []
        self.claim_count = 0
        self.evidence_count = 0
        self.llm_calls = 0
        self.web_searches = 0
        self.web_fetches = 0
        self.retries = 0

    def apply(self, event: HiveEvent) -> None:
        """Apply one event without relying on terminal colors or message parsing."""

        self.run_id = event.run_id
        self.round_number = max(self.round_number, event.round_number)
        self.recent_events = [*self.recent_events[-7:], event]
        if event.event_type == EventType.STAGE_CHANGED:
            self.stage = str(event.metadata.get("stage", self.stage))
        if event.event_type == EventType.AGENT_SPAWNED and event.agent_id:
            self.agents[event.agent_id] = DisplayAgent(
                agent_id=event.agent_id,
                name=str(event.metadata.get("name", "Agent")),
                kind=str(event.metadata.get("kind", "agent")),
                parent_agent_id=event.parent_agent_id,
                status=str(event.metadata.get("status", AgentStatus.CREATED.value)),
            )
        if (
            event.event_type
            in {
                EventType.AGENT_STARTED,
                EventType.AGENT_STATUS_CHANGED,
                EventType.AGENT_COMPLETED,
                EventType.AGENT_FAILED,
            }
            and event.agent_id in self.agents
        ):
            agent = self.agents[event.agent_id]
            default = {
                EventType.AGENT_STARTED: AgentStatus.RUNNING.value,
                EventType.AGENT_COMPLETED: AgentStatus.COMPLETED.value,
                EventType.AGENT_FAILED: AgentStatus.FAILED.value,
            }.get(event.event_type, agent.status)
            agent.status = str(event.metadata.get("status", default))
            agent.claims = int(event.metadata.get("claims", agent.claims))
            agent.evidence = int(event.metadata.get("evidence", agent.evidence))
        self.claim_count += int(event.metadata.get("claims_added", 0))
        self.evidence_count += int(event.metadata.get("evidence_added", 0))
        self.llm_calls += int(event.metadata.get("llm_calls", 0))
        if event.event_type == EventType.TOOL_COMPLETED:
            tool = event.metadata.get("tool")
            self.web_searches += int(tool == "web_search")
            self.web_fetches += int(tool == "web_fetch")
        if event.event_type == EventType.TASK_RETRYING:
            self.retries += 1


class TerminalRenderer:
    """Display a Rich live dashboard or timestamped plain event lines."""

    def __init__(
        self, *, console: Console | None = None, plain: bool = False, explain: bool = False
    ) -> None:
        self.console = console or Console()
        self.plain = plain
        self.explain = explain
        self.state: DashboardState | None = None
        self._live: Live | None = None

    def start(self, *, prompt: str, provider: str, model: str, max_rounds: int) -> None:
        """Start presentation before orchestration emits its first event."""

        self.state = DashboardState(
            prompt=prompt,
            provider=provider,
            model=model,
            max_rounds=max_rounds,
        )
        if self.plain:
            self.console.print(
                f"HiveMind | provider={provider} model={model} prompt={prompt}", markup=False
            )
            return
        self._live = Live(
            self._render_dashboard(),
            console=self.console,
            refresh_per_second=8,
            transient=False,
        )
        self._live.start()

    async def handle(self, event: HiveEvent) -> None:
        """Reduce and display one event-bus message."""

        if self.state is None:
            raise RuntimeError("TerminalRenderer.start() must be called before events arrive")
        self.state.apply(event)
        if self.plain:
            timestamp = event.timestamp.astimezone().strftime("%H:%M:%S")
            label = event.event_type.value.upper()
            self.console.print(f"{timestamp} [{label}] {event.message}", markup=False)
            if self.explain and "learning_note" in event.metadata:
                self.console.print(f"  Learning: {event.metadata['learning_note']}", markup=False)
        elif self._live:
            self._live.update(self._render_dashboard(), refresh=True)

    def stop(self) -> None:
        """Finish live rendering before printing a normal final report."""

        if self._live:
            self._live.stop()
            self._live = None

    def show_report(self, report: FinalReport) -> None:
        """Render the completed structured report."""

        body = [report.executive_summary, "", report.answer, "", "Key findings:"]
        body.extend(f"• {item}" for item in report.key_findings)
        body.extend(["", "Recommendations:"])
        body.extend(f"• {item}" for item in report.recommendations)
        self.console.print(Panel("\n".join(body), title=report.title, border_style="green"))

    def _render_dashboard(self) -> RenderableType:
        """Build a fresh renderable from event-derived state."""

        assert self.state is not None
        elapsed = datetime.now(UTC) - self.state.started_at
        elapsed_text = str(elapsed).split(".", maxsplit=1)[0]
        header = Table.grid(expand=True)
        header.add_column(ratio=3)
        header.add_column(ratio=2)
        header.add_row(
            f"[bold]HiveMind Run:[/] {self.state.run_id}",
            f"[bold]Elapsed:[/] {elapsed_text}",
        )
        header.add_row(
            f"[bold]Provider:[/] {self.state.provider} / {self.state.model}",
            f"[bold]Round:[/] {self.state.round_number or 1} of {self.state.max_rounds}",
        )
        header.add_row(
            f"[bold]Stage:[/] {self.state.stage.upper()}",
            f"[bold]Agents:[/] {len(self.state.agents)}",
        )
        prompt = Panel(self.state.prompt, title="User prompt", border_style="cyan")
        organization = Panel(
            self._render_tree(), title="Agent organization", border_style="magenta"
        )
        progress = self._render_progress()
        recent = Panel(self._render_recent(), title="Recent events", border_style="blue")
        learning = self._render_learning()
        parts: list[RenderableType] = [header, prompt, organization, progress, recent]
        if learning:
            parts.append(learning)
        return Group(*parts)

    def _render_tree(self) -> Tree:
        assert self.state is not None
        roots = [item for item in self.state.agents.values() if not item.parent_agent_id]
        if not roots:
            return Tree("Waiting for the CEO agent…")
        root = Tree(self._agent_label(roots[0]))
        self._append_children(root, roots[0].agent_id)
        return root

    def _append_children(self, tree: Tree, parent_id: str) -> None:
        assert self.state is not None
        children = [
            item for item in self.state.agents.values() if item.parent_agent_id == parent_id
        ]
        for child in children:
            branch = tree.add(self._agent_label(child))
            self._append_children(branch, child.agent_id)

    @staticmethod
    def _agent_label(agent: DisplayAgent) -> Text:
        color = _STATUS_COLORS.get(agent.status, "white")
        label = Text(agent.name)
        label.append(f"  {agent.status.upper()}", style=f"bold {color}")
        if agent.claims or agent.evidence:
            label.append(f"  {agent.claims} claims / {agent.evidence} sources", style="dim")
        return label

    def _render_progress(self) -> Columns:
        assert self.state is not None
        agents = list(self.state.agents.values())
        managers = [item for item in agents if item.kind == "manager"]
        workers = [item for item in agents if item.kind == "worker"]
        completed_managers = sum(item.status == "completed" for item in managers)
        completed_workers = sum(item.status == "completed" for item in workers)
        left = Panel(
            f"Managers: {completed_managers}/{len(managers)} complete\n"
            f"Workers: {completed_workers}/{len(workers)} complete\n"
            f"Retries: {self.state.retries}",
            title="Progress",
        )
        right = Panel(
            f"Claims: {self.state.claim_count}\n"
            f"Evidence: {self.state.evidence_count}\n"
            f"LLM calls: {self.state.llm_calls}\n"
            f"Web search/fetch: {self.state.web_searches}/{self.state.web_fetches}",
            title="Activity",
        )
        return Columns([left, right], equal=True, expand=True)

    def _render_recent(self) -> Text:
        assert self.state is not None
        lines = Text()
        for index, event in enumerate(self.state.recent_events):
            if index:
                lines.append("\n")
            lines.append(event.timestamp.astimezone().strftime("%H:%M:%S "), style="dim")
            lines.append(event.message)
        return lines or Text("Waiting for events…", style="dim")

    def _render_learning(self) -> Panel | None:
        assert self.state is not None
        if not self.explain:
            return None
        notes = [
            str(item.metadata["learning_note"])
            for item in self.state.recent_events
            if "learning_note" in item.metadata
        ]
        if not notes:
            return Panel("Learning notes appear as the workflow advances.", title="Explain mode")
        return Panel(notes[-1], title="Learning", border_style="cyan")


_STATUS_COLORS = {
    AgentStatus.CREATED.value: "white",
    AgentStatus.PLANNING.value: "blue",
    AgentStatus.RUNNING.value: "yellow",
    AgentStatus.WAITING_FOR_TOOL.value: "yellow",
    AgentStatus.WAITING_FOR_CHILDREN.value: "cyan",
    AgentStatus.SYNTHESIZING.value: "blue",
    AgentStatus.RETRYING.value: "magenta",
    AgentStatus.COMPLETED.value: "green",
    AgentStatus.FAILED.value: "red",
    AgentStatus.CANCELLED.value: "red",
}
