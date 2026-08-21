import type { AgentNodeState } from './types'

export const GRAPH_NODE_WIDTH = 112
export const GRAPH_NODE_HEIGHT = 92

interface ResearchGroup {
  manager: AgentNodeState | null
  children: AgentNodeState[]
  width: number
}

export function organizationLayoutPositions(
  agents: AgentNodeState[],
): Record<string, { x: number; y: number }> {
  const positions: Record<string, { x: number; y: number }> = {}
  const ceos = agents.filter((agent) => agent.profile.kind === 'ceo')
  const managers = agents.filter((agent) => agent.profile.kind === 'manager')
  const workers = agents.filter((agent) => agent.profile.kind === 'worker')
  const support = agents.filter((agent) =>
    ['verifier', 'qa', 'memory_curator'].includes(agent.profile.kind))
  const managerIds = new Set(managers.map((agent) => agent.profile.agent_id))
  const groupedWorkerIds = new Set<string>()
  const groups: ResearchGroup[] = managers.map((manager) => {
    const children = workers.filter((worker) =>
      worker.profile.parent_agent_id === manager.profile.agent_id)
    children.forEach((worker) => groupedWorkerIds.add(worker.profile.agent_id))
    return { manager, children, width: subtreeWidth(children.length) }
  })
  const ungroupedWorkers = workers.filter((worker) =>
    !groupedWorkerIds.has(worker.profile.agent_id) ||
    (worker.profile.parent_agent_id !== null && !managerIds.has(worker.profile.parent_agent_id)))
  if (ungroupedWorkers.length) {
    groups.push({
      manager: null,
      children: ungroupedWorkers,
      width: subtreeWidth(ungroupedWorkers.length),
    })
  }

  const groupGap = 88
  const researchWidth = groups.length
    ? groups.reduce((total, group) => total + group.width, 0) + groupGap * (groups.length - 1)
    : GRAPH_NODE_WIDTH
  const hasCeo = ceos.length > 0
  const managerY = hasCeo ? 176 : 0
  const workerY = managerY + 184
  let cursor = 0
  groups.forEach((group) => {
    const center = cursor + group.width / 2
    if (group.manager) {
      positions[group.manager.profile.agent_id] = {
        x: center - GRAPH_NODE_WIDTH / 2,
        y: managerY,
      }
    }
    const span = childSpan(group.children.length)
    const childStart = center - span / 2
    group.children.forEach((worker, index) => {
      positions[worker.profile.agent_id] = {
        x: childStart + index * (GRAPH_NODE_WIDTH + 42),
        y: group.manager ? workerY : managerY,
      }
    })
    cursor += group.width + groupGap
  })

  ceos.forEach((ceo, index) => {
    positions[ceo.profile.agent_id] = {
      x: researchWidth / 2 - GRAPH_NODE_WIDTH / 2 + index * (GRAPH_NODE_WIDTH + 42),
      y: 0,
    }
  })

  if (support.length) {
    const supportX = groups.length || ceos.length ? researchWidth + 176 : 0
    support.forEach((agent, index) => {
      positions[agent.profile.agent_id] = {
        x: supportX + index * (GRAPH_NODE_WIDTH + 42),
        y: managerY,
      }
    })
  }
  return positions
}

function subtreeWidth(childCount: number): number {
  return Math.max(220, childSpan(childCount))
}

function childSpan(childCount: number): number {
  return childCount > 0
    ? childCount * GRAPH_NODE_WIDTH + (childCount - 1) * 42
    : GRAPH_NODE_WIDTH
}
