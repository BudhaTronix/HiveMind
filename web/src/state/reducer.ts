import type {
  AgentHandoff,
  AgentKind,
  AgentNodeState,
  AgentStatus,
  HiveEvent,
  RunRecord,
  RunSnapshot,
  StreamEnvelope,
} from '../types'

export type ConnectionState = 'idle' | 'connecting' | 'live' | 'reconnecting' | 'offline'

export interface DashboardState {
  run: RunRecord | null
  agents: Record<string, AgentNodeState>
  tasks: RunSnapshot['tasks']
  events: HiveEvent[]
  handoffs: Record<string, AgentHandoff>
  evidence: RunSnapshot['evidence']
  toolActivity: RunSnapshot['tool_activity']
  metrics: RunSnapshot['metrics'] | null
  finalReport: RunSnapshot['final_report']
  error: string | null
  selectedAgentId: string | null
  selectedHandoffId: string | null
  pinnedSelection: boolean
  followLive: boolean
  connection: ConnectionState
  newestAgentId: string | null
}

export const initialState: DashboardState = {
  run: null,
  agents: {},
  tasks: [],
  events: [],
  handoffs: {},
  evidence: [],
  toolActivity: [],
  metrics: null,
  finalReport: null,
  error: null,
  selectedAgentId: null,
  selectedHandoffId: null,
  pinnedSelection: false,
  followLive: true,
  connection: 'idle',
  newestAgentId: null,
}

export type DashboardAction =
  | { type: 'snapshot'; snapshot: RunSnapshot; reconnect?: boolean }
  | { type: 'envelope'; envelope: StreamEnvelope }
  | { type: 'select_agent'; agentId: string; pinned?: boolean }
  | { type: 'select_handoff'; handoffId: string }
  | { type: 'clear_selection' }
  | { type: 'set_follow_live'; enabled: boolean }
  | { type: 'set_connection'; connection: ConnectionState }

export function dashboardReducer(
  state: DashboardState,
  action: DashboardAction,
): DashboardState {
  switch (action.type) {
    case 'snapshot':
      return fromSnapshot(state, action.snapshot, Boolean(action.reconnect))
    case 'envelope':
      return applyEnvelope(state, action.envelope)
    case 'select_agent':
      return {
        ...state,
        selectedAgentId: action.agentId,
        selectedHandoffId: null,
        pinnedSelection: action.pinned ?? true,
      }
    case 'select_handoff':
      return { ...state, selectedHandoffId: action.handoffId, pinnedSelection: true }
    case 'clear_selection':
      return { ...state, selectedAgentId: null, selectedHandoffId: null, pinnedSelection: false }
    case 'set_follow_live':
      return { ...state, followLive: action.enabled }
    case 'set_connection':
      return { ...state, connection: action.connection }
  }
}

function fromSnapshot(
  previous: DashboardState,
  snapshot: RunSnapshot,
  reconnect: boolean,
): DashboardState {
  const agents = Object.fromEntries(snapshot.agents.map((agent) => [agent.profile.agent_id, agent]))
  const selectedAgentId = reconnect && previous.selectedAgentId && previous.selectedAgentId in agents
    ? previous.selectedAgentId
    : (snapshot.agents[0]?.profile.agent_id ?? null)
  const selectedHandoffId = reconnect && previous.selectedHandoffId &&
    snapshot.handoffs.some((item) => item.handoff_id === previous.selectedHandoffId)
    ? previous.selectedHandoffId
    : null
  return {
    ...previous,
    run: snapshot.run,
    agents,
    tasks: snapshot.tasks,
    events: uniqueBy(snapshot.events, (item) => item.event_id),
    handoffs: Object.fromEntries(snapshot.handoffs.map((item) => [item.handoff_id, item])),
    evidence: snapshot.evidence,
    toolActivity: snapshot.tool_activity,
    metrics: snapshot.metrics,
    finalReport: snapshot.final_report,
    error: snapshot.error,
    selectedAgentId,
    selectedHandoffId,
    pinnedSelection: reconnect ? previous.pinnedSelection : false,
    newestAgentId: null,
  }
}

function applyEnvelope(state: DashboardState, envelope: StreamEnvelope): DashboardState {
  if (envelope.type === 'snapshot') {
    return fromSnapshot(state, envelope.data, state.run !== null)
  }
  if (envelope.type === 'event') {
    return applyEvent(state, envelope.data)
  }
  if (envelope.type === 'handoff') {
    if (state.handoffs[envelope.data.handoff_id]) return state
    return {
      ...state,
      handoffs: { ...state.handoffs, [envelope.data.handoff_id]: envelope.data },
    }
  }
  if (envelope.type === 'error') {
    return { ...state, error: envelope.data.message }
  }
  return state
}

function applyEvent(state: DashboardState, event: HiveEvent): DashboardState {
  if (state.events.some((item) => item.event_id === event.event_id)) return state
  let agents = state.agents
  let selectedAgentId = state.selectedAgentId
  let pinnedSelection = state.pinnedSelection
  let newestAgentId = state.newestAgentId
  let run = state.run
  let error = state.error

  if (event.event_type === 'agent_spawned' && event.agent_id && !agents[event.agent_id]) {
    const agent = agentFromSpawn(event, state.run)
    agents = { ...agents, [event.agent_id]: agent }
    newestAgentId = event.agent_id
    if (state.followLive && !state.pinnedSelection) {
      selectedAgentId = event.agent_id
      pinnedSelection = false
    }
  } else if (event.agent_id && agents[event.agent_id]) {
    const current = agents[event.agent_id]
    const status = statusFromEvent(current.status, event)
    const completed = event.event_type === 'agent_completed'
    agents = {
      ...agents,
      [event.agent_id]: {
        ...current,
        status,
        active_task_title: completed || event.event_type === 'agent_failed'
          ? null
          : (event.event_type === 'agent_started' ? event.message : current.active_task_title),
        claim_count: current.claim_count + numberMetadata(event, 'claims_added'),
        evidence_count: current.evidence_count + numberMetadata(event, 'evidence_added'),
        retry_count: current.retry_count + (event.event_type === 'task_retrying' ? 1 : 0),
        last_activity_at: event.timestamp,
      },
    }
  }

  if (run && event.event_type === 'stage_changed') {
    const stage = stringMetadata(event, 'stage')
    if (stage) run = { ...run, stage: stage as RunRecord['stage'], updated_at: event.timestamp }
  } else if (run && event.event_type === 'run_completed') {
    run = { ...run, stage: 'completed', updated_at: event.timestamp }
  } else if (run && event.event_type === 'run_failed') {
    const stage = stringMetadata(event, 'stage')
    run = { ...run, stage: stage === 'cancelled' ? 'cancelled' : 'failed', updated_at: event.timestamp }
    error = stringMetadata(event, 'error') ?? event.message
  }

  return {
    ...state,
    run,
    agents,
    events: [...state.events, event],
    selectedAgentId,
    selectedHandoffId: newestAgentId === event.agent_id ? null : state.selectedHandoffId,
    pinnedSelection,
    newestAgentId,
    error,
  }
}

function agentFromSpawn(event: HiveEvent, run: RunRecord | null): AgentNodeState {
  const status = (stringMetadata(event, 'status') ?? 'created') as AgentStatus
  return {
    profile: {
      agent_id: event.agent_id!,
      project_id: run?.project_id ?? '',
      role_key: event.agent_id!,
      name: stringMetadata(event, 'name') ?? 'New agent',
      kind: (stringMetadata(event, 'kind') ?? 'worker') as AgentKind,
      role_description: '',
      parent_agent_id: event.parent_agent_id,
      status,
      created_at: event.timestamp,
      last_used_at: event.timestamp,
      tasks_completed: 0,
      tasks_failed: 0,
      average_verification_score: null,
    },
    status,
    active_task_title: null,
    claim_count: 0,
    evidence_count: 0,
    retry_count: 0,
    last_activity_at: event.timestamp,
  }
}

function statusFromEvent(current: AgentStatus, event: HiveEvent): AgentStatus {
  if (event.event_type === 'agent_completed') return 'completed'
  if (event.event_type === 'agent_failed') return 'failed'
  const candidate = stringMetadata(event, 'status')
  return candidate ? candidate as AgentStatus : current
}

function stringMetadata(event: HiveEvent, key: string): string | null {
  const value = event.metadata[key]
  return typeof value === 'string' ? value : null
}

function numberMetadata(event: HiveEvent, key: string): number {
  const value = event.metadata[key]
  return typeof value === 'number' ? value : 0
}

function uniqueBy<T>(items: T[], key: (item: T) => string): T[] {
  return [...new Map(items.map((item) => [key(item), item])).values()]
}
