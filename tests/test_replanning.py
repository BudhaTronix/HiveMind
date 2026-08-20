"""QA follow-up is useful, focused, and bounded by Python."""

from pydantic import BaseModel

from hivemind.config import Settings
from hivemind.events import EventBus
from hivemind.providers.fake_provider import FakeLLMProvider
from hivemind.runtime import HiveMindRuntime
from hivemind.schemas import EventType, VerificationReport


def settings_for(tmp_path, *, rounds: int = 2) -> Settings:
    return Settings(
        HIVEMIND_PROVIDER="fake",
        HIVEMIND_ENABLE_WEB=False,
        HIVEMIND_DB_PATH=tmp_path / "hivemind.db",
        HIVEMIND_RUNS_DIR=tmp_path / "runs",
        HIVEMIND_MAX_RESEARCH_ROUNDS=rounds,
    )


async def test_qa_triggers_one_focused_follow_up_round(tmp_path) -> None:
    bus = EventBus()
    settings = settings_for(tmp_path)

    result = await HiveMindRuntime(settings, FakeLLMProvider(), bus).run(
        "Research a startup market"
    )

    assert result.run.round_number == 2
    assert result.qa.can_finalize
    assert any(item.role_key == "gap-analysis" for item in result.agents)
    assert len({item.department_name for item in result.manager_reports}) == 4
    assert len(result.agents) <= settings.max_total_agents
    assert sum(item.event_type == EventType.REPLAN_APPROVED for item in bus.events) == 1


async def test_maximum_round_count_finalizes_with_limitation(tmp_path) -> None:
    bus = EventBus()

    result = await HiveMindRuntime(settings_for(tmp_path, rounds=1), FakeLLMProvider(), bus).run(
        "Research a startup market"
    )

    assert result.run.round_number == 1
    assert not result.qa.can_finalize
    assert not any(item.event_type == EventType.REPLAN_APPROVED for item in bus.events)
    assert any("maximum of 1" in item for item in result.final_report.research_limitations)


class InventingVerifierProvider(FakeLLMProvider):
    async def generate_structured(
        self,
        schema: type[BaseModel],
        system_prompt: str,
        user_prompt: str,
    ) -> BaseModel:
        result = await super().generate_structured(schema, system_prompt, user_prompt)
        if schema is VerificationReport and result.findings:
            result.findings[0].supporting_evidence_ids.append("evidence_does_not_exist")
        return result


async def test_final_report_filters_nonexistent_evidence_ids(tmp_path) -> None:
    result = await HiveMindRuntime(
        settings_for(tmp_path), InventingVerifierProvider(), EventBus()
    ).run("Research a startup market")

    assert all(
        source.evidence_id != "evidence_does_not_exist" for source in result.final_report.sources
    )
