"""Retries, terminal failures, and secret redaction are bounded and observable."""

import json

import pytest
from pydantic import BaseModel

from hivemind.config import Settings
from hivemind.events import EventBus
from hivemind.persistence import HiveMindRepository
from hivemind.providers.base import ProviderError
from hivemind.providers.fake_provider import FakeLLMProvider
from hivemind.runtime import HiveMindRuntime
from hivemind.schemas import CompanyPlan, EventType, RunStage, WorkerReport


def settings_for(tmp_path) -> Settings:
    return Settings(
        HIVEMIND_PROVIDER="fake",
        HIVEMIND_ENABLE_WEB=False,
        HIVEMIND_DB_PATH=tmp_path / "hivemind.db",
        HIVEMIND_RUNS_DIR=tmp_path / "runs",
        HIVEMIND_MAX_RETRIES=2,
    )


class FlakyWorkerProvider(FakeLLMProvider):
    def __init__(self) -> None:
        super().__init__()
        self.failed_once = False

    async def generate_structured(
        self,
        schema: type[BaseModel],
        system_prompt: str,
        user_prompt: str,
    ) -> BaseModel:
        payload = json.loads(user_prompt)
        if (
            schema is WorkerReport
            and payload.get("role_key") == "market-research-demand"
            and not self.failed_once
        ):
            self.failed_once = True
            raise ProviderError("Temporary local model overload.")
        return await super().generate_structured(schema, system_prompt, user_prompt)


async def test_retryable_worker_error_is_retried_and_recovers(tmp_path) -> None:
    bus = EventBus()

    result = await HiveMindRuntime(settings_for(tmp_path), FlakyWorkerProvider(), bus).run(
        "Research a startup market"
    )

    market = next(
        item for item in result.manager_reports if item.department_name == "Market Research"
    )
    assert len(market.merged_claims) == 2
    assert any(item.event_type == EventType.TASK_RETRYING for item in bus.events)


class FailingCEOProvider(FakeLLMProvider):
    async def generate_structured(
        self,
        schema: type[BaseModel],
        system_prompt: str,
        user_prompt: str,
    ) -> BaseModel:
        if schema is CompanyPlan:
            raise ProviderError(
                "Authentication failed api_key=sk-supersecret12345", retryable=False
            )
        return await super().generate_structured(schema, system_prompt, user_prompt)


async def test_nonretryable_failure_marks_run_failed_and_redacts_secret(tmp_path) -> None:
    settings = settings_for(tmp_path)
    repository = HiveMindRepository(settings.db_path)
    bus = EventBus()
    bus.subscribe(repository.save_event)
    runtime = HiveMindRuntime(settings, FailingCEOProvider(), bus, repository=repository)

    with pytest.raises(ProviderError):
        await runtime.run("Research a startup market")

    assert runtime._active_run is not None
    saved = await repository.get_run(runtime._active_run.run_id)
    tasks = await repository.list_tasks(runtime._active_run.run_id)
    serialized_events = "\n".join(item.model_dump_json() for item in bus.events)
    assert saved and saved.stage == RunStage.FAILED
    assert sum(item.event_type == EventType.RUN_FAILED for item in bus.events) == 1
    assert "sk-supersecret12345" not in serialized_events
    assert all("sk-supersecret12345" not in (item.error_message or "") for item in tasks)


async def test_event_bus_redacts_message_and_nested_metadata() -> None:
    bus = EventBus()

    event = await bus.emit(
        EventType.TOOL_FAILED,
        "run_test",
        "Request used Bearer abc.def.secret and api_key=sk-secretvalue123",
        metadata={
            "authorization": "Bearer abc.def.secret",
            "nested": {"url": "https://example.com?token=privatevalue"},
        },
    )

    serialized = event.model_dump_json()
    assert "abc.def.secret" not in serialized
    assert "sk-secretvalue123" not in serialized
    assert "privatevalue" not in serialized
