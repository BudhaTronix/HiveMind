import { memo } from 'react'
import {
  BrainCircuit,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Trash2,
} from 'lucide-react'
import type { RunRecord } from '../types'

interface Props {
  runs: RunRecord[]
  currentRunId: string | null
  collapsed: boolean
  deletingRunId: string | null
  onToggle: () => void
  onNew: () => void
  onSelect: (runId: string) => void
  onDelete: (run: RunRecord) => void
}

const terminalStages = new Set(['completed', 'failed', 'cancelled'])

export const RunSidebar = memo(function RunSidebar({
  runs,
  currentRunId,
  collapsed,
  deletingRunId,
  onToggle,
  onNew,
  onSelect,
  onDelete,
}: Props) {
  return <aside className={`run-sidebar ${collapsed ? 'collapsed' : ''}`}>
    <div className="brand">
      <span><BrainCircuit size={21} /></span>
      <div><strong>HiveMind</strong><small>Agent canvas</small></div>
      <button className="sidebar-toggle" aria-label={collapsed ? 'Expand runs sidebar' : 'Collapse runs sidebar'} onClick={onToggle}>
        {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
      </button>
    </div>
    <button className="new-run-button" aria-label="New run" title="New run" onClick={onNew}>
      <Plus size={17} /><span>New Run</span>
    </button>
    <div className="sidebar-label">Recent runs</div>
    <nav aria-label="Historical runs">
      {runs.map((run) => <div className="run-row" key={run.run_id}>
        <button
          className={`run-list-item ${currentRunId === run.run_id ? 'active' : ''}`}
          aria-label={`Open run: ${run.prompt}`}
          title={run.prompt}
          onClick={() => onSelect(run.run_id)}
        >
          <span className={`run-state stage-${run.stage}`} />
          <span><strong>{run.prompt}</strong><small>{run.provider} · {new Date(run.created_at).toLocaleDateString()}</small></span>
        </button>
        {terminalStages.has(run.stage) && <button
          className="delete-run-button"
          aria-label={`Delete run: ${run.prompt}`}
          title="Delete run"
          disabled={deletingRunId === run.run_id}
          onClick={() => onDelete(run)}
        ><Trash2 size={14} /></button>}
      </div>)}
    </nav>
    <footer><Network size={14} /><span>Local observability</span></footer>
  </aside>
})
