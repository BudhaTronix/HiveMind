"""Persist HiveMind state and artifacts with readable SQLite and JSON files.

The repository keeps SQL out of orchestration while avoiding an ORM. JSON payload columns
preserve Pydantic contracts without a large relational schema, and explicit indexed columns
support the CLI queries a learner is likely to inspect.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import aiosqlite
from pydantic import BaseModel

from hivemind.schemas import (
    AgentProfile,
    Evidence,
    FinalReport,
    HiveEvent,
    RunRecord,
    TaskRecord,
    TaskStatus,
    utc_now,
)

SCHEMA_VERSION = 1


class HiveMindRepository:
    """Store and query one local HiveMind database."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Create the versioned schema on first use."""

        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            async with aiosqlite.connect(self.path) as db:
                await db.execute("PRAGMA journal_mode = WAL")
                await db.executescript(_SCHEMA)
                await db.execute(
                    "INSERT OR IGNORE INTO schema_version(version) VALUES (?)",
                    (SCHEMA_VERSION,),
                )
                await db.commit()
            self._initialized = True

    async def create_project(self, project_id: str, name: str) -> None:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO projects(project_id, name, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET name = excluded.name
                """,
                (project_id, name, utc_now().isoformat()),
            )
            await db.commit()

    async def save_run(self, run: RunRecord) -> None:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO runs(
                    run_id, project_id, prompt, provider, model, stage, round_number,
                    max_rounds, created_at, updated_at, error_message, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    stage = excluded.stage,
                    round_number = excluded.round_number,
                    updated_at = excluded.updated_at,
                    error_message = excluded.error_message,
                    payload_json = excluded.payload_json
                """,
                (
                    run.run_id,
                    run.project_id,
                    run.prompt,
                    run.provider,
                    run.model,
                    run.stage.value,
                    run.round_number,
                    run.max_rounds,
                    run.created_at.isoformat(),
                    run.updated_at.isoformat(),
                    run.error_message,
                    run.model_dump_json(),
                ),
            )
            await db.commit()

    async def get_run(self, run_id: str) -> RunRecord | None:
        row = await self._fetchone("SELECT payload_json FROM runs WHERE run_id = ?", (run_id,))
        return RunRecord.model_validate_json(row[0]) if row else None

    async def list_runs(self, limit: int = 50) -> list[RunRecord]:
        rows = await self._fetchall(
            "SELECT payload_json FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [RunRecord.model_validate_json(row[0]) for row in rows]

    async def save_agent(self, agent: AgentProfile) -> None:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO agents(
                    agent_id, project_id, role_key, name, kind, parent_agent_id, status,
                    last_used_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_id) DO UPDATE SET
                    name = excluded.name,
                    parent_agent_id = excluded.parent_agent_id,
                    status = excluded.status,
                    last_used_at = excluded.last_used_at,
                    payload_json = excluded.payload_json
                """,
                (
                    agent.agent_id,
                    agent.project_id,
                    agent.role_key,
                    agent.name,
                    agent.kind.value,
                    agent.parent_agent_id,
                    agent.status.value,
                    agent.last_used_at.isoformat(),
                    agent.model_dump_json(),
                ),
            )
            await db.commit()

    async def find_agent(self, project_id: str, role_key: str) -> AgentProfile | None:
        row = await self._fetchone(
            """
            SELECT payload_json FROM agents
            WHERE project_id = ? AND role_key = ?
            ORDER BY last_used_at DESC LIMIT 1
            """,
            (project_id, role_key),
        )
        return AgentProfile.model_validate_json(row[0]) if row else None

    async def get_agent(self, agent_id: str) -> AgentProfile | None:
        row = await self._fetchone(
            "SELECT payload_json FROM agents WHERE agent_id = ?", (agent_id,)
        )
        return AgentProfile.model_validate_json(row[0]) if row else None

    async def list_agents(self, project_id: str | None = None) -> list[AgentProfile]:
        if project_id:
            rows = await self._fetchall(
                """
                SELECT payload_json FROM agents
                WHERE project_id = ? ORDER BY last_used_at DESC
                """,
                (project_id,),
            )
        else:
            rows = await self._fetchall(
                "SELECT payload_json FROM agents ORDER BY last_used_at DESC"
            )
        return [AgentProfile.model_validate_json(row[0]) for row in rows]

    async def save_task(self, task: TaskRecord, output: BaseModel | None = None) -> None:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO tasks(
                    task_id, run_id, parent_task_id, agent_id, status, created_at,
                    completed_at, output_json, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    status = excluded.status,
                    completed_at = excluded.completed_at,
                    output_json = COALESCE(excluded.output_json, tasks.output_json),
                    payload_json = excluded.payload_json
                """,
                (
                    task.task_id,
                    task.run_id,
                    task.parent_task_id,
                    task.agent_id,
                    task.status.value,
                    task.created_at.isoformat(),
                    task.completed_at.isoformat() if task.completed_at else None,
                    output.model_dump_json() if output else None,
                    task.model_dump_json(),
                ),
            )
            await db.commit()

    async def list_tasks(self, run_id: str) -> list[TaskRecord]:
        rows = await self._fetchall(
            "SELECT payload_json FROM tasks WHERE run_id = ? ORDER BY created_at", (run_id,)
        )
        return [TaskRecord.model_validate_json(row[0]) for row in rows]

    async def get_completed_task_output(self, run_id: str, agent_id: str, title: str) -> str | None:
        """Return reusable validated output for one stable run/agent/task stage."""

        row = await self._fetchone(
            """
            SELECT output_json FROM tasks
            WHERE run_id = ? AND agent_id = ? AND status = ?
              AND json_extract(payload_json, '$.title') = ?
              AND output_json IS NOT NULL
            ORDER BY completed_at DESC LIMIT 1
            """,
            (run_id, agent_id, TaskStatus.COMPLETED.value, title),
        )
        return str(row[0]) if row else None

    async def reset_stale_tasks(self, run_id: str) -> int:
        """Make interrupted running work eligible for a lightweight resume."""

        await self.initialize()
        stale = {
            TaskStatus.RUNNING.value,
            TaskStatus.WAITING_FOR_TOOL.value,
            TaskStatus.WAITING_FOR_CHILDREN.value,
            TaskStatus.RETRYING.value,
        }
        placeholders = ",".join("?" for _ in stale)
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                f"""
                UPDATE tasks SET status = ?, payload_json = json_set(
                    payload_json, '$.status', ?
                ) WHERE run_id = ? AND status IN ({placeholders})
                """,
                (TaskStatus.PENDING.value, TaskStatus.PENDING.value, run_id, *stale),
            )
            await db.commit()
            return cursor.rowcount

    async def save_event(self, event: HiveEvent) -> None:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT OR IGNORE INTO events(
                    event_id, run_id, timestamp, event_type, agent_id, task_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.run_id,
                    event.timestamp.isoformat(),
                    event.event_type.value,
                    event.agent_id,
                    event.task_id,
                    event.model_dump_json(),
                ),
            )
            await db.commit()

    async def list_events(self, run_id: str) -> list[HiveEvent]:
        rows = await self._fetchall(
            "SELECT payload_json FROM events WHERE run_id = ? ORDER BY timestamp", (run_id,)
        )
        return [HiveEvent.model_validate_json(row[0]) for row in rows]

    async def save_evidence(self, item: Evidence) -> None:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO evidence(
                    evidence_id, run_id, task_id, agent_id, url, retrieved_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.evidence_id,
                    item.run_id,
                    item.task_id,
                    item.agent_id,
                    item.url,
                    item.retrieved_at.isoformat(),
                    item.model_dump_json(),
                ),
            )
            await db.commit()

    async def list_evidence(self, run_id: str) -> list[Evidence]:
        rows = await self._fetchall(
            "SELECT payload_json FROM evidence WHERE run_id = ? ORDER BY retrieved_at",
            (run_id,),
        )
        return [Evidence.model_validate_json(row[0]) for row in rows]

    async def save_claims(self, run_id: str, claims: list[BaseModel]) -> None:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            await db.executemany(
                """
                INSERT OR REPLACE INTO claims(claim_id, run_id, payload_json)
                VALUES (?, ?, ?)
                """,
                [(str(item.claim_id), run_id, item.model_dump_json()) for item in claims],
            )
            await db.commit()

    async def save_report(
        self,
        run_id: str,
        report_type: str,
        report: BaseModel,
        *,
        round_number: int,
        task_id: str = "",
    ) -> None:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO reports(
                    report_id, run_id, report_type, round_number, task_id,
                    created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, report_type, round_number, task_id)
                DO UPDATE SET payload_json = excluded.payload_json,
                              created_at = excluded.created_at
                """,
                (
                    f"{run_id}:{round_number}:{report_type}:{task_id}",
                    run_id,
                    report_type,
                    round_number,
                    task_id,
                    utc_now().isoformat(),
                    report.model_dump_json(),
                ),
            )
            await db.commit()

    async def get_report_json(
        self, run_id: str, report_type: str, *, round_number: int | None = None
    ) -> str | None:
        sql = "SELECT payload_json FROM reports WHERE run_id = ? AND report_type = ?"
        params: tuple[object, ...] = (run_id, report_type)
        if round_number is not None:
            sql += " AND round_number = ?"
            params += (round_number,)
        sql += " ORDER BY round_number DESC LIMIT 1"
        row = await self._fetchone(sql, params)
        return str(row[0]) if row else None

    async def save_checkpoint(self, run_id: str, key: str, payload: BaseModel) -> None:
        await self.save_report(run_id, f"checkpoint:{key}", payload, round_number=0)

    async def get_checkpoint(self, run_id: str, key: str) -> str | None:
        return await self.get_report_json(run_id, f"checkpoint:{key}")

    async def save_artifact(self, run_id: str, kind: str, path: Path) -> None:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO artifacts(artifact_id, run_id, kind, path, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (f"{run_id}:{kind}", run_id, kind, str(path), utc_now().isoformat()),
            )
            await db.commit()

    async def _fetchone(self, sql: str, params: tuple[object, ...] = ()) -> Any:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(sql, params)
            return await cursor.fetchone()

    async def _fetchall(self, sql: str, params: tuple[object, ...] = ()) -> list[Any]:
        await self.initialize()
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(sql, params)
            return await cursor.fetchall()


class ArtifactStore:
    """Write portable run files alongside the SQLite state."""

    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    async def prepare(self, run: RunRecord) -> Path:
        directory = self.run_dir(run.run_id)
        directory.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            (directory / "user_prompt.txt").write_text,
            run.prompt,
            encoding="utf-8",
        )
        return directory

    async def write_json(self, run_id: str, filename: str, value: BaseModel | list[Any]) -> Path:
        path = self.run_dir(run_id) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, BaseModel):
            content = value.model_dump_json(indent=2)
        else:
            content = json.dumps(
                [
                    item.model_dump(mode="json") if isinstance(item, BaseModel) else item
                    for item in value
                ],
                indent=2,
                default=str,
            )
        await asyncio.to_thread(path.write_text, content + "\n", encoding="utf-8")
        return path

    async def write_final_markdown(self, run_id: str, report: FinalReport) -> Path:
        path = self.run_dir(run_id) / "final_report.md"
        lines = [
            f"# {report.title}",
            "",
            "## Executive summary",
            "",
            report.executive_summary,
            "",
            "## Direct answer",
            "",
            report.answer,
        ]
        for title, values in (
            ("Key findings", report.key_findings),
            ("Risks", report.risks),
            ("Uncertainties", report.uncertainties),
            ("Recommendations", report.recommendations),
            ("Research limitations", report.research_limitations),
        ):
            lines.extend(["", f"## {title}", ""])
            lines.extend(f"- {item}" for item in values)
        lines.extend(["", "## Sources", ""])
        for source in report.sources:
            location = source.url or "No URL (simulated/local evidence)"
            lines.append(
                f"- **{source.title}** — {location} — retrieved "
                f"{source.retrieved_at.date()} — {source.verification_status.value}"
            )
        await asyncio.to_thread(path.write_text, "\n".join(lines) + "\n", encoding="utf-8")
        return path


class JsonlEventSink:
    """Append already-redacted public events to one run's JSONL artifact."""

    def __init__(self, artifacts: ArtifactStore) -> None:
        self.artifacts = artifacts

    async def __call__(self, event: HiveEvent) -> None:
        path = self.artifacts.run_dir(event.run_id) / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = event.model_dump_json() + "\n"

        def append() -> None:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)

        await asyncio.to_thread(append)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    prompt TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    stage TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    max_rounds INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error_message TEXT,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    role_key TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    parent_agent_id TEXT,
    status TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(project_id, role_key)
);
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    parent_task_id TEXT,
    agent_id TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    output_json TEXT,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    agent_id TEXT,
    task_id TEXT,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    url TEXT,
    retrieved_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    report_type TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    task_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE(run_id, report_type, round_number, task_id)
);
CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_calls (
    tool_call_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    task_id TEXT,
    agent_id TEXT,
    tool_name TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_run ON tasks(run_id, status);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_evidence_run ON evidence(run_id);
CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope, scope_id, status);
"""
