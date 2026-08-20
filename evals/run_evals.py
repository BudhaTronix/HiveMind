"""Run deterministic workflow evaluations without APIs, live web, or an LLM judge.

This runner asks simple architectural questions: did the run finish, are citations backed by
evidence, did limits hold, and were failures and memory handled? It complements unit tests;
it does not claim to grade real research quality.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from hivemind.config import Settings
from hivemind.events import EventBus
from hivemind.persistence import HiveMindRepository
from hivemind.providers.fake_provider import FakeLLMProvider
from hivemind.runtime import HiveMindRuntime
from hivemind.schemas import MemoryScope, RunStage

CASES_PATH = Path(__file__).with_name("cases.json")


async def evaluate(case: dict[str, Any], root: Path) -> dict[str, bool]:
    case_root = root / case["name"].replace(" ", "-")
    settings = Settings(
        HIVEMIND_PROVIDER="fake",
        HIVEMIND_ENABLE_WEB=False,
        HIVEMIND_DB_PATH=case_root / "hivemind.db",
        HIVEMIND_RUNS_DIR=case_root / "runs",
        HIVEMIND_MAX_RESEARCH_ROUNDS=case.get("max_rounds", 2),
        HIVEMIND_MAX_MANAGERS=case.get("max_managers", 3),
    )
    repository = HiveMindRepository(settings.db_path)
    provider = FakeLLMProvider(fail_roles=set(case.get("fail_roles", [])))
    project = "evaluation-project"
    runtime = HiveMindRuntime(settings, provider, EventBus(), repository=repository)
    if case.get("repeat_project"):
        await runtime.run(case["prompt"], project_id=project)
        runtime = HiveMindRuntime(settings, FakeLLMProvider(), EventBus(), repository=repository)
    result = await runtime.run(case["prompt"], project_id=project)
    evidence_ids = {item.evidence_id for item in result.evidence}
    claims = [claim for report in result.manager_reports for claim in report.merged_claims]
    memories = await repository.list_memories([(MemoryScope.PROJECT, project)])
    return {
        "completed": result.run.stage == RunStage.COMPLETED,
        "report": bool(result.final_report.answer),
        "citations": all(
            source.evidence_id in evidence_ids for source in result.final_report.sources
        ),
        "claim evidence": all(
            all(evidence_id in evidence_ids for evidence_id in claim.evidence_ids)
            for claim in claims
        ),
        "limits": len(result.agents) <= settings.max_total_agents
        and len(result.plan.departments) <= settings.max_managers,
        "partial failure": bool(result.manager_reports),
        "round bound": result.run.round_number <= settings.max_research_rounds,
        "memory curated": bool(memories),
    }


async def main() -> int:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    console = Console()
    table = Table(title="HiveMind deterministic evaluations")
    table.add_column("Case")
    metric_names = [
        "completed",
        "report",
        "citations",
        "claim evidence",
        "limits",
        "partial failure",
        "round bound",
        "memory curated",
    ]
    for name in metric_names:
        table.add_column(name)
    all_passed = True
    with tempfile.TemporaryDirectory(prefix="hivemind-evals-") as directory:
        root = Path(directory)
        for case in cases:
            metrics = await evaluate(case, root)
            all_passed = all_passed and all(metrics.values())
            table.add_row(
                case["name"],
                *("[green]yes[/]" if metrics[name] else "[red]no[/]" for name in metric_names),
            )
    console.print(table)
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
