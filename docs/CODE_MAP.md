# Code Map

Start at the CLI, then follow the runtime. The table maps concepts to their main implementation;
tests beside each area show intended behavior.

| Concept | Main file | What to look for |
|---|---|---|
| User commands | `src/hivemind/cli.py` | Typer commands and dependency composition |
| Configuration | `src/hivemind/config.py` | Pydantic settings and CLI precedence |
| Pydantic contracts | `src/hivemind/schemas.py` | Models, statuses, stages, and event enums |
| Dynamic orchestration | `src/hivemind/runtime.py` | Workflow stages, scheduling, follow-up, artifacts |
| Agent execution | `src/hivemind/agents.py` | One typed function for each role |
| Agent prompts | `src/hivemind/prompts.py` | Role instructions and untrusted-data boundaries |
| Limits | `src/hivemind/governor.py` | Deterministic validation and clamping |
| Persistent employees | `src/hivemind/registry.py` | Stable project-scoped identities |
| SQLite state | `src/hivemind/persistence.py` | Tables, repositories, checkpoints, artifact store |
| Memory | `src/hivemind/memory.py` | SQLite ranking and optional Mem0 adapter |
| Web research and tools | `src/hivemind/tools.py` | Registry, permissions, DDGS, safe HTTP |
| URL safety | `src/hivemind/security.py` | SSRF blocking and untrusted-content wrapping |
| Events and redaction | `src/hivemind/events.py` | Fan-out event bus and safe persisted text |
| Terminal dashboard | `src/hivemind/terminal_ui.py` | Event-derived live/plain/explain renderers |
| Provider contract | `src/hivemind/providers/base.py` | Protocol, validation, and repair behavior |
| Offline simulation | `src/hivemind/providers/fake_provider.py` | Deterministic prompt-sensitive responses |
| Ollama integration | `src/hivemind/providers/ollama_provider.py` | Local model calls and health checks |
| OpenAI integration | `src/hivemind/providers/openai_provider.py` | Responses structured parsing |
| Deterministic evaluations | `evals/run_evals.py` | Workflow-invariant evaluation table |
| Unit/integration tests | `tests/` | Temporary, offline behavior checks |

## Suggested reading path

1. Read `schemas.py` to learn the vocabulary.
2. Run `hivemind demo --plain` and watch the event sequence.
3. Read the top half of `runtime.py`, following each called role function into `agents.py`.
4. Inspect `governor.py`, then the concurrency and failure-handling tests.
5. Follow one event from `events.py` to SQLite, JSONL, and `terminal_ui.py`.
6. Read `tools.py` together with `security.py`.
7. Finish with persistence/resume and memory curation.

There is no generated framework code or hidden orchestration layer. The explicit calls are the
architecture.
