# One Run, Start to Finish

Follow the prompt “Should a startup enter the German EV charging market?” through a demo. The
fake provider makes the example repeatable, but it exercises the same runtime and schemas used
by Ollama and OpenAI.

## 1. CLI entry

`hivemind demo --plain` enters `demo()` in `src/hivemind/cli.py`. It loads settings with the
`fake` provider and web disabled, then `_execute_new_run()` creates:

- `HiveMindRepository` for SQLite;
- `ArtifactStore` for the run directory;
- the provider from `create_provider()`;
- an `EventBus` and `TerminalRenderer`;
- `HiveMindRuntime` with those dependencies.

The renderer, database event saver, and JSONL sink all subscribe to the event bus before the run
starts.

## 2. Run creation

`HiveMindRuntime.run()` applies the whole-run timeout and enters `_run_workflow()`. It creates a
`RunRecord`, project row, artifact directory, and `RUN_CREATED` event. `AgentRegistry` returns
the project’s stable CEO profile or creates it on the first run.

## 3. CEO plan

`run_ceo_planner()` in `agents.py` sends the prompt and a small selection of project memory to
the provider. Structured output must validate as `CompanyPlan`. For this prompt the fake
provider proposes market-demand and competition/regulation departments; a technical prompt
produces a different organization.

## 4. Governor validation

`Governor.validate_company_plan()` clamps the proposal to configured budgets. It trims excess
departments and later validates each manager’s worker plan and search queries. Reductions emit a
`GOVERNOR_DECISION` event. The LLM cannot bypass this step by asking for a larger team in prose.

## 5. Manager creation

`_run_departments()` gets or creates one stable manager profile for every approved department.
The profiles link to the CEO as parent. Independent `run_manager_planner()` calls can overlap,
but all provider calls pass through the shared semaphore in `AgentExecutor`.

## 6. Worker creation

Each validated `WorkerPlan` contains focused `WorkerSpec` values. Python creates only those
that fit depth, per-manager, and total-agent limits. Worker profiles link to their manager. A
failed worker becomes a failed task and event; its successful siblings continue.

## 7. Web research

In a real run, `_research_worker()` executes only the approved bounded queries through
`ToolRegistry`. `WebSearchTool` returns candidate URLs. `WebFetchTool` validates DNS and the
URL before each request and redirect, rejects private/local targets and unsupported content,
limits response bytes, removes scripts/styles, and returns an `<untrusted_source>` excerpt.

The demo instead creates clearly labelled synthetic evidence, so it never calls the network.
Both paths produce typed `Evidence` rows with stable IDs.

## 8. Worker and manager reports

`run_worker()` receives the task plus permitted evidence and returns a validated
`WorkerReport`: summary, claims linked to evidence IDs, limitations, and optional memory
candidates. `run_manager_synthesis()` merges the department’s successful worker results into a
`ManagerReport`. Nonexistent evidence references are removed before persistence.

## 9. Verification

The runtime creates a support verifier and calls `run_verifier()` with manager claims and the
evidence set. Every `VerificationFinding` records a state and rationale. The JSON result is
saved to SQLite and `verification.json`.

## 10. QA and bounded replanning

`run_qa()` assesses coverage, contradictions, evidence gaps, and report readiness. If it asks
for follow-up and another configured round remains, `run_ceo_follow_up_planner()` proposes only
focused gap-filling work. The governor validates that plan, the runtime runs the second round,
and verification and QA run again. With the default maximum of two rounds, there can be at most
one follow-up. There is no unbounded reflection loop.

## 11. Memory curation

Workers and managers only propose `MemoryCandidate` values. `run_memory_curator()` decides
whether each candidate is useful, appropriately scoped, non-duplicative, and linked to evidence.
The runtime writes accepted `MemoryRecord` values through `MemoryStore` and emits a decision
event for every candidate.

## 12. Final synthesis

`run_final_synthesis()` receives the prompt, manager reports, verification, QA, and evidence.
It returns a `FinalReport` with an answer, findings, limitations, confidence, and source
references. Python filters the source list against evidence actually saved for this run. The
fake provider’s output is plainly identified as an offline simulation.

## 13. Artifact creation and later inspection

`_write_final_artifacts()` and `ArtifactStore` produce the prompt, plan, event log, evidence,
verification, QA, final JSON/Markdown, and run summary under `runs/RUN_ID/`. The run stage
becomes `completed`, metrics are saved, and `RUN_COMPLETED` reaches every event subscriber.

Use:

```bash
hivemind status RUN_ID
hivemind agents list --project demo-project
hivemind memories list --project demo-project
hivemind resume RUN_ID --plain
```

Status reconstructs state from events. Resume returns a complete checkpoint immediately or
reuses valid completed task outputs while filling gaps in an interrupted run.
