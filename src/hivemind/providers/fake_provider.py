"""Provide deterministic model-like responses for demos and automated tests.

The fake provider performs no network access. It is intentionally prompt-sensitive so the
demo still illustrates dynamic organization: a market question and a technical question do
not create the same departments. It is a simulator, not a source of real-world facts.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

from pydantic import BaseModel

from hivemind.providers.base import ProviderHealth
from hivemind.schemas import (
    Claim,
    CompanyPlan,
    CurationDecision,
    CurationResult,
    DepartmentSpec,
    FinalReport,
    FollowUpPlan,
    ManagerReport,
    MemoryCandidate,
    MemoryType,
    QAReport,
    SourceReference,
    VerificationFinding,
    VerificationReport,
    VerificationStatus,
    WorkerPlan,
    WorkerReport,
    WorkerSpec,
)

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class FakeLLMProvider:
    """Return realistic, deterministic fixtures through the real provider interface."""

    name = "fake"
    model = "educational-simulator"

    def __init__(self, *, fail_roles: set[str] | None = None) -> None:
        self.fail_roles = fail_roles or set()
        self.call_count = 0
        self.active_calls = 0
        self.max_active_calls = 0

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        self.call_count += 1
        return "HiveMind fake provider completed the requested educational step."

    async def check_health(self) -> ProviderHealth:
        """The offline simulator is always available once the package imports."""

        return ProviderHealth(ok=True, message="Offline fake provider is ready.")

    async def generate_structured(
        self,
        schema: type[SchemaT],
        system_prompt: str,
        user_prompt: str,
    ) -> SchemaT:
        self.call_count += 1
        payload = _payload(user_prompt)
        role_key = str(payload.get("role_key", ""))
        if role_key in self.fail_roles:
            raise RuntimeError(f"Simulated failure for {role_key}")
        factory = {
            CompanyPlan: self._company_plan,
            WorkerPlan: self._worker_plan,
            WorkerReport: self._worker_report,
            ManagerReport: self._manager_report,
            VerificationReport: self._verification_report,
            QAReport: self._qa_report,
            FollowUpPlan: self._follow_up_plan,
            CurationResult: self._curation_result,
            FinalReport: self._final_report,
        }.get(schema)
        if factory is None:
            raise TypeError(f"Fake provider has no fixture for {schema.__name__}")
        result = factory(payload)
        return schema.model_validate(result)

    def _company_plan(self, data: dict[str, Any]) -> CompanyPlan:
        prompt = str(data.get("prompt", "research topic"))
        lower = prompt.lower()
        if any(word in lower for word in ("market", "startup", "customer", "business", "ev")):
            departments = [
                _department("market-research", "Market Research", "Maya", prompt, 90),
                _department("regulation", "Regulation", "Ravi", prompt, 80),
                _department("competition", "Competition", "Connie", prompt, 70),
            ]
        elif any(word in lower for word in ("architecture", "technical", "software", "system")):
            departments = [
                _department("technical-feasibility", "Technical Feasibility", "Terry", prompt, 90),
                _department("security", "Security and Reliability", "Sam", prompt, 80),
                _department("cost-analysis", "Cost Analysis", "Casey", prompt, 70),
            ]
        else:
            departments = [
                _department("evidence", "Evidence Research", "Eden", prompt, 90),
                _department("impact", "Impact Analysis", "Imani", prompt, 80),
            ]
        return CompanyPlan(
            objective=prompt,
            departments=departments,
            rationale_summary="The simulated CEO selected prompt-specific viewpoints.",
        )

    def _worker_plan(self, data: dict[str, Any]) -> WorkerPlan:
        role_key = str(data["role_key"])
        name = str(data.get("name", role_key.replace("-", " ").title()))
        topics = {
            "market-research": ("demand", "pricing"),
            "regulation": ("policy", "compliance"),
            "competition": ("competitors", "business-models"),
            "technical-feasibility": ("architecture", "scalability"),
            "security": ("threats", "controls"),
            "cost-analysis": ("infrastructure-cost", "operations-cost"),
            "evidence": ("primary-sources", "recent-findings"),
            "impact": ("benefits", "risks"),
            "gap-analysis": ("missing-evidence",),
        }.get(role_key, ("facts", "risks"))
        workers = [
            WorkerSpec(
                role_key=f"{role_key}-{topic}",
                name=f"{topic.replace('-', ' ').title()} Researcher",
                role=f"Research {topic.replace('-', ' ')}",
                objective=f"Investigate {topic.replace('-', ' ')} for {name}.",
                research_questions=[f"What reliable evidence covers {topic.replace('-', ' ')}?"],
                search_queries=[f"{name} {topic.replace('-', ' ')} evidence"],
                rationale_summary="This focused role covers one distinct part of the objective.",
                priority=90 - index,
            )
            for index, topic in enumerate(topics)
        ]
        return WorkerPlan(
            department_role_key=role_key,
            workers=workers,
            rationale_summary="The simulated manager divided its objective into focused tasks.",
        )

    def _worker_report(self, data: dict[str, Any]) -> WorkerReport:
        role_key = str(data["role_key"])
        evidence_ids = list(data.get("evidence_ids", []))
        claim = Claim(
            text=f"The simulated evidence contains a finding relevant to {role_key}.",
            confidence=0.78 if evidence_ids else 0.35,
            evidence_ids=evidence_ids[:2],
            limitations=["Demo evidence is synthetic and must not be treated as real research."],
        )
        return WorkerReport(
            summary=f"Completed an offline simulated review for {role_key}.",
            claims=[claim],
            important_findings=[claim.text],
            open_questions=[] if evidence_ids else ["Real evidence is required."],
            conflicts=[],
            memory_candidates=[
                MemoryCandidate(
                    text=f"The project should investigate {role_key} with real sources.",
                    memory_type=MemoryType.LESSON,
                    confidence=0.7,
                    source_evidence_ids=evidence_ids[:1],
                )
            ],
        )

    def _manager_report(self, data: dict[str, Any]) -> ManagerReport:
        reports = [WorkerReport.model_validate(item) for item in data.get("worker_reports", [])]
        claims = [claim for report in reports for claim in report.claims]
        failed = int(data.get("failed_workers", 0))
        return ManagerReport(
            department_name=str(data.get("name", "Department")),
            summary=f"Combined {len(reports)} successful worker report(s).",
            merged_claims=claims,
            agreements=[claim.text for claim in claims],
            conflicts=[],
            research_gaps=[f"{failed} worker task(s) failed."] if failed else [],
            recommended_follow_up=[],
        )

    def _verification_report(self, data: dict[str, Any]) -> VerificationReport:
        claims = [Claim.model_validate(item) for item in data.get("claims", [])]
        evidence_ids = set(data.get("evidence_ids", []))
        findings = []
        for claim in claims:
            valid = [item for item in claim.evidence_ids if item in evidence_ids]
            status = VerificationStatus.VERIFIED if valid else VerificationStatus.UNVERIFIED
            findings.append(
                VerificationFinding(
                    claim_id=claim.claim_id,
                    status=status,
                    explanation=(
                        "Referenced demo evidence is present."
                        if valid
                        else "No matching evidence record was supplied."
                    ),
                    supporting_evidence_ids=valid,
                )
            )
        return VerificationReport(findings=findings, summary="Checked every claim reference.")

    def _qa_report(self, data: dict[str, Any]) -> QAReport:
        round_number = int(data.get("round_number", 1))
        findings = data.get("verification_findings", [])
        unsupported = [
            item["claim_id"]
            for item in findings
            if item.get("status") in {"unverified", "contradicted"}
        ]
        needs_follow_up = round_number == 1 and bool(data.get("request_demo_follow_up", True))
        return QAReport(
            quality_score=0.82,
            coverage_score=0.74 if needs_follow_up else 0.9,
            evidence_score=0.8 if not unsupported else 0.55,
            identified_gaps=["Confirm the most important uncertainty."] if needs_follow_up else [],
            contradictions=[],
            unsupported_claims=unsupported,
            follow_up_questions=(
                ["What evidence closes the remaining gap?"] if needs_follow_up else []
            ),
            can_finalize=not needs_follow_up,
        )

    def _follow_up_plan(self, data: dict[str, Any]) -> FollowUpPlan:
        gaps = data.get("identified_gaps", [])
        if not gaps:
            return FollowUpPlan(needed=False, rationale_summary="No important gaps remain.")
        return FollowUpPlan(
            needed=True,
            departments=[
                _department("gap-analysis", "Gap Analysis", "Grace", "; ".join(gaps), 100)
            ],
            rationale_summary="One focused follow-up team can close the remaining gap.",
        )

    def _curation_result(self, data: dict[str, Any]) -> CurationResult:
        candidate = MemoryCandidate.model_validate(data["candidate"])
        supported = bool(candidate.source_evidence_ids) or candidate.memory_type in {
            MemoryType.DECISION,
            MemoryType.PREFERENCE,
        }
        return CurationResult(
            candidate=candidate,
            decision=CurationDecision.SAVE if supported else CurationDecision.TEMPORARY_ONLY,
            rationale_summary=(
                "The concise candidate has evidence."
                if supported
                else "An unsupported demo candidate should remain temporary."
            ),
        )

    def _final_report(self, data: dict[str, Any]) -> FinalReport:
        prompt = str(data.get("prompt", "Research question"))
        findings = [
            VerificationFinding.model_validate(item)
            for item in data.get("verification_findings", [])
        ]
        verified = [item for item in findings if item.status == VerificationStatus.VERIFIED]
        sources = [SourceReference.model_validate(item) for item in data.get("sources", [])]
        return FinalReport(
            title=f"HiveMind research: {prompt[:70]}",
            executive_summary=(
                "The offline demo completed a dynamically planned, governed research run."
            ),
            answer=(
                f"The simulated team produced {len(verified)} verified demo finding(s). "
                "Run with Ollama or OpenAI and web research for a real answer."
            ),
            key_findings=[item.explanation for item in verified] or ["No claim could be verified."],
            risks=["Synthetic demo evidence is not a basis for real decisions."],
            uncertainties=["The demo intentionally performs no external research."],
            recommendations=["Use `hivemind run` with a configured provider for real research."],
            research_limitations=["All demo content is deterministic and synthetic."],
            sources=sources,
        )


def _payload(user_prompt: str) -> dict[str, Any]:
    """Decode runtime-owned JSON, returning a plain prompt for simple calls."""

    try:
        value = json.loads(user_prompt)
    except json.JSONDecodeError:
        return {"prompt": user_prompt}
    return value if isinstance(value, dict) else {"prompt": user_prompt}


def _department(
    role_key: str, name: str, manager_name: str, objective: str, priority: int
) -> DepartmentSpec:
    return DepartmentSpec(
        role_key=role_key,
        name=name,
        manager_name=f"{manager_name} — {name} Manager",
        objective=f"Analyze {name.lower()} for: {objective}",
        rationale_summary=f"{name} addresses a distinct part of this prompt.",
        suggested_tools=["memory_search", "evidence_read"],
        priority=priority,
    )
