# Roadmap

HiveMind version 1 deliberately optimizes for learning: one Python process, explicit async
functions, SQLite, inspectable events, three organizational levels, and no mandatory external
service. Future work should preserve those transparent defaults.

## Near-term learning improvements

- Add more deterministic fake-provider cases and artifact snapshot tests.
- Show provider latency and token metadata consistently when each SDK exposes them.
- Add read-only CLI exports for tasks, evidence, claims, and tool calls.
- Add an interactive but fail-closed approval gate demonstration.
- Improve accessibility and narrow-terminal behavior in the Rich dashboard.
- Publish small tutorials that replace one dependency at a time.

## Storage and retrieval

- Offer PostgreSQL repositories for multi-process and multi-user deployments.
- Add optional semantic vector search while retaining the SQLite keyword baseline.
- Exercise the isolated Mem0 adapter in a separate integration-test profile.
- Define retention, supersession, backup, and migration policies for long-lived memory.

## Observability and orchestration

- Export traces and metrics through OpenTelemetry.
- Evaluate LangGraph or Temporal for durable workflows without hiding policy decisions.
- Add distributed task queues only with idempotency, leases, cancellation, and budgets.
- Drive a browser dashboard from the same typed event stream.

## Tools and agent interoperability

- Add MCP tools behind the existing registry, permissions, and approval boundary.
- Explore A2A agent services with authentication, provenance, and explicit data contracts.
- Add sandboxed code execution only after resource, filesystem, and network isolation are
  designed and tested.

## Governance

- Build a real human approval interface for consequential actions.
- Add per-project budgets, provider spending limits, tenant isolation, and audit export.
- Research deeper but still bounded hierarchies with explicit termination proofs and cost
  visibility.

Unlimited recursion, unrestricted shell access, fabricated citations, hidden reasoning capture,
and mandatory cloud dependencies are not roadmap goals.
