import type { AgentDetails, AgentHandoff, AgentNodeState, HiveEvent, RunSnapshot } from '../types'

export const run = {
  run_id: 'run_test', project_id: 'project', prompt: 'Test agent workflow', provider: 'fake',
  model: 'educational-simulator', stage: 'workers_researching' as const, round_number: 1,
  max_rounds: 2, created_at: '2026-08-21T10:00:00Z', updated_at: '2026-08-21T10:00:01Z',
  error_message: null,
}

export function agent(id = 'agent_ceo', kind: AgentNodeState['profile']['kind'] = 'ceo', parent: string | null = null): AgentNodeState {
  return {
    profile: {
      agent_id: id, project_id: 'project', role_key: id, name: kind === 'ceo' ? 'CEO Agent' : 'Research Worker',
      kind, role_description: 'Investigate the assigned question.', parent_agent_id: parent,
      status: 'completed', created_at: '2026-08-21T10:00:00Z', last_used_at: '2026-08-21T10:00:02Z',
      tasks_completed: 1, tasks_failed: 0, average_verification_score: null,
    },
    status: 'completed', active_task_title: null, claim_count: 2, evidence_count: 1,
    retry_count: 0, last_activity_at: '2026-08-21T10:00:02Z',
  }
}

export function event(overrides: Partial<HiveEvent> = {}): HiveEvent {
  return {
    event_id: 'event_one', event_type: 'agent_spawned', timestamp: '2026-08-21T10:00:03Z',
    run_id: 'run_test', round_number: 1, task_id: null, agent_id: 'agent_worker',
    parent_agent_id: 'agent_ceo', message: 'Created Research Worker.',
    metadata: { name: 'Research Worker', kind: 'worker', status: 'queued' }, ...overrides,
  }
}

export function handoff(): AgentHandoff {
  return {
    handoff_id: 'handoff_one', run_id: 'run_test', round_number: 1,
    source_agent_id: 'agent_worker', target_agent_id: 'agent_ceo', task_id: null,
    kind: 'worker_report', title: 'Worker findings', summary: 'A bounded public summary.',
    payload_preview: { claim_count: 2 }, created_at: '2026-08-21T10:00:04Z',
    publication_status: 'published',
  }
}

export function snapshot(): RunSnapshot {
  return {
    run, agents: [agent()], tasks: [], events: [], handoffs: [], evidence: [], tool_activity: [],
    metrics: { llm_call_count: 1, web_search_count: 0, web_fetch_count: 0, agent_count: 1, task_count: 0, retry_count: 0, claim_count: 2, evidence_count: 1, failed_task_count: 0 },
    final_report: null, error: null,
  }
}

export function details(): AgentDetails {
  const worker = agent('agent_worker', 'worker', 'agent_ceo')
  return {
    agent: worker.profile, current_status: worker.status, tasks: [],
    incoming_handoffs: [{ ...handoff(), handoff_id: 'incoming', source_agent_id: 'agent_ceo', target_agent_id: 'agent_worker', kind: 'assignment', title: 'Research assignment' }],
    outgoing_handoffs: [handoff()], status_history: [event({ event_id: 'status', event_type: 'agent_completed', message: 'Worker completed.', metadata: { status: 'completed' } })],
    tool_calls: [], evidence: [], reports: [],
  }
}
