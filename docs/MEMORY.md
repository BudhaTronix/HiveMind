# Memory

HiveMind memory is durable, scoped context. It is deliberately separate from model weights and
from the uncurated transcript of a run.

## Lifecycle

```text
worker/manager suggests candidate
             |
             v
memory curator: accept, reject, or supersede
             |
      evidence link exists?
             |
             v
SQLite MemoryRecord --> scoped retrieval --> small future prompt excerpt
```

Workers and managers cannot directly write durable memory. The curator considers usefulness,
confidence, provenance, scope, duplication, and whether referenced evidence exists. Every
decision is persisted as an event. Accepted records include ID, text, memory type, scope,
scope ID, confidence, evidence IDs, source run, status, and timestamps.

## Scopes and types

Scopes prevent accidental cross-project leakage:

- project memory belongs to one project;
- agent memory belongs to one stable agent;
- role memory can apply to a role within its scope identifier;
- global memory is available only when explicitly requested.

Memory types distinguish facts, decisions, preferences, lessons, source notes, and summaries.
The current runtime primarily retrieves project and role-appropriate records rather than
dumping every scope into every prompt.

## Default SQLite retrieval

`SimpleSQLiteMemoryStore` asks the repository for active records in the allowed scopes. SQLite
FTS5 narrows candidates when available; a normal text query is the portable fallback. Python
then ranks records by:

```text
4 × keyword overlap + 2 × confidence + recency
```

Only a small top-ranked list enters a prompt. This transparent baseline is easy to debug,
requires no embeddings, and works in the offline demo.

## Memory is not training

Training modifies a model’s internal numeric weights. HiveMind never does that. It writes text
records to storage, finds relevant records later, and adds them to that request’s context. Delete
or deactivate the record and future prompts stop receiving it; the model itself was unchanged.

## Optional Mem0 adapter

`Mem0MemoryStore` is isolated so the default dependency set remains small. It mirrors approved
records into Mem0 while SQLite remains the source used by HiveMind’s inspection CLI. The
integration targets `mem0ai>=2.0.16,<3`, local Ollama for generation and embeddings, and a local
Qdrant directory.

```bash
python -m pip install -e '.[mem0]'
ollama pull qwen3:8b
ollama pull nomic-embed-text
```

Then set:

```dotenv
HIVEMIND_MEMORY_BACKEND=mem0
HIVEMIND_MEM0_EMBED_MODEL=nomic-embed-text
```

Mem0 is optional and experimental in this project. Default tests do not install it or require
its service dependencies.

## Inspecting memory

```bash
hivemind memories list --project demo-project
hivemind memories search "market demand" --project demo-project
```

For deterministic tests, inject a `MemoryStore` into `HiveMindRuntime`; do not make tests
depend on a live vector database or embedding model.
