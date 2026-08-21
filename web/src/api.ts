import type { AgentDetails, NewRunInput, RunRecord, RunSnapshot } from './types'

async function json<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText })) as { detail?: string }
    throw new Error(body.detail ?? `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const api = {
  listRuns: () => fetch('/api/v1/runs').then((response) => json<RunRecord[]>(response)),
  snapshot: (runId: string) =>
    fetch(`/api/v1/runs/${encodeURIComponent(runId)}/snapshot`).then((response) => json<RunSnapshot>(response)),
  agent: (runId: string, agentId: string) =>
    fetch(`/api/v1/runs/${encodeURIComponent(runId)}/agents/${encodeURIComponent(agentId)}`).then((response) => json<AgentDetails>(response)),
  createRun: (input: NewRunInput) =>
    fetch('/api/v1/runs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }).then((response) => json<{ run_id: string }>(response)),
  resume: (runId: string) =>
    fetch(`/api/v1/runs/${encodeURIComponent(runId)}/resume`, { method: 'POST' }).then((response) => json<{ run_id: string }>(response)),
  cancel: (runId: string) =>
    fetch(`/api/v1/runs/${encodeURIComponent(runId)}/cancel`, { method: 'POST' }).then((response) => json<RunRecord>(response)),
}

export function streamUrl(runId: string): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/api/v1/runs/${encodeURIComponent(runId)}/stream`
}
