import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { organizationLayoutPositions } from '../graphLayout'
import { GraphCanvas } from './GraphCanvas'
import { Inspector } from './Inspector'
import { NewRunDialog } from './NewRunDialog'
import { RunSidebar } from './RunSidebar'
import { Timeline } from './Timeline'
import { dashboardReducer, initialState } from '../state/reducer'
import { agent, details, event, handoff, snapshot } from '../test/factories'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('interactive dashboard components', () => {
  it('clicking a graph node selects it and clicking a handoff edge opens it', async () => {
    const data = snapshot()
    data.agents = [agent(), agent('agent_worker', 'worker', 'agent_ceo')]
    data.handoffs = [handoff()]
    const state = dashboardReducer(initialState, { type: 'snapshot', snapshot: data })
    const selectAgent = vi.fn()
    const selectHandoff = vi.fn()
    const { rerender } = render(<GraphCanvas state={state} view="organization" onViewChange={() => {}} onSelectAgent={selectAgent} onSelectHandoff={selectHandoff} />)
    fireEvent.click(await screen.findByLabelText('Research Worker, worker, completed'))
    expect(selectAgent).toHaveBeenCalledWith('agent_worker')
    expect(screen.queryByText('2 claims')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Research Worker, worker, completed').querySelector('.source')).toBeNull()
    expect(screen.getByLabelText('CEO Agent, ceo, completed').querySelector('.target')).toBeNull()
    rerender(<GraphCanvas state={state} view="handoffs" onViewChange={() => {}} onSelectAgent={selectAgent} onSelectHandoff={selectHandoff} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open handoff Worker findings' }))
    expect(selectHandoff).toHaveBeenCalledWith('handoff_one')
  })

  it('lays out organization ownership as a CEO-manager-worker pyramid', () => {
    const agents = [
      agent(),
      agent('manager_a', 'manager', 'agent_ceo'),
      agent('manager_b', 'manager', 'agent_ceo'),
      agent('worker_a1', 'worker', 'manager_a'),
      agent('worker_a2', 'worker', 'manager_a'),
      agent('worker_b1', 'worker', 'manager_b'),
      agent('verifier', 'verifier', 'agent_ceo'),
    ]
    const positions = organizationLayoutPositions(agents)
    const center = (id: string) => positions[id].x + 56

    expect(positions.agent_ceo.y).toBeLessThan(positions.manager_a.y)
    expect(positions.manager_a.y).toBe(positions.manager_b.y)
    expect(positions.manager_a.y).toBeLessThan(positions.worker_a1.y)
    expect(center('manager_a')).toBe((center('worker_a1') + center('worker_a2')) / 2)
    expect(center('agent_ceo')).toBeGreaterThan(center('manager_a'))
    expect(center('agent_ceo')).toBeLessThan(center('manager_b'))
    expect(positions.verifier.x).toBeGreaterThan(positions.worker_b1.x)
    expect(positions.verifier.y).toBe(positions.manager_a.y)
  })

  it('an agent inspector exposes status plus incoming and outgoing public messages', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(details()), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const data = snapshot()
    data.agents = [agent('agent_worker', 'worker', 'agent_ceo')]
    const state = dashboardReducer(initialState, { type: 'snapshot', snapshot: data })
    render(<Inspector state={state} runId="run_test" onClose={() => {}} onSelectAgent={() => {}} />)
    expect(await screen.findByText('Research Worker')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Incoming' }))
    expect(screen.getByText('Research assignment')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Status' }))
    expect(screen.getByText('Worker completed.')).toBeInTheDocument()
  })

  it('provides keyboard-reachable safe new-run controls with accessible labels', async () => {
    const submit = vi.fn()
    render(<NewRunDialog open busy={false} error={null} onClose={() => {}} onSubmit={submit} />)
    const prompt = screen.getByLabelText('Research prompt')
    expect(prompt).toHaveFocus()
    await userEvent.type(prompt, 'Investigate deterministic agents')
    expect(screen.getByLabelText('Project ID')).toBeEnabled()
    expect(screen.queryByLabelText(/API key/i)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Start run' }))
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ provider: 'fake', prompt: 'Investigate deterministic agents', enable_web: false }))
  })

  it('enables grounded web research by default for real providers', async () => {
    const submit = vi.fn()
    render(<NewRunDialog open busy={false} error={null} onClose={() => {}} onSubmit={submit} />)
    await userEvent.selectOptions(screen.getByLabelText('Provider'), 'ollama')
    const webResearch = screen.getByRole('checkbox', { name: /Enable safe web research/i })
    expect(webResearch).toBeChecked()
    await userEvent.click(webResearch)
    expect(screen.getByRole('status')).toHaveTextContent(/receive no external evidence/i)
    await userEvent.click(webResearch)
    await userEvent.type(screen.getByLabelText('Research prompt'), 'Compare automotive companies')
    await userEvent.click(screen.getByRole('button', { name: 'Start run' }))
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({
      provider: 'ollama',
      prompt: 'Compare automotive companies',
      enable_web: true,
    }))
  })

  it('collapses the runs sidebar and offers deletion for completed runs', async () => {
    const toggle = vi.fn()
    const remove = vi.fn()
    const completedRun = { ...snapshot().run, stage: 'completed' as const }
    render(<RunSidebar runs={[completedRun]} currentRunId={completedRun.run_id} collapsed={false} deletingRunId={null} onToggle={toggle} onNew={() => {}} onSelect={() => {}} onDelete={remove} />)
    await userEvent.click(screen.getByRole('button', { name: 'Collapse runs sidebar' }))
    expect(toggle).toHaveBeenCalledOnce()
    await userEvent.click(screen.getByRole('button', { name: `Delete run: ${completedRun.prompt}` }))
    expect(remove).toHaveBeenCalledWith(completedRun)
  })

  it('shows event cards on a horizontal timeline and collapses to its bottom bar', async () => {
    const data = snapshot()
    data.agents = [agent(), agent('agent_worker', 'worker', 'agent_ceo')]
    data.events = [event()]
    data.handoffs = [handoff()]
    const state = dashboardReducer(initialState, { type: 'snapshot', snapshot: data })
    const selectAgent = vi.fn()
    const selectHandoff = vi.fn()
    render(<Timeline state={state} onFocusAgent={selectAgent} onFocusHandoff={selectHandoff} />)

    await userEvent.click(screen.getByRole('button', { name: 'agent spawned: Created Research Worker.' }))
    expect(selectAgent).toHaveBeenCalledWith('agent_worker')
    await userEvent.click(screen.getByRole('button', { name: 'worker report: Worker findings' }))
    expect(selectHandoff).toHaveBeenCalledWith('handoff_one')

    const timeline = screen.getByRole('region', { name: 'Run event timeline' })
    await userEvent.click(screen.getByRole('button', { name: 'Collapse timeline' }))
    expect(timeline).toHaveClass('collapsed')
    expect(screen.queryByRole('button', { name: 'worker report: Worker findings' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Expand timeline' })).toHaveAttribute('aria-expanded', 'false')
  })
})
