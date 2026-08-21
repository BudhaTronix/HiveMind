import { useMemo, useState } from 'react'
import { ChevronDown, ChevronUp, Radio, RotateCcw } from 'lucide-react'
import type { DashboardState } from '../state/reducer'

const MAX_VISIBLE_ITEMS = 300

interface Props {
  state: DashboardState
  onFocusAgent: (agentId: string) => void
  onFocusHandoff: (handoffId: string) => void
}

export function Timeline({ state, onFocusAgent, onFocusHandoff }: Props) {
  const [open, setOpen] = useState(true)
  const [paused, setPaused] = useState(false)
  const [agentFilter, setAgentFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [severity, setSeverity] = useState('all')
  const items = useMemo(() => [
    ...state.events.map((event) => ({ id: event.event_id, kind: 'event' as const, type: event.event_type, time: event.timestamp, label: event.message, agentId: event.agent_id, severity: severityFor(event.event_type) })),
    ...Object.values(state.handoffs).map((handoff) => ({ id: handoff.handoff_id, kind: 'handoff' as const, type: handoff.kind, time: handoff.created_at, label: handoff.title, agentId: handoff.source_agent_id, severity: 'info' })),
  ].sort((a, b) => a.time.localeCompare(b.time)).filter((item) =>
    (agentFilter === 'all' || item.agentId === agentFilter) &&
    (typeFilter === 'all' || item.kind === typeFilter) &&
    (severity === 'all' || item.severity === severity)).slice(-MAX_VISIBLE_ITEMS), [agentFilter, severity, state.events, state.handoffs, typeFilter])

  return <section className={`timeline ${open ? 'open' : ''}`} aria-label="Run event timeline">
    <header><button className="timeline-title" onClick={() => setOpen((value) => !value)} aria-expanded={open}>{open ? <ChevronDown size={16} /> : <ChevronUp size={16} />}<Radio size={15} /> Timeline <span>{items.length}</span></button>{open && <div className="timeline-filters"><select aria-label="Timeline agent filter" value={agentFilter} onChange={(event) => setAgentFilter(event.target.value)}><option value="all">All agents</option>{Object.values(state.agents).map((agent) => <option key={agent.profile.agent_id} value={agent.profile.agent_id}>{agent.profile.name}</option>)}</select><select aria-label="Timeline item type" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option value="all">Events + handoffs</option><option value="event">Events</option><option value="handoff">Handoffs</option></select><select aria-label="Timeline severity" value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="all">All severity</option><option value="info">Info</option><option value="warning">Warning</option><option value="error">Error</option></select>{paused && <button className="resume-live" onClick={() => setPaused(false)}><RotateCcw size={14} /> Resume Live</button>}</div>}</header>
    {open && <div className="timeline-scroll" onScroll={(event) => { const element = event.currentTarget; setPaused(element.scrollHeight - element.scrollTop - element.clientHeight > 40) }} ref={(element) => { if (element && !paused) element.scrollTop = element.scrollHeight }}>
      {items.map((item) => <button className={`timeline-item severity-${item.severity}`} key={item.id} onClick={() => item.kind === 'handoff' ? onFocusHandoff(item.id) : item.agentId && onFocusAgent(item.agentId)}><time>{new Date(item.time).toLocaleTimeString()}</time><span className="event-type">{item.type.replaceAll('_', ' ')}</span><span>{item.label}</span></button>)}
    </div>}
  </section>
}

function severityFor(type: string): string {
  if (type.includes('failed')) return 'error'
  if (type.includes('retry') || type.includes('replan') || type.includes('reduced')) return 'warning'
  return 'info'
}
