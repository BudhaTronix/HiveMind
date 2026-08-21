import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { GraphCanvas } from './GraphCanvas'
import { Inspector } from './Inspector'
import { NewRunDialog } from './NewRunDialog'
import { dashboardReducer, initialState } from '../state/reducer'
import { agent, details, handoff, snapshot } from '../test/factories'

afterEach(() => vi.restoreAllMocks())

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
    rerender(<GraphCanvas state={state} view="handoffs" onViewChange={() => {}} onSelectAgent={selectAgent} onSelectHandoff={selectHandoff} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open handoff Worker findings' }))
    expect(selectHandoff).toHaveBeenCalledWith('handoff_one')
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
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ provider: 'fake', prompt: 'Investigate deterministic agents' }))
  })
})
