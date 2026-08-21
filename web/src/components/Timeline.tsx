import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowLeftRight,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleDot,
  Radio,
  RotateCcw,
} from 'lucide-react'
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
  const scrollRef = useRef<HTMLDivElement>(null)
  const items = useMemo(() => [
    ...state.events.map((event) => ({
      id: event.event_id,
      kind: 'event' as const,
      type: event.event_type,
      time: event.timestamp,
      label: event.message,
      agentId: event.agent_id,
      agentName: event.agent_id
        ? state.agents[event.agent_id]?.profile.name ?? 'Unknown agent'
        : 'HiveMind',
      severity: severityFor(event.event_type),
    })),
    ...Object.values(state.handoffs).map((handoff) => ({
      id: handoff.handoff_id,
      kind: 'handoff' as const,
      type: handoff.kind,
      time: handoff.created_at,
      label: handoff.title,
      agentId: handoff.source_agent_id,
      agentName: state.agents[handoff.source_agent_id]?.profile.name ?? 'Unknown agent',
      severity: 'info',
    })),
  ].sort((a, b) => a.time.localeCompare(b.time)).filter((item) =>
    (agentFilter === 'all' || item.agentId === agentFilter) &&
    (typeFilter === 'all' || item.kind === typeFilter) &&
    (severity === 'all' || item.severity === severity)).slice(-MAX_VISIBLE_ITEMS), [agentFilter, severity, state.agents, state.events, state.handoffs, typeFilter])

  useEffect(() => {
    if (!open || paused || !scrollRef.current) return
    scrollRef.current.scrollLeft = scrollRef.current.scrollWidth
  }, [items.length, open, paused])

  const latest = items.at(-1)
  return <section className={`timeline ${open ? 'open' : 'collapsed'}`} aria-label="Run event timeline">
    <header>
      <button
        className="timeline-title"
        aria-expanded={open}
        aria-label={`${open ? 'Collapse' : 'Expand'} timeline`}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
        <Radio size={15} />
        <span className="timeline-title-copy">Timeline</span>
        <span className="timeline-count">{items.length}</span>
      </button>
      {!open && latest && <span className="timeline-latest">
        <strong>{latest.type.replaceAll('_', ' ')}</strong>
        <span>{latest.label}</span>
        <time dateTime={latest.time}>{formatTime(latest.time)}</time>
      </span>}
      {open && <div className="timeline-filters">
        <select aria-label="Timeline agent filter" value={agentFilter} onChange={(event) => setAgentFilter(event.target.value)}>
          <option value="all">All agents</option>
          {Object.values(state.agents).map((agent) => <option key={agent.profile.agent_id} value={agent.profile.agent_id}>{agent.profile.name}</option>)}
        </select>
        <select aria-label="Timeline item type" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
          <option value="all">Events + handoffs</option>
          <option value="event">Events</option>
          <option value="handoff">Handoffs</option>
        </select>
        <select aria-label="Timeline severity" value={severity} onChange={(event) => setSeverity(event.target.value)}>
          <option value="all">All severity</option>
          <option value="info">Info</option>
          <option value="warning">Warning</option>
          <option value="error">Error</option>
        </select>
        {paused && <button className="resume-live" onClick={() => setPaused(false)}><RotateCcw size={14} /> Latest</button>}
      </div>}
    </header>
    {open && <div
      className="timeline-scroll"
      ref={scrollRef}
      onScroll={(event) => {
        const element = event.currentTarget
        setPaused(element.scrollWidth - element.scrollLeft - element.clientWidth > 48)
      }}
    >
      {items.length ? <div className="timeline-track">
        {items.map((item, index) => <div
          className={`timeline-entry ${index % 2 === 0 ? 'above' : 'below'} severity-${item.severity}`}
          key={item.id}
        >
          <button
            className="timeline-card"
            aria-label={`${item.type.replaceAll('_', ' ')}: ${item.label}`}
            onClick={() => item.kind === 'handoff'
              ? onFocusHandoff(item.id)
              : item.agentId && onFocusAgent(item.agentId)}
          >
            <span className="timeline-card-kicker">
              <TimelineIcon kind={item.kind} severity={item.severity} />
              {item.type.replaceAll('_', ' ')}
            </span>
            <strong>{item.label}</strong>
            <span className="timeline-card-meta">{item.agentName}</span>
          </button>
          <span className="timeline-connector" aria-hidden="true" />
          <span className="timeline-marker" aria-hidden="true" />
          <time className="timeline-point-time" dateTime={item.time}>{formatTime(item.time)}</time>
        </div>)}
      </div> : <div className="timeline-empty"><CircleDot size={18} /> Events will appear here as the team works.</div>}
    </div>}
  </section>
}

function TimelineIcon({ kind, severity }: { kind: 'event' | 'handoff'; severity: string }) {
  if (kind === 'handoff') return <ArrowLeftRight size={12} aria-hidden="true" />
  if (severity === 'error') return <AlertTriangle size={12} aria-hidden="true" />
  if (severity === 'warning') return <CircleDot size={12} aria-hidden="true" />
  return <CheckCircle2 size={12} aria-hidden="true" />
}

function formatTime(value: string): string {
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function severityFor(type: string): string {
  if (type.includes('failed')) return 'error'
  if (type.includes('retry') || type.includes('replan') || type.includes('reduced')) return 'warning'
  return 'info'
}
