# Browser UI

HiveMind's browser UI is a separate localhost application for observing the same runtime used by
the CLI. It can schedule and cancel runs, but it is not a workflow editor: graph dragging and
layout controls never modify agent parents, permissions, plans, or persisted orchestration data.

## Architecture

```text
React + TypeScript
  |-- HTTP: runs, snapshots, selected-agent detail
  `-- WebSocket: snapshot, events, handoffs, run state
                 |
FastAPI app factory
  |-- RunSupervisor --> public runtime composition --> HiveMindRuntime
  |-- LiveBroker (bounded queue per connected client)
  |-- snapshot builder --> SQLite repositories
  `-- built Vite assets when web/dist exists
```

The server is independently composed from `load_settings`, `create_provider`, `EventBus`,
`HiveMindRepository`, `ArtifactStore`, `JsonlEventSink`, and `HiveMindRuntime`. It never imports
private helpers from `cli.py`, and the existing `hivemind` entrypoint is unchanged.

`RunSupervisor` creates and persists a `RunRecord` before placing work on the event loop, which
lets `POST /api/v1/runs` return `202 Accepted` with a stable ID immediately. Each run gets its own
event bus. SQLite and JSONL sinks persist first; the broker sink only calls `put_nowait` on bounded
client queues. A slow client receives a resynchronization instruction instead of blocking model
or tool work. Active tasks and queues are process-local, so run the server with its default one
Uvicorn worker.

## Events versus handoffs

Events answer “what state changed?” Examples include `AGENT_SPAWNED`, structured agent status,
stage changes, retry counts, and tool outcomes. The terminal dashboard and browser reducer both
reconstruct presentation from them; neither parses human-readable event messages for status.

Handoffs answer “what validated public data moved between roles?” The bounded kinds are:

- assignment
- worker report
- manager report
- verification
- quality review
- follow-up
- memory candidate
- final input

The runtime has an optional `RuntimeObserver` with an inert default. Browser composition injects
an observer that persists and publishes `AgentHandoff`; CLI composition needs no change and gains
no extra terminal events. Deterministic handoff IDs make resume/replay an idempotent upsert.

## HTTP and WebSocket protocol

The versioned routes are:

```text
GET  /api/v1/health
GET  /api/v1/public-settings
GET  /api/v1/runs
POST /api/v1/runs
DELETE /api/v1/runs/{run_id}
GET  /api/v1/runs/{run_id}/snapshot
GET  /api/v1/runs/{run_id}/agents/{agent_id}
POST /api/v1/runs/{run_id}/resume
POST /api/v1/runs/{run_id}/cancel
WS   /api/v1/runs/{run_id}/stream
```

New-run JSON uses a forbidden-extra-fields model. Only prompt, project, selected provider/model,
web enablement, and bounded team/round/concurrency controls are accepted. Database paths,
artifact paths, API keys, base URLs, and unknown settings are rejected. Public settings never
return credentials or server paths.

Run deletion is limited to inactive runs. It removes that run's events, tasks, handoffs,
evidence, claims, reports, tool calls, artifact records, and exact artifact directory. Stable
project-scoped agent identities and curated project memory remain available for future runs.

Safe web research defaults on when Ollama or OpenAI is selected so workers receive external,
evidence-linked source material. It remains disabled for the synthetic offline provider. Users
can explicitly turn web research off for a real provider, but the dialog warns that the runtime
will then return uncertainty rather than treat unsupported model knowledge as evidence.

WebSocket messages use explicit envelopes:

```json
{ "type": "snapshot", "data": {} }
{ "type": "event", "data": {} }
{ "type": "handoff", "data": {} }
{ "type": "run_state", "data": {} }
{ "type": "error", "data": {} }
```

The server registers the client's queue before loading the snapshot. It then sends the snapshot,
drains buffered updates through the same loop, and drops IDs already present in that snapshot.
On reconnect the frontend accepts a fresh snapshot as authoritative while preserving a still-valid
pinned selection. Events and handoffs are keyed by their IDs, so reloads do not duplicate nodes,
timeline rows, or data-flow edges.

Snapshot run membership comes only from this run's `AGENT_SPAWNED` events. Stable project agents
that participated in another run are not accidentally displayed. Their profiles enrich those IDs;
events determine their status and counters. Selected-agent details join only that run's tasks,
status history, handoffs, tool calls, evidence summaries, and validated reports.

## Privacy boundary

Handoffs contain concise fields selected from validated plans and reports. Before persistence,
existing redaction removes secret-looking keys and credential forms, then recursive bounds cap
string, collection, and nesting sizes. React renders values as text and never uses
`dangerouslySetInnerHTML`.

The UI deliberately does not show hidden chain-of-thought. Such reasoning is not a reliable public
workflow record and may contain prompt or provider internals. System prompts, complete provider
requests/responses, authorization headers, cookies, tokens, environment secrets, raw fetched
pages, and arbitrary database rows are also excluded. External source excerpts remain untrusted
data under the existing security boundary.

## Development

Install Python and frontend dependencies:

```bash
python -m pip install -e '.[dev,web]'
cd web
npm ci
```

Run development servers in separate terminals:

```bash
hivemind-web                    # 127.0.0.1:8000
cd web && npm run dev           # 127.0.0.1:5173
```

The local Vite server proxies HTTP and WebSocket `/api` traffic. FastAPI CORS allows only the two
localhost Vite origins. The production path is:

```bash
cd web
npm run build
cd ..
hivemind-web                    # serves web/dist at 127.0.0.1:8000
```

If `web/dist` is absent, FastAPI returns a clear build instruction. To run an offline demo, open
the New Run dialog and keep `Fake · offline` selected.

## Tests

```bash
ruff check .
pytest
python evals/run_evals.py

cd web
npm run lint
npm run test -- --run
npm run build
npm ci
```

Backend tests use temporary SQLite databases and the fake provider. They cover scheduling,
snapshots, selected-agent joins, redaction and bounds, handoff deduplication, resume, WebSocket
ordering, slow clients, cancellation, deletion, and additive v1 upgrades. Frontend tests cover reducer
reconstruction and deduplication, live spawn/follow/pinning behavior, structured status, graph
selection, message inspection, edge selection, sidebar controls, and keyboard-accessible safe
controls. Live envelopes are applied in short batches, Dagre reruns only when graph topology
changes, and selected-agent refetches are scoped and debounced.

The timeline uses a horizontally scrollable card-and-marker track. Cards alternate around the
time axis, keep the latest activity in view until the user scrolls back, and retain the existing
agent, type, and severity filters. Collapsing it leaves only a compact bottom bar so the workflow
canvas immediately receives the released vertical space.
