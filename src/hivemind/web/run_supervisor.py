"""Own background HiveMind runs independently from the Typer CLI."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from hivemind.config import Settings
from hivemind.events import EventBus
from hivemind.observability import AgentHandoff, RuntimeObserver
from hivemind.persistence import ArtifactStore, HiveMindRepository, JsonlEventSink
from hivemind.providers import create_provider
from hivemind.runtime import HiveMindRuntime
from hivemind.schemas import RunRecord
from hivemind.web.broker import LiveBroker
from hivemind.web.models import NewRunRequest


class PersistentHandoffObserver(RuntimeObserver):
    """Queue a public handoff for live clients, then persist it for reconstruction."""

    def __init__(self, repository: HiveMindRepository, broker: LiveBroker) -> None:
        self.repository = repository
        self.broker = broker

    async def publish_handoff(self, handoff: AgentHandoff) -> None:
        await self.broker.publish_handoff(handoff)
        await self.repository.save_handoff(handoff)


class RunSupervisor:
    """Track in-process run tasks and compose each runtime from public components."""

    def __init__(
        self,
        settings: Settings,
        repository: HiveMindRepository,
        artifacts: ArtifactStore,
        broker: LiveBroker,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.artifacts = artifacts
        self.broker = broker
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    async def schedule(self, request: NewRunRequest) -> RunRecord:
        run_settings = self._settings_for(request)
        provider = create_provider(run_settings)
        run = RunRecord(
            project_id=request.project_id,
            prompt=request.prompt,
            provider=provider.name,
            model=provider.model,
            max_rounds=run_settings.max_research_rounds,
        )
        await self.repository.create_project(run.project_id, run.project_id)
        await self.repository.save_run(run)
        runtime = self._runtime(run_settings, provider)
        self._start(
            run.run_id,
            runtime.run(run.prompt, project_id=run.project_id, existing_run=run),
        )
        return run

    async def resume(self, run_id: str) -> RunRecord:
        run = await self.repository.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if self.is_active(run_id):
            raise RuntimeError("Run is already active.")
        run_settings = self._settings_from_record(run)
        provider = create_provider(run_settings)
        runtime = self._runtime(run_settings, provider)
        self._start(run_id, runtime.resume(run_id))
        return run

    async def cancel(self, run_id: str) -> RunRecord:
        run = await self.repository.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        task = self._tasks.get(run_id)
        if task is None or task.done():
            raise RuntimeError("Run is not active.")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return await self.repository.get_run(run_id) or run

    async def delete(self, run_id: str) -> None:
        run = await self.repository.get_run(run_id)
        if run is None:
            raise KeyError(run_id)
        if self.is_active(run_id):
            raise RuntimeError("Active runs must be cancelled before deletion.")
        await self.artifacts.delete_run(run_id)
        if not await self.repository.delete_run(run_id):
            raise KeyError(run_id)

    def is_active(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        return bool(task and not task.done())

    async def shutdown(self) -> None:
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _runtime(self, settings: Settings, provider: Any) -> HiveMindRuntime:
        events = EventBus()
        # The broker only performs a bounded put_nowait, so live clients see the state
        # change before slower SQLite and filesystem persistence completes. Its
        # subscribe-before-snapshot protocol buffers this safely during reconnects.
        events.subscribe(self.broker.event_sink)
        events.subscribe(self.repository.save_event)
        events.subscribe(JsonlEventSink(self.artifacts))
        return HiveMindRuntime(
            settings,
            provider,
            events,
            repository=self.repository,
            artifacts=self.artifacts,
            observer=PersistentHandoffObserver(self.repository, self.broker),
        )

    def _start(self, run_id: str, coroutine: Any) -> None:
        task = asyncio.create_task(coroutine, name=f"hivemind-web:{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda completed: self._finished(run_id, completed))

    def _finished(self, run_id: str, task: asyncio.Task[Any]) -> None:
        self._tasks.pop(run_id, None)
        with suppress(asyncio.CancelledError, Exception):
            task.exception()
        self.broker.publish(run_id, {"type": "run_state", "data": {"run_id": run_id}})

    def _settings_for(self, request: NewRunRequest) -> Settings:
        updates: dict[str, Any] = {
            "provider": request.provider,
            "enable_web": request.enable_web,
            "max_managers": request.max_managers,
            "max_workers_per_manager": request.max_workers_per_manager,
            "max_research_rounds": request.max_research_rounds,
            "max_concurrent_llm_calls": request.max_concurrent_llm_calls,
        }
        if request.model and request.provider == "ollama":
            updates["ollama_model"] = request.model
        elif request.model and request.provider == "openai":
            updates["openai_model"] = request.model
        return self.settings.model_copy(update=updates)

    def _settings_from_record(self, run: RunRecord) -> Settings:
        updates: dict[str, Any] = {
            "provider": run.provider,
            "max_research_rounds": run.max_rounds,
        }
        if run.provider == "ollama":
            updates["ollama_model"] = run.model
        elif run.provider == "openai":
            updates["openai_model"] = run.model
        return self.settings.model_copy(update=updates)
