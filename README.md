# HiveMind

HiveMind is a local-first learning project that shows how a dynamic multi-agent research
system works. A CEO model proposes departments, managers propose focused workers, and a
Python runtime validates and schedules the work. Verifier and QA roles check the result
before the CEO produces a report.

In HiveMind, an **agent is not a process or a magical digital employee**. It is an identity,
role, prompt, task, permissions, status, model call, and validated result managed by Python.

```text
Prompt -> CEO plan -> Python governor -> Managers -> Workers
                                             |          |
                                             +-> reports+
                                                    |
                                      Verifier -> QA -> Final report
```

The LLM may propose an organization and research questions. Python remains responsible for
actual agent creation, limits, concurrency, permissions, tool execution, persistence, and
artifact paths. This distinction is the central lesson of the project.

## Try the offline demo

HiveMind requires Python 3.11 or newer.

### macOS and Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
hivemind demo --explain
```

### Windows PowerShell

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
hivemind demo --explain
```

The demo is deterministic and uses synthetic evidence clearly labelled as simulation. It
does not need Ollama, OpenAI, an API key, or internet access, and its output is not real
research.

## Development status

The full runtime, provider integrations, persistence, research tools, resume support,
memory, tests, and learning documentation are being added in verified milestones. See
[`BUILD_PROGRESS.md`](BUILD_PROGRESS.md) for the live checklist.

HiveMind is educational software. It is not a production autonomous company and should not
be used as the sole basis for consequential decisions.
