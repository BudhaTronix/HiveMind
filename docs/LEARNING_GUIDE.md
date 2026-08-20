# Learning Guide

This guide introduces the ideas in the same order that a new reader needs them. Keep
`hivemind demo --plain` open while reading: its event lines make each concept concrete.

## 1. What is an LLM?

A large language model (LLM) predicts useful sequences of text from the context it receives.
It can propose a plan or write a report, but it does not automatically create Python objects,
call tools, or save data. HiveMind uses an LLM as a fallible reasoning and text component.

Example: given “study the EV charging market,” a model may suggest demand, competition, and
regulation departments. Python still decides whether those departments are allowed.

## 2. What is a prompt?

A prompt is the text supplied to a model. It combines role instructions, the current task, small
relevant memory excerpts, and any evidence the role may use. Prompts are assembled in
`prompts.py`; user and web text are treated as data rather than trusted system instructions.

## 3. What is structured output?

Free-form text is difficult for a program to trust. Structured output asks the model for data
that must fit a schema, such as a `CompanyPlan` containing a list of `DepartmentSpec` values.
Pydantic checks types, required fields, lengths, and enum values. An adapter attempts one repair
when validation fails and then reports a clear error.

```text
untrusted model response -> Pydantic schema -> accepted object OR validation error
```

## 4. What is an agent in HiveMind?

An agent is an application-level record plus one role-specific operation. It has an ID, name,
role, objective, parent, memory scope, permissions, status, task, model call, and result. It is
not automatically a separate process, model, or machine.

A project’s “market manager” keeps a stable profile ID across runs, while each assigned task has
its own run-specific record.

## 5. What is orchestration?

Orchestration is the Python logic that decides what happens, in what order, and under which
limits. `HiveMindRuntime` invokes the CEO planner, validates the plan, schedules managers and
workers, collects partial results, verifies claims, runs QA, optionally follows up, curates
memory, and synthesizes the final report.

The model suggests content. The orchestrator owns control flow.

## 6. What does “spawning an agent” actually mean?

Spawning means:

1. validate a proposed role;
2. get or create an `AgentProfile`;
3. persist the profile and emit an `AGENT_SPAWNED` event;
4. create a task record;
5. schedule an async role function.

No subprocess, virtual machine, or unlimited child hierarchy appears. Only CEO → Manager →
Worker descendants are permitted.

## 7. What is asynchronous execution?

`async` lets one Python process make progress on other tasks while a model or HTTP request is
waiting. If three independent workers are ready, the runtime schedules all three. When worker A
waits for a response, worker B can continue.

This is concurrency, not necessarily parallel CPU computation. It is especially useful for
network-bound work.

## 8. What is a semaphore?

A semaphore is a counter that limits how many operations may run at once. If the LLM semaphore
has capacity three, a fourth ready model call waits until one slot is released.

```text
ready calls: A B C D
three slots: [A] [B] [C]   D waits
```

HiveMind has separate limits for model calls and web requests. This protects local hardware,
remote quotas, and the sites being researched.

## 9. What is a tool?

A tool is a named Python function with metadata and an allowed-role list. Version 1 registers
web search, safe web fetch, scoped memory search, and evidence read. The runtime—not a free-form
model loop—chooses when to execute approved search queries.

`ToolRegistry.execute` checks role permissions first. Tools marked consequential would also go
through `ApprovalGate`, which rejects by default unless an application supplies approval.

## 10. What is evidence?

Evidence is a saved record of where information came from. A web evidence record includes its
URL, title, bounded excerpt, retrieval time, source kind, and an evidence ID. Offline demo
evidence is explicitly marked synthetic.

Claims contain evidence IDs rather than invented footnote text. The artifact writer removes
references that do not exist in the run.

## 11. What is verification?

Verification checks whether a claim is actually supported by the evidence IDs it cites. The
verifier marks findings `verified`, `partial`, `uncertain`, or `contradicted` and explains
gaps. QA then checks coverage, coherence, unresolved contradictions, and whether focused
follow-up is worthwhile.

Verification improves traceability; it cannot prove that every source is true.

## 12. What is memory?

Memory is a small durable record retrieved into a future prompt. A memory might say that a
source was unreliable, that a project prefers a comparison format, or that an evidence-backed
finding should be reused. Records have scopes, confidence, provenance, status, and timestamps.

The default store ranks matching scoped records using keyword overlap, confidence, and recency.

## 13. Why memory does not change model weights

Training changes the numeric parameters inside a model. HiveMind does not train models. It saves
text in SQLite (and optionally mirrors it to Mem0), later retrieves a few records, and inserts
them into a prompt. The model sees the text only as current context.

```text
saved memory -> retrieval -> prompt context -> model response
model weights --------------------------------> unchanged
```

## 14. What is checkpointing?

Checkpointing records progress so an interrupted run does not need to repeat valid completed
work. HiveMind saves every task, report, event, and run stage. On resume, deterministic task
keys locate completed typed outputs for the same run and round. Failed or missing work runs
again; valid work is reused.

This is stage-level recovery, not a byte-for-byte snapshot of the Python process.

## 15. What is the governor?

The governor is deterministic Python policy. It clamps the number of departments, workers,
agents, queries, rounds, retries, and concurrent operations. A model can request five managers,
but if the configured maximum is three, only three are approved and a governor event explains
the reduction.

The governor turns suggestions into bounded executable plans.

## 16. Why unlimited recursion is dangerous

If every agent could create any number of children, a small prompt could cause exponential work,
high bills, long runtimes, and an organization nobody can inspect. Unlimited replanning can also
repeat forever.

HiveMind fixes depth at three organizational levels and defaults to at most one follow-up round
(two total research rounds). Support roles cannot spawn children. More depth should only be
introduced with explicit budgets, termination rules, and observability.

## 17. How the terminal UI receives events

The runtime emits typed `HiveEvent` values to an `EventBus`. Subscribers receive the same
events:

```text
Runtime -> EventBus -> Rich live renderer
                    -> SQLite repository
                    `-> runs/RUN_ID/events.jsonl
```

The terminal UI builds its agent tree, statuses, retries, tool activity, rounds, elapsed time,
metrics, and recent-event list from this stream. `hivemind status` can later read persisted
events and reconstruct a similar view. Presentation does not secretly control orchestration.

## Continue learning

Follow [WALKTHROUGH.md](WALKTHROUGH.md) for a concrete run, then use
[CODE_MAP.md](CODE_MAP.md) to find each implementation. Change a governor limit or fake-provider
response, run the tests, and observe how the event log changes.
