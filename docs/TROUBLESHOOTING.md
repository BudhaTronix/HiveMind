# Troubleshooting

Start with:

```bash
hivemind doctor
hivemind demo --plain
```

The first command checks Python, directories, SQLite capabilities, provider configuration, and
provider health. The second isolates orchestration from model and network setup.

## `hivemind: command not found`

Activate the virtual environment and reinstall the editable package:

```bash
source .venv/bin/activate
python -m pip install -e .
python -m hivemind --help
```

PowerShell activation is `.venv\Scripts\Activate.ps1`. If script execution is restricted,
follow your organization’s PowerShell policy rather than disabling security globally.

## Python is too old

Run `python --version`. HiveMind needs Python 3.11+. Create the virtual environment with the
newer interpreter, delete no project data, and reinstall.

## Ollama is unreachable

Confirm that Ollama is installed and running:

```bash
ollama list
ollama pull qwen3:8b
hivemind doctor --provider ollama
```

If Ollama listens somewhere else, set `OLLAMA_BASE_URL`. If the configured model is missing,
pull it or pass `--model`.

## OpenAI key is missing

Set `OPENAI_API_KEY` in your shell or untracked `.env`, then run
`hivemind doctor --provider openai`. Do not add the key to `.env.example`, source code, a
prompt, or a bug report.

## Structured output is invalid

The adapter already makes one repair attempt. Repeated failures usually mean the selected local
model does not reliably follow the schema or its context is overloaded. Try a stronger model,
reduce the prompt, or reproduce with `hivemind demo`. Use `--debug` only when you need the
developer traceback.

## Web search or fetch fails

DDGS can be rate-limited or temporarily unavailable. A site may block automated clients, return
an unsupported content type, exceed limits, redirect too often, or resolve to a prohibited
network. The worker records a bounded failure and other work continues. Retry later or use
`--no-web` to test model-only orchestration.

HiveMind intentionally refuses localhost, LAN, private, link-local, and non-HTTP(S) URLs. Do not
weaken this merely to make an internal URL fetch succeed.

## A run stopped or timed out

List and inspect saved state:

```bash
hivemind runs list
hivemind status RUN_ID
hivemind resume RUN_ID --plain
```

Resume reuses valid completed task outputs. Increase `HIVEMIND_MAX_RUNTIME_SECONDS` only after
checking for a slow/unhealthy provider and an unexpectedly large plan.

## SQLite reports locking or permission errors

Keep the database on a writable local filesystem, avoid running many independent HiveMind
processes against the same file, and check the parent directory shown by `hivemind doctor`.
For an isolated experiment, point `HIVEMIND_DB_PATH` and `HIVEMIND_RUNS_DIR` to new paths.
Never delete a database that contains work you need; copy it before diagnosis.

## Memory search returns nothing

Memory is curated, so a run may legitimately save none. Check the project ID and use
`hivemind memories list --project ID`. Search is scope-aware and does not leak records from a
different project. The SQLite backend works without FTS5 by using its fallback.

For Mem0, install `.[mem0]`, pull both configured Ollama models, and check Ollama. Switch back to
`HIVEMIND_MEMORY_BACKEND=simple` to isolate the optional adapter.

## Live display looks broken

Use `--plain` in CI, redirected output, minimal terminals, or screen readers. The same events
are still stored in SQLite and `events.jsonl`, and `hivemind status RUN_ID` reconstructs state
afterward.

## Clean diagnostic report

When filing an issue, include Python and OS versions, the command without secrets, provider/model
names, `hivemind doctor` output, and fake-provider reproduction if possible. Never attach a
private database or real `.env`.
