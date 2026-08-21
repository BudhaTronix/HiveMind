import { Component, useEffect, useReducer, useState, type ErrorInfo, type ReactNode } from 'react'
import { Activity, BrainCircuit, CircleStop, FileText, Moon, Network, Play, Plus, RefreshCw, Sun, Wifi, WifiOff } from 'lucide-react'
import { api } from './api'
import { FinalReportView } from './components/FinalReportView'
import { GraphCanvas } from './components/GraphCanvas'
import { Inspector } from './components/Inspector'
import { NewRunDialog } from './components/NewRunDialog'
import { Timeline } from './components/Timeline'
import { useRunStream } from './hooks/useRunStream'
import { dashboardReducer, initialState } from './state/reducer'
import type { NewRunInput, RunRecord } from './types'

export default function App() {
  const [state, dispatch] = useReducer(dashboardReducer, initialState)
  const [runs, setRuns] = useState<RunRecord[]>([])
  const [currentRunId, setCurrentRunId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [view, setView] = useState<'organization' | 'handoffs'>('organization')
  const [theme, setTheme] = useState<'dark' | 'light'>(() => localStorage.getItem('hivemind-theme') === 'light' ? 'light' : 'dark')
  const [reportOpen, setReportOpen] = useState(false)
  const elapsed = useElapsed(state.run?.created_at)

  useRunStream(currentRunId, dispatch)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('hivemind-theme', theme)
  }, [theme])

  useEffect(() => {
    let active = true
    const refresh = () => api.listRuns().then((items) => {
      if (!active) return
      setRuns(items)
      setCurrentRunId((current) => current ?? items[0]?.run_id ?? null)
    }).catch((error: Error) => setActionError(error.message)).finally(() => setLoading(false))
    void refresh()
    const timer = window.setInterval(() => void refresh(), 5_000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  useEffect(() => {
    if (!currentRunId) return
    setLoading(true)
    void api.snapshot(currentRunId).then((snapshot) => dispatch({ type: 'snapshot', snapshot })).catch((error: Error) => setActionError(error.message)).finally(() => setLoading(false))
  }, [currentRunId])

  const selectAgent = (agentId: string) => dispatch({ type: 'select_agent', agentId })
  const submitRun = async (input: NewRunInput) => {
    setCreating(true)
    setActionError(null)
    try {
      const scheduled = await api.createRun(input)
      setDialogOpen(false)
      setCurrentRunId(scheduled.run_id)
      setRuns(await api.listRuns())
    } catch (error) {
      setActionError(error instanceof Error ? error.message : 'Could not schedule the run.')
    } finally {
      setCreating(false)
    }
  }
  const resume = async () => {
    if (!currentRunId) return
    setActionError(null)
    try { await api.resume(currentRunId) } catch (error) { setActionError(error instanceof Error ? error.message : 'Resume failed.') }
  }
  const cancel = async () => {
    if (!currentRunId) return
    setActionError(null)
    try { await api.cancel(currentRunId) } catch (error) { setActionError(error instanceof Error ? error.message : 'Cancellation failed.') }
  }
  const terminal = state.run && ['completed', 'failed', 'cancelled'].includes(state.run.stage)
  const selected = state.selectedAgentId || state.selectedHandoffId

  return <div className="app-shell">
    <aside className="run-sidebar"><div className="brand"><span><BrainCircuit size={21} /></span><div><strong>HiveMind</strong><small>Agent canvas</small></div></div><button className="new-run-button" onClick={() => { setActionError(null); setDialogOpen(true) }}><Plus size={17} /> New Run</button><div className="sidebar-label">Recent runs</div><nav aria-label="Historical runs">{runs.map((run) => <button key={run.run_id} className={`run-list-item ${currentRunId === run.run_id ? 'active' : ''}`} onClick={() => setCurrentRunId(run.run_id)}><span className={`run-state stage-${run.stage}`} /><span><strong>{run.prompt}</strong><small>{run.provider} · {new Date(run.created_at).toLocaleDateString()}</small></span></button>)}</nav><footer><Network size={14} /><span>Local observability</span></footer></aside>
    <main className="workspace">
      <header className="topbar"><div className="run-context"><span className="eyebrow">{state.run?.project_id ?? 'No project'}</span><h1>{state.run?.prompt ?? 'HiveMind workflow canvas'}</h1></div>{state.run && <div className="run-facts"><span><Activity size={14} /> {state.run.stage.replaceAll('_', ' ')}</span><span>Round {state.run.round_number}/{state.run.max_rounds}</span><span>{elapsed}</span><span>{state.run.provider} · {state.run.model}</span></div>}<div className="top-actions"><label className="follow-toggle"><input type="checkbox" checked={state.followLive} onChange={(event) => dispatch({ type: 'set_follow_live', enabled: event.target.checked })} /> Follow Live</label><span className={`connection connection-${state.connection}`} title={`WebSocket ${state.connection}`}>{state.connection === 'live' ? <Wifi size={15} /> : <WifiOff size={15} />}{state.connection}</span>{state.finalReport && <button className="toolbar-button" onClick={() => setReportOpen(true)}><FileText size={15} /> Report</button>}{state.run && !terminal && <button className="icon-button danger" aria-label="Cancel active run" title="Cancel run" onClick={() => void cancel()}><CircleStop size={17} /></button>}{state.run && terminal && state.run.stage !== 'completed' && <button className="toolbar-button" onClick={() => void resume()}><RefreshCw size={15} /> Resume</button>}<button className="icon-button" aria-label={`Use ${theme === 'dark' ? 'light' : 'dark'} theme`} onClick={() => setTheme((value) => value === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}</button></div></header>
      {actionError && <div className="error-banner" role="alert"><strong>Setup or provider issue</strong><span>{actionError}</span><button aria-label="Dismiss error" onClick={() => setActionError(null)}>×</button></div>}
      {state.error && <div className="error-banner" role="alert"><strong>Run {state.run?.stage}</strong><span>{state.error}</span></div>}
      <div className={`work-area ${selected ? 'with-inspector' : ''}`}>
        {loading && state.run?.run_id !== currentRunId ? <CanvasSkeleton /> : currentRunId && state.run ? <ErrorBoundary label="workflow canvas"><GraphCanvas state={state} view={view} onViewChange={setView} onSelectAgent={selectAgent} onSelectHandoff={(handoffId) => dispatch({ type: 'select_handoff', handoffId })} /></ErrorBoundary> : <EmptyState onNew={() => setDialogOpen(true)} />}
        {selected && currentRunId && <ErrorBoundary label="agent inspector"><Inspector state={state} runId={currentRunId} onClose={() => dispatch({ type: 'clear_selection' })} onSelectAgent={selectAgent} /></ErrorBoundary>}
      </div>
      {state.run && <Timeline state={state} onFocusAgent={selectAgent} onFocusHandoff={(handoffId) => dispatch({ type: 'select_handoff', handoffId })} />}
    </main>
    <NewRunDialog open={dialogOpen} busy={creating} error={actionError} onClose={() => setDialogOpen(false)} onSubmit={(input) => void submitRun(input)} />
    {reportOpen && state.finalReport && <FinalReportView report={state.finalReport} onClose={() => setReportOpen(false)} />}
  </div>
}

function EmptyState({ onNew }: { onNew: () => void }) {
  return <section className="empty-state"><span><Network size={32} /></span><h2>Watch a team take shape</h2><p>Start an offline demo run and agents will appear as the governor approves them.</p><button className="primary" onClick={onNew}><Play size={16} /> Create first run</button></section>
}

function CanvasSkeleton() {
  return <div className="canvas-skeleton" aria-label="Loading workflow"><span /><span /><span /><span /></div>
}

function useElapsed(start?: string): string {
  const [, tick] = useState(0)
  useEffect(() => { const timer = window.setInterval(() => tick((value) => value + 1), 1_000); return () => window.clearInterval(timer) }, [])
  if (!start) return '0:00'
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(start).getTime()) / 1_000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

class ErrorBoundary extends Component<{ children: ReactNode; label: string }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error(`HiveMind ${this.props.label} failed`, error, info) }
  render() { return this.state.failed ? <section className="component-error"><h2>Could not render the {this.props.label}</h2><p>The run is safe. Reload to reconstruct this view from SQLite.</p></section> : this.props.children }
}
