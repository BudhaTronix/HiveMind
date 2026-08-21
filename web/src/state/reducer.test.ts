import { describe, expect, it } from 'vitest'
import { dashboardReducer, initialState } from './reducer'
import { agent, event, handoff, snapshot } from '../test/factories'

describe('dashboardReducer', () => {
  it('initializes the graph from a persisted snapshot', () => {
    const state = dashboardReducer(initialState, { type: 'snapshot', snapshot: snapshot() })
    expect(Object.keys(state.agents)).toEqual(['agent_ceo'])
    expect(state.selectedAgentId).toBe('agent_ceo')
  })

  it('creates and selects a node when AGENT_SPAWNED arrives', () => {
    const initialized = dashboardReducer(initialState, { type: 'snapshot', snapshot: snapshot() })
    const state = dashboardReducer(initialized, { type: 'envelope', envelope: { type: 'event', data: event() } })
    expect(state.agents.agent_worker.profile.name).toBe('Research Worker')
    expect(state.selectedAgentId).toBe('agent_worker')
    expect(state.newestAgentId).toBe('agent_worker')
  })

  it('does not auto-open a spawned agent when Follow Live is off', () => {
    let state = dashboardReducer(initialState, { type: 'snapshot', snapshot: snapshot() })
    state = dashboardReducer(state, { type: 'set_follow_live', enabled: false })
    state = dashboardReducer(state, { type: 'envelope', envelope: { type: 'event', data: event() } })
    expect(state.selectedAgentId).toBe('agent_ceo')
  })

  it('preserves a pinned agent while new agents arrive', () => {
    let state = dashboardReducer(initialState, { type: 'snapshot', snapshot: snapshot() })
    state = dashboardReducer(state, { type: 'select_agent', agentId: 'agent_ceo', pinned: true })
    state = dashboardReducer(state, { type: 'envelope', envelope: { type: 'event', data: event() } })
    expect(state.selectedAgentId).toBe('agent_ceo')
    expect(state.pinnedSelection).toBe(true)
  })

  it('uses structured status metadata instead of message text', () => {
    const initialSnapshot = snapshot()
    initialSnapshot.agents = [agent('agent_worker', 'worker', 'agent_ceo')]
    let state = dashboardReducer(initialState, { type: 'snapshot', snapshot: initialSnapshot })
    state = dashboardReducer(state, { type: 'envelope', envelope: { type: 'event', data: event({ event_id: 'status_two', event_type: 'agent_status_changed', message: 'Do not parse me', metadata: { status: 'verifying' } }) } })
    expect(state.agents.agent_worker.status).toBe('verifying')
  })

  it('deduplicates handoff publication into one data-flow record', () => {
    let state = dashboardReducer(initialState, { type: 'snapshot', snapshot: snapshot() })
    const envelope = { type: 'handoff' as const, data: handoff() }
    state = dashboardReducer(state, { type: 'envelope', envelope })
    state = dashboardReducer(state, { type: 'envelope', envelope })
    expect(Object.keys(state.handoffs)).toEqual(['handoff_one'])
  })

  it('replaces from a reconnect snapshot without duplicating records', () => {
    const reconnect = snapshot()
    reconnect.events = [event()]
    reconnect.handoffs = [handoff(), handoff()]
    let state = dashboardReducer(initialState, { type: 'snapshot', snapshot: reconnect })
    state = dashboardReducer(state, { type: 'snapshot', snapshot: reconnect, reconnect: true })
    expect(state.events).toHaveLength(1)
    expect(Object.values(state.handoffs)).toHaveLength(1)
  })
})
