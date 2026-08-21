import { useEffect, useState } from 'react'
import { ArrowDownLeft, ArrowUpRight, ExternalLink, PinOff, X } from 'lucide-react'
import { api } from '../api'
import type { DashboardState } from '../state/reducer'
import type { AgentDetails, AgentHandoff } from '../types'

interface Props {
  state: DashboardState
  runId: string
  onClose: () => void
  onSelectAgent: (agentId: string) => void
}

type Tab = 'overview' | 'history' | 'incoming' | 'outgoing' | 'work' | 'tools'

export function Inspector({ state, runId, onClose, onSelectAgent }: Props) {
  const [details, setDetails] = useState<AgentDetails | null>(null)
  const [loading, setLoading] = useState(false)
  const [tab, setTab] = useState<Tab>('overview')
  const handoff = state.selectedHandoffId ? state.handoffs[state.selectedHandoffId] : null
  const agentId = state.selectedAgentId

  useEffect(() => {
    if (!agentId) return
    let current = true
    setLoading(true)
    void api.agent(runId, agentId).then((value) => {
      if (current) setDetails(value)
    }).catch(() => {
      if (current) setDetails(null)
    }).finally(() => {
      if (current) setLoading(false)
    })
    return () => { current = false }
  }, [agentId, runId, state.events.length, state.handoffs])

  if (!handoff && !agentId) return null
  return (
    <aside className="inspector" aria-label="Agent inspector">
      <div className="inspector-top"><span>Inspector</span><button className="icon-button" aria-label="Close inspector" onClick={onClose}><X size={17} /></button></div>
      {handoff ? <HandoffDetail handoff={handoff} state={state} onSelectAgent={onSelectAgent} /> : (
        <AgentContent
          details={details}
          liveState={agentId ? state.agents[agentId] : null}
          loading={loading}
          tab={tab}
          setTab={setTab}
          onClose={onClose}
        />
      )}
    </aside>
  )
}

function AgentContent({ details, liveState, loading, tab, setTab, onClose }: {
  details: AgentDetails | null
  liveState: DashboardState['agents'][string] | null
  loading: boolean
  tab: Tab
  setTab: (tab: Tab) => void
  onClose: () => void
}) {
  if (loading && !details) return <div className="inspector-loading"><span /><span /><span /></div>
  if (!liveState) return <p className="empty-copy">Agent details are unavailable.</p>
  const profile = details?.agent ?? liveState.profile
  const status = liveState.status
  const tabs: Array<[Tab, string]> = [['overview', 'Overview'], ['history', 'Status'], ['incoming', 'Incoming'], ['outgoing', 'Outgoing'], ['work', 'Tasks'], ['tools', 'Tools']]
  return (
    <>
      <div className="agent-heading">
        <div className={`avatar role-${profile.kind}`}>{profile.name.slice(0, 2).toUpperCase()}</div>
        <div><span className="eyebrow">{profile.kind.replace('_', ' ')}</span><h2>{profile.name}</h2><span className={`status-label status-${status}`}>{status.replaceAll('_', ' ')}</span></div>
        <button className="icon-button pin-off" aria-label="Unpin selected agent" title="Unpin selection" onClick={onClose}><PinOff size={16} /></button>
      </div>
      <nav className="inspector-tabs" aria-label="Agent details tabs">{tabs.map(([value, label]) => <button key={value} className={tab === value ? 'active' : ''} aria-selected={tab === value} role="tab" onClick={() => setTab(value)}>{label}</button>)}</nav>
      <div className="inspector-body">
        {tab === 'overview' && <Overview details={details} liveState={liveState} />}
        {tab === 'history' && <EventList events={details?.status_history ?? []} />}
        {tab === 'incoming' && <HandoffList handoffs={details?.incoming_handoffs ?? []} direction="incoming" />}
        {tab === 'outgoing' && <HandoffList handoffs={details?.outgoing_handoffs ?? []} direction="outgoing" />}
        {tab === 'work' && <WorkList details={details} />}
        {tab === 'tools' && <ToolsList details={details} />}
      </div>
    </>
  )
}

function Overview({ details, liveState }: { details: AgentDetails | null; liveState: DashboardState['agents'][string] }) {
  return <div className="detail-stack">
    <section><h3>Objective</h3><p>{liveState.profile.role_description || 'Waiting for the validated assignment.'}</p></section>
    {liveState.active_task_title && <section><h3>Active task</h3><p>{liveState.active_task_title}</p></section>}
    <div className="metric-grid"><Metric label="Claims" value={liveState.claim_count} /><Metric label="Evidence" value={liveState.evidence_count} /><Metric label="Retries" value={liveState.retry_count} /><Metric label="Tasks" value={details?.tasks.length ?? 0} /></div>
    <section><h3>Message flow</h3><p>{details?.incoming_handoffs.length ?? 0} incoming · {details?.outgoing_handoffs.length ?? 0} outgoing</p></section>
  </div>
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div className="metric"><strong>{value}</strong><span>{label}</span></div>
}

function EventList({ events }: { events: AgentDetails['status_history'] }) {
  if (!events.length) return <p className="empty-copy">No status transitions yet.</p>
  return <div className="card-list">{events.map((event) => <article className="event-card" key={event.event_id}><span className="eyebrow">{event.event_type.replaceAll('_', ' ')}</span><p>{event.message}</p><time>{formatTime(event.timestamp)}</time></article>)}</div>
}

function HandoffList({ handoffs, direction }: { handoffs: AgentHandoff[]; direction: 'incoming' | 'outgoing' }) {
  if (!handoffs.length) return <p className="empty-copy">No {direction} public handoffs yet.</p>
  return <div className="card-list">{handoffs.map((handoff) => <HandoffCard key={handoff.handoff_id} handoff={handoff} direction={direction} />)}</div>
}

function HandoffCard({ handoff, direction }: { handoff: AgentHandoff; direction: string }) {
  return <details className="message-card"><summary>{direction === 'incoming' ? <ArrowDownLeft size={15} /> : <ArrowUpRight size={15} />}<span><span className="eyebrow">{handoff.kind.replaceAll('_', ' ')}</span><strong>{handoff.title}</strong></span><time>{formatTime(handoff.created_at)}</time></summary><p>{handoff.summary}</p><span className="publication">{handoff.publication_status}</span><pre>{JSON.stringify(handoff.payload_preview, null, 2)}</pre></details>
}

function WorkList({ details }: { details: AgentDetails | null }) {
  if (!details) return <p className="empty-copy">Loading validated work…</p>
  return <div className="card-list">
    {details.tasks.map((task) => <article className="event-card" key={task.task_id}><span className="eyebrow">{task.status} · attempt {task.attempt}/{task.max_attempts}</span><strong>{task.title}</strong><p>{task.objective}</p>{task.error_message && <p className="error-copy">{task.error_message}</p>}</article>)}
    {details.reports.map((report, index) => <details className="message-card" key={`${report.report_type}-${index}`}><summary><strong>Validated {report.report_type.replaceAll('_', ' ')}</strong></summary><pre>{JSON.stringify(report.data, null, 2)}</pre></details>)}
  </div>
}

function ToolsList({ details }: { details: AgentDetails | null }) {
  if (!details || (!details.tool_calls.length && !details.evidence.length)) return <p className="empty-copy">No tools or evidence recorded.</p>
  return <div className="card-list">
    {details.tool_calls.map((tool) => <article className="event-card" key={tool.tool_call_id}><span className="eyebrow">{tool.status}</span><strong>{tool.tool_name}</strong><time>{formatTime(tool.created_at)}</time></article>)}
    {details.evidence.map((item) => <article className="event-card" key={item.evidence_id}><span className="eyebrow">{item.source_type}</span><strong>{item.title}</strong>{item.url && <a href={item.url} target="_blank" rel="noreferrer">Open source <ExternalLink size={13} /></a>}</article>)}
  </div>
}

function HandoffDetail({ handoff, state, onSelectAgent }: { handoff: AgentHandoff; state: DashboardState; onSelectAgent: (id: string) => void }) {
  const source = state.agents[handoff.source_agent_id]?.profile.name ?? handoff.source_agent_id
  const target = state.agents[handoff.target_agent_id]?.profile.name ?? handoff.target_agent_id
  return <div className="inspector-body handoff-detail"><span className="eyebrow">{handoff.kind.replaceAll('_', ' ')}</span><h2>{handoff.title}</h2><div className="handoff-route"><button onClick={() => onSelectAgent(handoff.source_agent_id)}>{source}</button><ArrowUpRight size={18} /><button onClick={() => onSelectAgent(handoff.target_agent_id)}>{target}</button></div><p>{handoff.summary}</p><div className="message-meta"><time>{new Date(handoff.created_at).toLocaleString()}</time><span className="publication">{handoff.publication_status}</span></div><h3>Public payload preview</h3><pre>{JSON.stringify(handoff.payload_preview, null, 2)}</pre><p className="privacy-note">This preview contains bounded validated workflow data—never prompts, credentials, or hidden reasoning.</p></div>
}

function formatTime(value: string): string {
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
