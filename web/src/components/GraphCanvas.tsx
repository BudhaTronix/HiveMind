import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import dagre from '@dagrejs/dagre'
import {
  Background, BackgroundVariant, Controls, MiniMap, ReactFlow, ReactFlowProvider,
  MarkerType, applyNodeChanges, useReactFlow, type Edge, type NodeChange,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Filter, LocateFixed, Lock, Search, Unlock } from 'lucide-react'
import type { DashboardState } from '../state/reducer'
import type { AgentKind, AgentNodeState, AgentStatus } from '../types'
import {
  GRAPH_NODE_HEIGHT as NODE_HEIGHT,
  GRAPH_NODE_WIDTH as NODE_WIDTH,
  organizationLayoutPositions,
} from '../graphLayout'
import { AgentNode, type AgentFlowNode } from './AgentNode'

interface Props {
  state: DashboardState
  view: 'organization' | 'handoffs'
  onViewChange: (view: 'organization' | 'handoffs') => void
  onSelectAgent: (agentId: string) => void
  onSelectHandoff: (handoffId: string) => void
}

const nodeTypes = { agent: AgentNode }
const statuses: AgentStatus[] = ['created', 'queued', 'planning', 'running', 'waiting_for_tool', 'waiting_for_children', 'synthesizing', 'verifying', 'retrying', 'completed', 'failed', 'cancelled']
const roles: AgentKind[] = ['ceo', 'manager', 'worker', 'verifier', 'qa', 'memory_curator']

export function GraphCanvas(props: Props) {
  return <ReactFlowProvider><Canvas {...props} /></ReactFlowProvider>
}

function Canvas({ state, view, onViewChange, onSelectAgent, onSelectHandoff }: Props) {
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<AgentStatus | 'all'>('all')
  const [roleFilter, setRoleFilter] = useState<AgentKind | 'all'>('all')
  const [locked, setLocked] = useState(false)
  const [nodes, setNodes] = useState<AgentFlowNode[]>([])
  const layoutCache = useRef<{ key: string; positions: Record<string, { x: number; y: number }> }>({ key: '', positions: {} })
  const appliedTopologyKey = useRef('')
  const { fitView, setCenter } = useReactFlow()

  const visibleAgents = useMemo(() => Object.values(state.agents).filter((agent) => {
    const matchesText = `${agent.profile.name} ${agent.profile.kind}`.toLowerCase().includes(query.toLowerCase())
    return matchesText && (statusFilter === 'all' || agent.status === statusFilter) &&
      (roleFilter === 'all' || agent.profile.kind === roleFilter)
  }), [query, roleFilter, state.agents, statusFilter])

  const rawEdges = useMemo(
    () => edgeList(state.agents, state.handoffs, view),
    [state.agents, state.handoffs, view],
  )
  const topologyKey = `${view}:${visibleAgents.map((agent) => agent.profile.agent_id).join(',')}:${rawEdges.map((edge) => `${edge.source}>${edge.target}`).join(',')}`
  if (layoutCache.current.key !== topologyKey) {
    layoutCache.current = {
      key: topologyKey,
      positions: layoutPositions(
        visibleAgents,
        rawEdges,
        view,
      ),
    }
  }
  const positions = layoutCache.current.positions
  const calculated = useMemo(() => visibleAgents.map((agent) => ({
      id: agent.profile.agent_id,
      type: 'agent' as const,
      position: positions[agent.profile.agent_id] ?? { x: 0, y: 0 },
      data: { state: agent, isNew: state.newestAgentId === agent.profile.agent_id },
    })), [positions, state.newestAgentId, visibleAgents])

  useEffect(() => {
    const topologyChanged = appliedTopologyKey.current !== topologyKey
    appliedTopologyKey.current = topologyKey
    setNodes((previous) => calculated.map((node) => {
      const existing = previous.find((item) => item.id === node.id)
      if (
        existing &&
        !topologyChanged &&
        existing.data.state === node.data.state &&
        existing.data.isNew === node.data.isNew
      ) return existing
      return existing ? {
        ...node,
        position: topologyChanged ? node.position : existing.position,
        selected: existing.selected,
      } : node
    }))
  }, [calculated, topologyKey])

  useEffect(() => {
    if (!state.followLive || !state.newestAgentId) return
    const node = nodes.find((item) => item.id === state.newestAgentId)
    if (node) void setCenter(node.position.x + 56, node.position.y + 46, { zoom: 1, duration: 350 })
  }, [nodes, setCenter, state.followLive, state.newestAgentId])

  const edges = useMemo(() => rawEdges.filter((edge) =>
    nodes.some((node) => node.id === edge.source) && nodes.some((node) => node.id === edge.target)), [nodes, rawEdges])
  const resetLayout = useCallback(() => {
    setNodes(calculated)
    window.setTimeout(() => void fitView({ padding: 0.18, duration: 400 }), 0)
  }, [calculated, fitView])
  const onNodesChange = useCallback((changes: NodeChange<AgentFlowNode>[]) => {
    setNodes((current) => applyNodeChanges(changes, current))
  }, [])

  return (
    <section className="canvas-shell" aria-label="Agent workflow canvas">
      <div className="canvas-toolbar">
        <label className="search-field"><Search size={15} /><span className="sr-only">Search agents</span><input aria-label="Search agents" placeholder="Search agents" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
        <label><Filter size={14} /><span className="sr-only">Filter status</span><select aria-label="Filter by status" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as AgentStatus | 'all')}><option value="all">All statuses</option>{statuses.map((item) => <option key={item}>{item}</option>)}</select></label>
        <label><span className="sr-only">Filter role</span><select aria-label="Filter by role" value={roleFilter} onChange={(event) => setRoleFilter(event.target.value as AgentKind | 'all')}><option value="all">All roles</option>{roles.map((item) => <option key={item}>{item.replace('_', ' ')}</option>)}</select></label>
        <div className="segmented" aria-label="Graph view"><button className={view === 'organization' ? 'active' : ''} onClick={() => onViewChange('organization')}>Organization</button><button className={view === 'handoffs' ? 'active' : ''} onClick={() => onViewChange('handoffs')}>Handoff Flow</button></div>
        <button className="icon-button" aria-label="Reset graph layout" title="Reset layout" onClick={resetLayout}><LocateFixed size={16} /></button>
        <button className="icon-button" aria-label={locked ? 'Unlock node positions' : 'Lock node positions'} title="Lock layout" onClick={() => setLocked((value) => !value)}>{locked ? <Lock size={16} /> : <Unlock size={16} />}</button>
      </div>
      {view === 'handoffs' && <nav className="sr-only" aria-label="Handoff graph edges">{Object.values(state.handoffs).map((handoff) => <button key={handoff.handoff_id} aria-label={`Open handoff ${handoff.title}`} onClick={() => onSelectHandoff(handoff.handoff_id)}>{handoff.title}</button>)}</nav>}
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onNodeClick={(_, node) => onSelectAgent(node.id)}
        onEdgeClick={(_, edge) => edge.data?.handoffId && onSelectHandoff(String(edge.data.handoffId))}
        nodesDraggable={!locked}
        fitView
        minZoom={0.25}
        maxZoom={1.8}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1.3} />
        <Controls position="bottom-left" showInteractive={false} />
        <MiniMap position="bottom-right" pannable zoomable nodeColor={(node) => roleColor(state.agents[node.id]?.profile.kind)} />
      </ReactFlow>
    </section>
  )
}

function edgeList(
  agents: DashboardState['agents'],
  handoffs: DashboardState['handoffs'],
  view: 'organization' | 'handoffs',
): Edge[] {
  if (view === 'organization') {
    return Object.values(agents).flatMap((agent) => {
      const parentId = agent.profile.parent_agent_id
      if (!parentId) return []
      const branch = agent.profile.kind === 'manager'
        ? 'manager'
        : agent.profile.kind === 'worker' ? 'worker' : 'support'
      const color = branch === 'manager' ? '#8f79d4' : branch === 'worker' ? '#3fb69e' : '#647087'
      return [{
        id: `org:${parentId}:${agent.profile.agent_id}`,
        source: parentId,
        target: agent.profile.agent_id,
        type: 'smoothstep',
        className: `organization-edge ${branch}-branch`,
        ariaLabel: `${agents[parentId]?.profile.name ?? 'Parent agent'} spawned ${agent.profile.name}`,
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
        style: { stroke: color },
      }]
    })
  }
  return Object.values(handoffs).map((handoff) => ({
    id: handoff.handoff_id,
    source: handoff.source_agent_id,
    target: handoff.target_agent_id,
    label: handoff.kind.replace('_', ' '),
    data: { handoffId: handoff.handoff_id },
    ariaLabel: `Handoff: ${handoff.title}`,
    focusable: true,
    className: 'handoff-edge',
    animated: Date.now() - new Date(handoff.created_at).getTime() < 12_000,
  }))
}

function layoutPositions(
  agents: AgentNodeState[],
  edges: Edge[],
  view: string,
): Record<string, { x: number; y: number }> {
  if (view === 'organization') return organizationLayoutPositions(agents)
  const graph = new dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}))
  const agentIds = agents.map((agent) => agent.profile.agent_id)
  graph.setGraph({ rankdir: 'LR', ranksep: 64, nodesep: 30 })
  agentIds.forEach((agentId) => graph.setNode(agentId, { width: NODE_WIDTH, height: NODE_HEIGHT }))
  edges.forEach((edge) => graph.setEdge(edge.source, edge.target))
  dagre.layout(graph)
  return Object.fromEntries(agentIds.map((agentId) => {
    const position = graph.node(agentId) as { x: number; y: number } | undefined
    return [agentId, position ? {
      x: position.x - NODE_WIDTH / 2,
      y: position.y - NODE_HEIGHT / 2,
    } : { x: 0, y: 0 }]
  }))
}

function roleColor(kind?: AgentKind): string {
  return ({ ceo: '#ffb454', manager: '#a78bfa', worker: '#48d6b5', verifier: '#5ca8ff', qa: '#ff719a', memory_curator: '#d1dd72' } as Record<string, string>)[kind ?? ''] ?? '#707786'
}
