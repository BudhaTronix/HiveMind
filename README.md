# HiveMind

HiveMind is a local-first learning project that demonstrates a dynamic multi-agent research
workflow. A CEO proposes a team for the question, managers divide the work, workers research
focused topics, and verifier and QA roles challenge the result before the CEO writes a final
report. The default real provider is local Ollama; an optional OpenAI adapter is included.

The complete workflow also has a deterministic offline demo. You can learn the architecture,
run the test suite, and inspect saved runs without a model server, API key, or internet access.

> HiveMind is educational software, not a production autonomous company. Its reports may be
> incomplete or wrong and must not be the sole basis for consequential decisions.

## What is an agent here?

An agent is not an operating-system process, a container, or a magical digital employee. In
HiveMind it is an identity, role, prompt, task, permissions, memory scope, status, model call,
and validated result managed by Python. “Spawning” means that Python creates an agent profile,
stores it, and schedules an asynchronous function.

```text
User prompt
    |
    v
CEO plan --> Governor validates limits
    |
    +--> Manager A --> Worker A1 --+
    |             `-> Worker A2 --+--> Manager report --+
    |                                                    |
    `--> Manager B --> Worker B1 ------> Manager report --+
                                                          v
                                               Verifier --> QA
                                                          |
                                      optional follow-up -+
                                                          v
                                            Final report + memory
```

The language model may propose departments, workers, search queries, follow-up work, and memory
candidates. Python controls actual creation, depth and count limits, permissions, tools,
concurrency, retries, timeouts, database writes, approvals, and artifact paths. This separation
is the project’s most important design lesson.

## Install and run the offline demo

HiveMind requires Python 3.11 or newer.

### macOS and Linux

```bash
git clone https://github.com/BudhaTronix/HiveMind.git
cd HiveMind
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
hivemind demo --explain
```

### Windows PowerShell

```powershell
git clone https://github.com/BudhaTronix/HiveMind.git
Set-Location HiveMind
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
hivemind demo --explain
```

The demo’s evidence and citations are synthetic and visibly marked as simulation. Use
`--plain` for log-like output suitable for terminals without live rendering:

```text
12:31:15 [RUN_CREATED] Created run run_...
12:31:15 [AGENT_SPAWNED] CEO Agent joined as ceo.
12:31:15 [PLAN_RECEIVED] CEO requested 2 departments.
12:31:16 [TASK_COMPLETED] Demand Researcher completed its task.
12:31:17 [VERIFICATION_COMPLETED] Verification checked the evidence links.
12:31:17 [RUN_COMPLETED] Run completed with a final report.
```

## Ollama setup and the first real run

1. Install [Ollama](https://ollama.com/) for your operating system and start it.
2. Download the default model with `ollama pull qwen3:8b`.
3. Copy `.env.example` to `.env` if you want to change defaults.
4. Check the installation, then start research:

```bash
hivemind doctor
hivemind run "Should a startup enter the German EV charging market?"
```

Web research is enabled by default. Disable it with `--no-web`. HiveMind uses DuckDuckGo
search results and safely fetches small public text/HTML pages; external content is untrusted
input, never instructions.

### Optional OpenAI provider

Install the normal package, set the key only in your environment or untracked `.env`, and
select the provider:

```bash
export OPENAI_API_KEY="your-key"
hivemind doctor --provider openai
hivemind run "Compare two database migration strategies" --provider openai
```

In PowerShell, use `$env:OPENAI_API_KEY = "your-key"`. Never commit `.env` or paste a key into
a prompt. Provider-specific code is isolated in `src/hivemind/providers/`.

## Browser workflow canvas

The browser dashboard is a second interface; it does not replace or alter any `hivemind`
command. It shows the organization and actual public agent-to-agent handoffs as a live,
interactive graph. Node dragging changes only your local presentation—not the runtime plan,
hierarchy, or permissions.

Prerequisites are Python 3.11+ and Node.js 20 or 22+. Install the optional server dependencies
and frontend packages:

```bash
python -m pip install -e '.[web]'
cd web
npm ci
```

For development, use two terminals from the repository root:

```bash
# Terminal 1: API and WebSocket server
hivemind-web

# Terminal 2: Vite development server
cd web
npm run dev
```

Open `http://127.0.0.1:5173`, choose **New Run**, and leave **Fake · offline** selected for a
complete demo without a model server, API key, web access, or other service. Vite proxies only
the API and WebSocket paths to the local backend.

For a production frontend build served by FastAPI:

```bash
cd web
npm run build
cd ..
hivemind-web
# Open http://127.0.0.1:8000
```

For Ollama, start Ollama and pull the model before selecting it in the dialog. For OpenAI, set
`OPENAI_API_KEY` in the backend process environment; credentials are intentionally absent from
all browser requests and responses. `hivemind-web` binds to `127.0.0.1` and uses one Uvicorn
worker by default. The active task registry and live broker are process-local, so multi-worker
serving is not supported in this educational version. See [Web UI](docs/WEB_UI.md) for the
protocol, privacy boundary, and development architecture.

## Command reference

```text
hivemind demo [PROMPT] [--plain] [--explain]
hivemind doctor [--provider ollama|openai|fake] [--model MODEL]
hivemind run PROMPT [--project ID] [--provider ...] [--model ...]
                    [--no-web] [--plain] [--explain]
                    [--max-managers N] [--max-workers N]
                    [--max-rounds N] [--max-concurrent N]
hivemind resume RUN_ID [--plain] [--explain]
hivemind status RUN_ID
hivemind runs list [--limit N]
hivemind agents list [--project ID]
hivemind agents show AGENT_ID
hivemind memories list --project ID
hivemind memories search QUERY --project ID
```

Command-line options override `.env` values. Run any command with `--help` for details. Ordinary
setup failures produce a short actionable message; add `--debug` to `demo`, `run`, or `resume`
when developing and you need a traceback.

## Saved state, checkpoints, and inspection

SQLite stores projects, runs, stable agents, tasks, events, evidence, claims, reports, memories,
artifacts, and tool-call records in `data/hivemind.db`. Every meaningful transition is recorded.
After interruption, `hivemind resume RUN_ID` schedules the workflow again but reuses each valid,
completed stage output instead of repeating that provider call. If a run was already complete,
the saved final checkpoint is returned directly.

`hivemind status RUN_ID` reconstructs the organization and recent activity from persisted events,
even in a new process. `runs/RUN_ID/` contains:

```text
user_prompt.txt       plan.json             events.jsonl
evidence.json         verification.json     qa_report.json
final_report.json     final_report.md        run_summary.json
```

Final sources are filtered against real evidence IDs before writing. Findings are rendered as
verified, partial, uncertain, or contradicted rather than being flattened into false confidence.
Generated databases and run directories are ignored by Git.

## Memory

Memory is retrieved text, not model training. Workers and managers can suggest candidates, but a
separate curator accepts only useful, evidence-linked records. Records have project, agent, role,
or global scope; retrieval sends a small relevant selection, never the whole database. The
default SQLite store combines keyword matching, confidence, and recency and falls back cleanly
when SQLite FTS5 is unavailable.

An experimental Mem0 backend is isolated behind the same interface:

```bash
python -m pip install -e '.[mem0]'
ollama pull nomic-embed-text
# Set HIVEMIND_MEMORY_BACKEND=mem0 in .env
```

The optional integration targets `mem0ai` 2.x and uses local Ollama plus a local Qdrant path.
The default install, demo, tests, and evaluations do not require Mem0.

## Configuration

Copy `.env.example` to `.env` and edit only what you need. Important defaults include:

```dotenv
HIVEMIND_PROVIDER=ollama
OLLAMA_MODEL=qwen3:8b
OLLAMA_THINK=false
HIVEMIND_ENABLE_WEB=true
HIVEMIND_MEMORY_BACKEND=simple
HIVEMIND_MAX_MANAGERS=3
HIVEMIND_MAX_WORKERS_PER_MANAGER=3
HIVEMIND_MAX_TOTAL_AGENTS=15
HIVEMIND_MAX_CONCURRENT_LLM_CALLS=3
HIVEMIND_MAX_RESEARCH_ROUNDS=2
HIVEMIND_LLM_CALL_TIMEOUT_SECONDS=300
```

Per-role model overrides are available as `HIVEMIND_MODEL_CEO`, `HIVEMIND_MODEL_MANAGER`,
`HIVEMIND_MODEL_WORKER`, `HIVEMIND_MODEL_VERIFIER`, `HIVEMIND_MODEL_QA`, and
`HIVEMIND_MODEL_MEMORY`. Ollama thinking is disabled by default because this workflow needs
concise schema-shaped results rather than long reasoning traces. Set `OLLAMA_THINK=true` only
when you deliberately want the extra local inference time.

## Development and evaluations

```bash
python -m pip install -e '.[dev,web]'
ruff check .
pytest
python evals/run_evals.py

cd web
npm ci
npm run lint
npm run test -- --run
npm run build
```

Tests use temporary databases and injected fake providers/web clients. They do not contact
Ollama, OpenAI, or the live web. Evaluations cover factual, market, technical, ambiguous,
conflicting, failure, offline, memory, follow-up, and limit-clamping scenarios. They validate
workflow invariants rather than asking another model to subjectively grade prose.

## Learn and troubleshoot

- [Architecture](docs/ARCHITECTURE.md) explains control flow, contracts, and intentional limits.
- [Web UI](docs/WEB_UI.md) explains the browser canvas, live protocol, and privacy boundary.
- [Learning guide](docs/LEARNING_GUIDE.md) teaches the underlying concepts in order.
- [Code map](docs/CODE_MAP.md) points from each concept to its implementation.
- [Walkthrough](docs/WALKTHROUGH.md) follows one prompt from CLI to artifacts.
- [Memory](docs/MEMORY.md) covers scopes, retrieval, curation, and Mem0.
- [Security](docs/SECURITY.md) documents trust boundaries and permissions.
- [Troubleshooting](docs/TROUBLESHOOTING.md) covers common setup and runtime errors.
- [Glossary](docs/GLOSSARY.md) defines unfamiliar terms.

## Limitations

Version 1 is a single Python process with SQLite and bounded three-level organization. Its live
browser broker supports one Uvicorn worker; it is not a multi-user or remotely exposed service.
It has no distributed scheduler, shell/filesystem tools for agents, general autonomous tool loop,
or production human-approval interface. Keyword memory is intentionally simple. DDGS may be
unavailable or rate-limited. Local model quality depends strongly on model and hardware.
Structured validation, verification, and citations reduce mistakes but cannot guarantee truth.

See [ROADMAP.md](ROADMAP.md) for deliberately deferred production-oriented upgrades.

## License

MIT © 2026 Budhaditya Mukhopadhyay.
