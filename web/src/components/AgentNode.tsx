import { Bot, BrainCircuit, BriefcaseBusiness, CheckCheck, Microscope, ShieldCheck } from 'lucide-react'
import { Handle, Position, type Node, type NodeProps } from '@xyflow/react'
import { memo } from 'react'
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

export const AgentNode = memo(function AgentNode({ data, selected }: NodeProps<AgentFlowNode>) {
  const agent = data.state
  const Icon = icons[agent.profile.kind]
  const receivesSpawnEdge = agent.profile.kind !== 'ceo'
  const canSpawnChildren = ['ceo', 'manager'].includes(agent.profile.kind)
  return (
    <article
      className={`agent-node role-${agent.profile.kind} status-${agent.status} ${active.has(agent.status) ? 'is-active' : ''} ${data.isNew ? 'is-new' : ''} ${selected ? 'is-selected' : ''}`}
      aria-label={`${agent.profile.name}, ${agent.profile.kind}, ${agent.status}`}
    >
      {receivesSpawnEdge && <Handle type="target" position={Position.Top} />}
      <div className="agent-orb">
        <Icon size={25} aria-hidden="true" />
        <span className={`status-dot status-${agent.status}`} aria-hidden="true" />
        {agent.retry_count > 0 && <span className="retry-chip">{agent.retry_count}</span>}
      </div>
      <h3>{agent.profile.name}</h3>
      <span className="node-status">{humanStatus(agent.status)}</span>
      {canSpawnChildren && <Handle type="source" position={Position.Bottom} />}
    </article>
  )
})

function humanStatus(status: string): string {
  return status.replaceAll('_', ' ')
}
