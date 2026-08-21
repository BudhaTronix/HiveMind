# Architecture

HiveMind version 1 is a single-process, event-driven Python application. The design keeps model
suggestions separate from program authority: providers generate proposals and typed reports,
while the runtime validates, schedules, persists, and presents them.

## Control flow

```text
Typer CLI --------------------------> Rich/plain renderer
   |                                          ^
   |                                          |
   +--> Settings --> Provider --> Runtime <--> Event bus --> SQLite / JSONL
                                  |   |
Browser API --> Run supervisor ---+   `--> bounded live broker --> WebSocket --> React canvas
                                  |
                                  `--> Handoff observer --> SQLite --> live broker
                                       (validated public transfers only)
```

The organization depth is fixed at CEO → Manager → Worker. Verifier, QA, and memory curator are
support roles and cannot create descendants. One Python event loop runs the workflow; agents are
records and asynchronous model calls, not independent services.

## Components and ownership

- `cli.py` composes settings, storage, provider, event bus, renderer, and runtime. CLI values
  are applied after environment settings.
- `runtime.py` owns the workflow state machine. It creates approved profiles, schedules work,
  links evidence, runs verification and QA, permits a bounded follow-up, curates memory, and
  writes final artifacts.
- `governor.py` deterministically clamps model-proposed plans to manager, worker, total-agent,
  search-query, concurrency, retry, and round limits.
- `agents.py` contains role-specific, schema-validated provider calls. It does not schedule the
  organization.
- `providers/` isolates Fake, Ollama, and OpenAI SDK details behind `LLMProvider`.
- `persistence.py` owns SQLite repositories, artifact files, and the JSONL event sink.
- `registry.py` gives a project/role pair a stable agent identity across runs.
- `memory.py` implements scoped retrieval and durable writes behind `MemoryStore`.
- `tools.py` owns the explicit registry and bounded tool handlers.
- `security.py` validates public URLs, rejects local/private targets, wraps outside content,
  limits excerpts, and supplies redaction helpers with `events.py`.
- `events.py` fans immutable typed events out to storage and presentation.
- `terminal_ui.py` derives its visible state from those events.
- `observability.py` defines bounded, redacted, idempotent public handoffs and the optional
  runtime observer. Its default is a no-op, so CLI composition and output are unchanged.
- `web/` composes a separate FastAPI service, task supervisor, snapshot builder, bounded live
  broker, and WebSocket protocol without importing CLI helpers.
- top-level `web/` contains the strict TypeScript React canvas and its deterministic reducer.

## Data and public contracts

Important data crossing a boundary is a Pydantic v2 model in `schemas.py`. Plans, worker
reports, claims, evidence, verification, QA, memory, events, tasks, metrics, and final reports
are validated before orchestration trusts them. Statuses and kinds are enums, timestamps are
UTC, and IDs are collision-resistant.

`LLMProvider` offers asynchronous text and structured generation. Structured generation
validates against the requested Pydantic model; provider adapters attempt one repair after
invalid output and then raise an actionable `ProviderError`.

The runtime accepts its provider, repository, event bus, governor, registry, tool registry,
memory store, artifact store, and optional observer as small injected dependencies. This makes
failure behavior testable without live services.

## Two observability streams

`HiveEvent` records lifecycle and state: stages, spawns, statuses, retries, tool activity, and
terminal outcomes. Both terminal and browser presentation reconstruct state from these public
records. `AgentHandoff` records concise validated data that genuinely crossed an agent boundary,
such as an assignment or worker report. Handoffs are separate so the terminal event stream and
existing CLI output do not change merely to support a browser.

Handoff IDs derive from the run, round, source, target, kind, and task key. Replaying a resume
therefore upserts rather than duplicates them. Recursive collection and text bounds plus the
existing redaction functions prevent the preview from becoming a provider-data or external-page
dump. No contract captures hidden reasoning, system prompts, provider bodies, or secrets.

## Scheduling and resilience

Manager planning calls run concurrently. Approved worker calls within and across departments
also run concurrently, all sharing one bounded LLM semaphore. Web operations share a separate
semaphore. Per-task exception isolation means one worker can fail without discarding successful
siblings. Calls have retries with backoff and per-call timeouts; the full run has a hard deadline.

Each stage emits status events and saves typed outputs. A resume starts stage scheduling again,
but deterministic task keys allow valid completed task outputs for that run and round to be
reused. A completed run has a final checkpoint that can be returned immediately. This approach
is deliberately understandable rather than a hidden workflow engine.

## Evidence and report integrity

Web search only discovers candidate URLs. Python fetches each page through URL validation,
converts accepted public text/HTML into a bounded untrusted excerpt, and creates an evidence
record. Models receive short evidence aliases that Python resolves back to stored IDs, avoiding
copy errors from long identifiers. Claims refer to those resolved IDs. Before artifacts are
written, references that do not exist in the run’s evidence set are rejected. Python also
rejects unknown claim IDs and downgrades “verified” findings that contain no valid supporting
evidence. Final key findings use the real claim text and remain visibly labelled as `verified`,
`partially verified`, `unverified`, or `contradicted`.

This establishes traceability, not truth. A source can itself be wrong, and a model can
misinterpret it.

## Persistence

SQLite tables store schema metadata, projects, runs, agents, tasks, events, handoffs, evidence,
claims, reports, memories, artifacts, and tool calls. The handoff table is an additive schema-v2
upgrade; opening an existing v1 database preserves its records. JSON is used for typed payload
snapshots where a relational expansion would make this educational version harder to follow.
Per-run artifacts make the same information easy to inspect outside SQLite.

## Intentional version 1 exclusions

Version 1 does not include PostgreSQL, a distributed queue, autonomous service-to-service
agents, unlimited recursive hierarchies, a generic model-directed tool loop, shell or filesystem
agent tools, browser automation, hidden chain-of-thought capture, multi-user web serving, or
production authorization and tenancy. No external service is mandatory for the demo or tests.

Possible future upgrades include:

- PostgreSQL for multi-user and higher-throughput state.
- Semantic vector search and a full Mem0 deployment.
- OpenTelemetry traces and metrics export.
- LangGraph or Temporal for durable production workflows.
- MCP tools and A2A agent services with explicit trust boundaries.
- Distributed task queues and independently scalable workers.
- Durable multi-process browser streaming backed by an external broker.
- Sandboxed code execution.
- Deeper but still bounded recursion.
- A real human approval interface for consequential actions.

These are roadmap items, not missing prerequisites for understanding the current system.
