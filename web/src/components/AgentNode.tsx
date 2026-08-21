import { Bot, BrainCircuit, BriefcaseBusiness, CheckCheck, Microscope, ShieldCheck } from 'lucide-react'
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import type { AgentNodeState } from '../types'

export type AgentNodeData = { state: AgentNodeState; isNew: boolean } & Record<string, unknown>
export type AgentFlowNode = Node<AgentNodeData, 'agent'>

const icons = {
  ceo: BrainCircuit,
  manager: BriefcaseBusiness,
  worker: Microscope,
  verifier: ShieldCheck,
  qa: CheckCheck,
  memory_curator: Bot,
}

const active = new Set([
  'planning', 'running', 'waiting_for_tool', 'waiting_for_children',
  'synthesizing', 'verifying', 'retrying',
])

export function AgentNode({ data, selected }: NodeProps<AgentFlowNode>) {
  const agent = data.state
  const Icon = icons[agent.profile.kind]
  const time = new Date(agent.last_activity_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return (
    <article
      className={`agent-node role-${agent.profile.kind} status-${agent.status} ${active.has(agent.status) ? 'is-active' : ''} ${data.isNew ? 'is-new' : ''} ${selected ? 'is-selected' : ''}`}
      aria-label={`${agent.profile.name}, ${agent.profile.kind}, ${agent.status}`}
    >
      <Handle type="target" position={Position.Top} />
      <header>
        <span className="role-icon"><Icon size={16} aria-hidden="true" /></span>
        <span className="node-role">{agent.profile.kind.replace('_', ' ')}</span>
        <span className={`status-dot status-${agent.status}`} aria-hidden="true" />
      </header>
      <h3>{agent.profile.name}</h3>
      <p className="node-task">{agent.active_task_title ?? humanStatus(agent.status)}</p>
      <footer>
        <span>{agent.claim_count} claims</span>
        <span>{agent.evidence_count} evidence</span>
        <time dateTime={agent.last_activity_at}>{time}</time>
      </footer>
      {agent.retry_count > 0 && <span className="retry-chip">{agent.retry_count} retr{agent.retry_count === 1 ? 'y' : 'ies'}</span>}
      <Handle type="source" position={Position.Bottom} />
    </article>
  )
}

function humanStatus(status: string): string {
  return status.replaceAll('_', ' ')
}
