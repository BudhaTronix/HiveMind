# Glossary

**agent**  
An identity, role, task, permissions, status, model call, and result managed by HiveMind. It is
not necessarily a process or separate model.

**artifact**  
A human- or machine-readable file produced by a run, such as `plan.json` or
`final_report.md`.

**async**  
Python syntax and execution behavior that lets other work continue while an operation waits,
usually for a model, database, or network response.

**checkpoint**  
Persisted progress that allows a later resume to reuse valid completed outputs.

**claim**  
A statement in a worker or manager report. A claim should reference the evidence IDs that
support it.

**concurrency**  
Multiple tasks making progress during overlapping time. HiveMind uses it for independent model
and web requests.

**context**  
The instructions and data visible to a model for one call: prompt, task, selected memory, and
permitted evidence.

**embedding**  
A numeric representation used to compare semantic similarity. The default memory store does
not require embeddings; the optional Mem0 setup does.

**evidence**  
A stored source record with provenance, excerpt, retrieval details, and an ID that claims can
reference.

**event**  
A typed record of something that happened, such as a stage change, tool call, retry, or task
completion.

**FTS5**  
SQLite’s optional full-text-search extension. HiveMind uses it when available and has a normal
text-query fallback.

**governor**  
Deterministic Python policy that validates and clamps model-proposed teams and work to configured
limits.

**LLM**  
Large language model: a system that generates text or structured data from supplied context.

**memory**  
A curated durable text record retrieved into a later prompt. It is external context, not a
change to model weights.

**model**  
The particular trained language system used by a provider, such as `qwen3:8b`.

**orchestration**  
Program logic that sequences roles, schedules tasks, applies limits, gathers results, and
handles failures.

**prompt**  
The instructions and input sent to a model for one generation.

**provider**  
An adapter that knows how to call a model system. HiveMind includes Fake, Ollama, and OpenAI
providers.

**provenance**  
Information about where data came from, including source URL or run and retrieval time.

**replanning**  
A bounded second planning step used only when QA identifies focused gaps and another round is
allowed.

**retrieval**  
Selecting a small relevant set of stored memory or evidence for current work.

**schema**  
A machine-checkable definition of fields, types, values, and constraints. HiveMind schemas are
Pydantic models.

**semaphore**  
A concurrency counter. A task waits when all allowed slots are occupied.

**structured output**  
Model output parsed and validated into a schema instead of accepted as arbitrary prose.

**task**  
One run-specific unit of work assigned to an agent, with status, attempts, and typed output.

**token**  
A small unit of text processed by a language model. Cost and context limits are commonly
measured in tokens.

**tool**  
A registered Python operation with metadata and role permissions, such as public web fetch or
scoped memory search.

**untrusted content**  
External text that may contain errors or malicious instructions. HiveMind labels it as data and
does not grant it program authority.

**verification**  
Checking whether claims are supported by the evidence they cite and recording a visible state.

**worker**  
The leaf research role under a manager. Workers cannot spawn descendants.
