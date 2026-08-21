import { useEffect, useState, type FormEvent } from 'react'
import { Play, X } from 'lucide-react'
import type { NewRunInput } from '../types'

interface Props {
  open: boolean
  busy: boolean
  error: string | null
  onClose: () => void
  onSubmit: (input: NewRunInput) => void
}

export function NewRunDialog({ open, busy, error, onClose, onSubmit }: Props) {
  const [provider, setProvider] = useState<NewRunInput['provider']>('fake')
  const [webEnabled, setWebEnabled] = useState(true)
  useEffect(() => {
    if (open) setWebEnabled(true)
  }, [open])
  if (!open) return null
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    onSubmit({
      prompt: String(data.get('prompt')),
      project_id: String(data.get('project_id')),
      provider,
      model: String(data.get('model') || '') || undefined,
      enable_web: provider !== 'fake' && webEnabled,
      max_managers: Number(data.get('max_managers')),
      max_workers_per_manager: Number(data.get('max_workers_per_manager')),
      max_research_rounds: Number(data.get('max_research_rounds')),
      max_concurrent_llm_calls: Number(data.get('max_concurrent_llm_calls')),
    })
  }
  return <div className="dialog-backdrop" role="presentation"><section className="new-run-dialog" role="dialog" aria-modal="true" aria-labelledby="new-run-title"><header><div><span className="eyebrow">Safe runtime controls</span><h2 id="new-run-title">Launch a research team</h2></div><button className="icon-button" aria-label="Close new run dialog" onClick={onClose}><X size={18} /></button></header><form onSubmit={submit}><label className="full">Research prompt<textarea name="prompt" autoFocus required maxLength={12000} placeholder="What should the team investigate?" /></label><label>Project ID<input name="project_id" defaultValue="web-project" required maxLength={100} /></label><label>Provider<select name="provider" value={provider} onChange={(event) => { const value = event.target.value as NewRunInput['provider']; setProvider(value); if (value !== 'fake') setWebEnabled(true) }}><option value="fake">Fake · offline</option><option value="ollama">Ollama · local</option><option value="openai">OpenAI</option></select></label><label className="full">Model override <span>optional</span><input name="model" placeholder={provider === 'ollama' ? 'qwen3:8b' : provider === 'openai' ? 'gpt-4.1-mini' : 'Uses educational simulator'} disabled={provider === 'fake'} /></label><label>Managers<input name="max_managers" type="number" min="1" max="10" defaultValue="3" /></label><label>Workers / manager<input name="max_workers_per_manager" type="number" min="1" max="10" defaultValue="3" /></label><label>Research rounds<input name="max_research_rounds" type="number" min="1" max="5" defaultValue="2" /></label><label>Concurrent model calls<input name="max_concurrent_llm_calls" type="number" min="1" max="20" defaultValue="3" /></label><label className="checkbox full"><input name="enable_web" type="checkbox" checked={provider !== 'fake' && webEnabled} onChange={(event) => setWebEnabled(event.target.checked)} disabled={provider === 'fake'} /> Enable safe web research <span>Recommended for evidence-backed answers</span></label>{provider !== 'fake' && !webEnabled && <p className="dialog-warning full" role="status">Without web research, workers receive no external evidence and may return an uncertain answer instead of inventing facts.</p>}<p className="privacy-note full">API keys remain server-side in the environment and are never accepted by this form.</p>{error && <p className="dialog-error full" role="alert">{error}</p>}<footer className="full"><button type="button" className="secondary" onClick={onClose}>Cancel</button><button type="submit" className="primary" disabled={busy}><Play size={16} />{busy ? 'Scheduling…' : 'Start run'}</button></footer></form></section></div>
}
