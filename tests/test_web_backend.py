"""Deterministic acceptance coverage for the independent browser backend."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hivemind.config import Settings
from hivemind.observability import HandoffKind, create_handoff
from hivemind.persistence import HiveMindRepository
from hivemind.providers.fake_provider import FakeLLMProvider
from hivemind.schemas import AgentKind, AgentProfile, EventType, HiveEvent
from hivemind.web import create_app
from hivemind.web.broker import LiveBroker
from hivemind.web.models import NewRunRequest
from hivemind.web.snapshot import build_snapshot


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        HIVEMIND_PROVIDER="fake",
        HIVEMIND_ENABLE_WEB=False,
        HIVEMIND_DB_PATH=tmp_path / "hivemind.db",
        HIVEMIND_RUNS_DIR=tmp_path / "runs",
        HIVEMIND_MAX_RESEARCH_ROUNDS=1,
    )


def wait_for_terminal(client: TestClient, run_id: str, timeout: float = 5) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/runs/{run_id}/snapshot")
        if response.status_code == 200:
            snapshot = response.json()
            if snapshot["run"]["stage"] in {"completed", "failed", "cancelled"}:
                return snapshot
        time.sleep(0.02)
    raise AssertionError(f"Run {run_id} did not reach a terminal stage.")


def schedule_fake(client: TestClient, prompt: str = "Explain local-first agents") -> str:
    response = client.post(
        "/api/v1/runs",
        json={
            "prompt": prompt,
            "project_id": "web-tests",
            "provider": "fake",
            "enable_web": False,
            "max_research_rounds": 1,
        },
    )
    assert response.status_code == 202
    return str(response.json()["run_id"])


def test_health_and_public_settings_do_not_expose_secrets(tmp_path: Path) -> None:
    settings = settings_for(tmp_path).model_copy(update={"openai_api_key": "sk-supersecret123"})
    with TestClient(create_app(settings=settings)) as client:
        assert client.get("/api/v1/health").json() == {
            "status": "ok",
            "service": "hivemind-web",
        }
        response = client.get("/api/v1/public-settings")
        assert response.status_code == 200
        assert "supersecret" not in response.text
        assert "db_path" not in response.text
        rejected = client.post(
            "/api/v1/runs",
            json={"prompt": "Unsafe override", "provider": "fake", "api_key": "nope"},
        )
        assert rejected.status_code == 422


def test_real_provider_browser_requests_default_to_web_research() -> None:
    request = NewRunRequest(prompt="Research an evidence-backed answer", provider="ollama")

    assert request.enable_web is True


def test_fake_run_schedules_immediately_and_reconstructs_snapshot(tmp_path: Path) -> None:
    with TestClient(create_app(settings=settings_for(tmp_path))) as client:
        run_id = schedule_fake(client)
        snapshot = wait_for_terminal(client, run_id)
        assert snapshot["run"]["stage"] == "completed"
        assert snapshot["agents"]
        assert snapshot["events"]
        assert snapshot["tasks"]
        assert snapshot["handoffs"]
        assert snapshot["final_report"]["answer"]
        assert snapshot["metrics"]["agent_count"] == len(snapshot["agents"])


def test_spawn_membership_and_status_are_event_derived(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    repository = HiveMindRepository(settings.db_path)
    with TestClient(create_app(settings=settings, repository=repository)) as client:
        run_id = schedule_fake(client)
        snapshot = wait_for_terminal(client, run_id)
        ceo = next(item for item in snapshot["agents"] if item["profile"]["kind"] == "ceo")
        assert ceo["status"] == "completed"
        unrelated = AgentProfile(
            project_id="web-tests",
            role_key="unrelated",
            name="Unrelated stable agent",
            kind=AgentKind.WORKER,
            role_description="Did not participate.",
        )
        asyncio.run(repository.save_agent(unrelated))
        rebuilt = client.get(f"/api/v1/runs/{run_id}/snapshot").json()
        ids = {item["profile"]["agent_id"] for item in rebuilt["agents"]}
        assert unrelated.agent_id not in ids


def test_selected_agent_has_status_messages_tasks_tools_and_reports(tmp_path: Path) -> None:
    with TestClient(create_app(settings=settings_for(tmp_path))) as client:
        run_id = schedule_fake(client)
        snapshot = wait_for_terminal(client, run_id)
        worker = next(item for item in snapshot["agents"] if item["profile"]["kind"] == "worker")
        response = client.get(
            f"/api/v1/runs/{run_id}/agents/{worker['profile']['agent_id']}"
        )
        assert response.status_code == 200
        details = response.json()
        assert details["current_status"] == "completed"
        assert details["tasks"]
        assert details["incoming_handoffs"]
        assert details["outgoing_handoffs"]
        assert details["status_history"]
        assert details["reports"][0]["report_type"].startswith("worker:")


def test_handoff_redaction_recursive_bounds_and_deterministic_identity() -> None:
    arguments = {
        "run_id": "run_test",
        "round_number": 1,
        "source_agent_id": "agent_source",
        "target_agent_id": "agent_target",
        "kind": HandoffKind.WORKER_REPORT,
        "title": "x" * 400,
        "summary": "Bearer abcdefghijklmnopqrstuvwxyz " + "y" * 1_000,
        "payload_preview": {
            "api_key": "sk-shouldneverappear",
            "long": "z" * 2_000,
            "items": list(range(100)),
            "nested": {"token": "private-token-value"},
        },
    }
    first = create_handoff(**arguments)
    second = create_handoff(**arguments)
    assert first.handoff_id == second.handoff_id
    assert len(first.title) == 160
    assert len(first.summary) <= 600
    assert len(first.payload_preview["long"]) == 800
    assert len(first.payload_preview["items"]) == 20
    serialized = first.model_dump_json()
    assert "shouldneverappear" not in serialized
    assert "private-token-value" not in serialized
    assert "abcdefghijklmnopqrstuvwxyz" not in serialized


@pytest.mark.asyncio
async def test_repository_upserts_duplicate_handoffs(tmp_path: Path) -> None:
    repository = HiveMindRepository(tmp_path / "db.sqlite")
    handoff = create_handoff(
        run_id="run_one",
        round_number=1,
        source_agent_id="source",
        target_agent_id="target",
        kind=HandoffKind.ASSIGNMENT,
        title="Assignment",
        summary="Safe summary",
        payload_preview={"objective": "Test"},
    )
    await repository.save_handoff(handoff)
    await repository.save_handoff(handoff)
    assert await repository.list_handoffs("run_one") == [handoff]


def test_completed_resume_does_not_duplicate_handoffs(tmp_path: Path) -> None:
    with TestClient(create_app(settings=settings_for(tmp_path))) as client:
        run_id = schedule_fake(client)
        before = wait_for_terminal(client, run_id)["handoffs"]
        response = client.post(f"/api/v1/runs/{run_id}/resume")
        assert response.status_code == 202
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            after = client.get(f"/api/v1/runs/{run_id}/snapshot").json()["handoffs"]
            if len(after) == len(before):
                break
            time.sleep(0.01)
        assert {item["handoff_id"] for item in after} == {
            item["handoff_id"] for item in before
        }


def test_delete_old_run_removes_records_and_artifacts_but_keeps_agents(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    repository = HiveMindRepository(settings.db_path)
    with TestClient(create_app(settings=settings, repository=repository)) as client:
        run_id = schedule_fake(client)
        snapshot = wait_for_terminal(client, run_id)
        participating_ids = {
            item["profile"]["agent_id"] for item in snapshot["agents"]
        }
        artifact_dir = settings.runs_dir / run_id
        assert artifact_dir.is_dir()

        response = client.delete(f"/api/v1/runs/{run_id}")

        assert response.status_code == 200
        assert response.json() == {"run_id": run_id, "deleted": True}
        assert client.get(f"/api/v1/runs/{run_id}/snapshot").status_code == 404
        assert not artifact_dir.exists()
        stable_ids = {
            item.agent_id for item in asyncio.run(repository.list_agents("web-tests"))
        }
        assert participating_ids <= stable_ids


def test_websocket_sends_snapshot_before_buffered_live_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "hivemind.web.run_supervisor.create_provider",
        lambda settings: FakeLLMProvider(delay_seconds=0.04),
    )
    with TestClient(create_app(settings=settings_for(tmp_path))) as client:
        run_id = schedule_fake(client)
        with client.websocket_connect(f"/api/v1/runs/{run_id}/stream") as websocket:
            first = websocket.receive_json()
            assert first["type"] == "snapshot"
            snapshot_ids = {item["event_id"] for item in first["data"]["events"]}
            live = []
            for _ in range(40):
                envelope = websocket.receive_json()
                if envelope["type"] == "event":
                    assert envelope["data"]["event_id"] not in snapshot_ids
                    live.append(envelope["data"])
                    if envelope["data"]["event_type"] == "agent_spawned":
                        break
            assert any(item["event_type"] == "agent_spawned" for item in live)


@pytest.mark.asyncio
async def test_slow_or_disconnected_client_never_blocks_event_sink() -> None:
    broker = LiveBroker(queue_size=1)
    subscription = broker.subscribe("run_slow")
    for index in range(1_000):
        await broker.event_sink(
            HiveEvent(
                event_type=EventType.STAGE_CHANGED,
                run_id="run_slow",
                message=f"Event {index}",
            )
        )
    assert subscription.queue.qsize() == 1
    assert subscription.queue.get_nowait()["data"]["code"] == "resync_required"
    broker.unsubscribe(subscription)
    await asyncio.wait_for(
        broker.event_sink(
            HiveEvent(
                event_type=EventType.RUN_COMPLETED,
                run_id="run_slow",
                message="Done",
            )
        ),
        timeout=0.1,
    )


def test_cancel_marks_an_active_run_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "hivemind.web.run_supervisor.create_provider",
        lambda settings: FakeLLMProvider(delay_seconds=0.3),
    )
    with TestClient(create_app(settings=settings_for(tmp_path))) as client:
        run_id = schedule_fake(client)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            stage = client.get(f"/api/v1/runs/{run_id}/snapshot").json()["run"]["stage"]
            if stage != "created":
                break
            time.sleep(0.01)
        assert client.delete(f"/api/v1/runs/{run_id}").status_code == 409
        response = client.post(f"/api/v1/runs/{run_id}/cancel")
        assert response.status_code == 200
        assert response.json()["stage"] == "cancelled"


@pytest.mark.asyncio
async def test_existing_v1_database_upgrades_additively(tmp_path: Path) -> None:
    path = tmp_path / "v1.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
            INSERT INTO schema_version(version) VALUES (1);
            CREATE TABLE projects (
                project_id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
            );
            INSERT INTO projects VALUES ('preserved', 'Preserved project', '2026-01-01');
            """
        )
    repository = HiveMindRepository(path)
    await repository.initialize()
    with sqlite3.connect(path) as db:
        project = db.execute(
            "SELECT name FROM projects WHERE project_id = 'preserved'"
        ).fetchone()
        handoff_table = db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'handoffs'"
        ).fetchone()
        versions = db.execute("SELECT version FROM schema_version ORDER BY version").fetchall()
    assert project == ("Preserved project",)
    assert handoff_table == ("handoffs",)
    assert versions == [(1,), (2,)]


def test_snapshot_builder_applies_structured_agent_status(tmp_path: Path) -> None:
    repository = HiveMindRepository(tmp_path / "state.sqlite")

    async def scenario() -> None:
        from hivemind.schemas import RunRecord

        run = RunRecord(
            project_id="project",
            prompt="State test",
            provider="fake",
            model="simulator",
        )
        agent = AgentProfile(
            project_id="project",
            role_key="ceo",
            name="CEO",
            kind=AgentKind.CEO,
            role_description="Lead",
        )
        await repository.create_project("project", "project")
        await repository.save_run(run)
        await repository.save_agent(agent)
        await repository.save_event(
            HiveEvent(
                event_type=EventType.AGENT_SPAWNED,
                run_id=run.run_id,
                agent_id=agent.agent_id,
                message="Spawned",
                metadata={"status": "created", "name": "CEO", "kind": "ceo"},
            )
        )
        await repository.save_event(
            HiveEvent(
                event_type=EventType.AGENT_STATUS_CHANGED,
                run_id=run.run_id,
                agent_id=agent.agent_id,
                message="Human text is irrelevant",
                metadata={"status": "verifying"},
            )
        )
        snapshot = await build_snapshot(repository, run.run_id)
        assert snapshot is not None
        assert snapshot.agents[0].status.value == "verifying"

    asyncio.run(scenario())


def test_snapshot_uses_run_spawn_identity_instead_of_mutable_registry_profile(
    tmp_path: Path,
) -> None:
    repository = HiveMindRepository(tmp_path / "state.sqlite")

    async def scenario() -> None:
        from hivemind.schemas import RunRecord

        run = RunRecord(
            project_id="project",
            prompt="Snapshot identity test",
            provider="fake",
            model="simulator",
        )
        profile = AgentProfile(
            project_id="project",
            role_key="data",
            name="Data Lead",
            kind=AgentKind.MANAGER,
            role_description="Lead research.",
            parent_agent_id="agent_ceo",
        )
        await repository.create_project("project", "project")
        await repository.save_run(run)
        await repository.save_agent(profile)
        await repository.save_event(
            HiveEvent(
                event_type=EventType.AGENT_SPAWNED,
                run_id=run.run_id,
                agent_id=profile.agent_id,
                parent_agent_id="agent_ceo",
                message="Spawned manager",
                metadata={
                    "status": "queued",
                    "name": "Data Lead",
                    "kind": "manager",
                    "role_key": "data",
                },
            )
        )
        profile.name = "Colliding Worker"
        profile.kind = AgentKind.WORKER
        profile.parent_agent_id = profile.agent_id
        await repository.save_agent(profile)

        snapshot = await build_snapshot(repository, run.run_id)
        assert snapshot is not None
        restored = snapshot.agents[0].profile
        assert restored.name == "Data Lead"
        assert restored.kind == AgentKind.MANAGER
        assert restored.parent_agent_id == "agent_ceo"

    asyncio.run(scenario())


def test_protected_cli_sources_match_recorded_main_hashes() -> None:
    expected = {
        "src/hivemind/cli.py": "378a63f0af65a6693d2e288215e513c581c04c0d2fbd6134f9dacb934fa8a83c",
        "src/hivemind/terminal_ui.py": (
            "68d58a7c2170b123f66efccfdf18dc02f4c245f01881da7ff75d2ae0ec2d465a"
        ),
        "src/hivemind/__main__.py": (
            "04f0ab30d2691d13a439310b0361ce46e1e0f1c6d6c583a28fa78b105989eb75"
        ),
    }
    root = Path(__file__).resolve().parents[1]
    actual = {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in expected
    }
    assert actual == expected
