# Security Model

HiveMind is an educational local application, but it still treats models, prompts, and the web
as untrusted inputs. Python remains the authority at every side-effect boundary.

## Trust boundaries

- A model proposes typed data; Pydantic validates it and the governor applies hard limits.
- A worker may receive web text; the prompt labels it as untrusted source data.
- A tool call must name a registered function and pass the role allow-list.
- Persistent writes happen in repositories and the runtime, not from arbitrary model text.
- Final citations must resolve to an evidence ID collected for the current run.

There is no shell tool, filesystem tool, arbitrary Python execution, browser automation, generic
autonomous tool loop, or capture of hidden model reasoning.

## Web and SSRF protection

`WebFetchTool` accepts only HTTP and HTTPS. Before the initial request and every redirect,
`validate_public_url()` resolves the host and rejects loopback, private, link-local, multicast,
reserved, and unspecified IP addresses. This blocks common server-side request forgery targets
such as localhost, private cloud networks, and link-local metadata services.

Fetches use explicit redirect limits, timeouts, a recognizable user agent, a maximum download
size, accepted text content types, and a maximum extracted-character count. HTML script, style,
and noscript elements are removed. DNS-rebinding protection in a hostile production network
would require network-level egress policy as well; application checks are only one layer.

Every accepted page excerpt is wrapped in `<untrusted_source>` markers. Prompts tell roles to
extract evidence but ignore commands embedded in a page. This reduces prompt-injection risk but
does not make arbitrary web content safe enough for consequential autonomous action.

## Tool permissions and approvals

`ToolRegistry` stores `ToolMetadata` beside each handler. Metadata declares which
`AgentKind` values may invoke it and whether approval is required. Execution checks the
allow-list before the handler runs. `ApprovalGate` fails closed: a tool requiring approval is
denied unless an application provides a gate that explicitly approves the request.

Version 1 registers:

| Tool | Allowed roles |
|---|---|
| `web_search`, `web_fetch` | worker, verifier |
| `memory_search` | CEO, manager, worker, QA, curator |
| `evidence_read` | CEO, manager, verifier, QA |

The runtime controls when the web tools execute, even for an allowed role.

## Secrets and errors

`.env`, generated databases, and run output are ignored by Git. API keys stay in environment
settings and are not deliberately placed in prompts. Events and failure messages redact common
API-key, authorization, cookie, and secret patterns before storage or display. Ordinary CLI
failures show a concise message without a traceback; `--debug` is an explicit developer choice.

Redaction is defense in depth, not permission to put secrets in prompts. Do not research private
data, paste credentials, or commit a real `.env`.

## Data and operational limits

SQLite and artifact files are local plaintext. Anyone with filesystem access can read them.
Version 1 provides no encryption at rest, authentication, tenant isolation, audit export,
retention automation, or production backup policy. Use a dedicated non-sensitive workspace.

Concurrency, retry, query, agent, round, response-size, and total-runtime limits contain resource
use. They do not replace provider spending limits or network policy.

## Reporting a problem

Do not include keys, cookies, private prompts, or run databases in a public issue. Describe the
minimum reproduction using the fake provider where possible and rotate any secret that may have
been exposed.
