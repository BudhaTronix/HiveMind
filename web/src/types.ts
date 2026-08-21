export type RunStage =
  | 'created' | 'loading_memory' | 'ceo_planning' | 'validating_plan'
  | 'spawning_managers' | 'managers_planning' | 'spawning_workers'
  | 'workers_researching' | 'managers_synthesizing' | 'verifying'
  | 'quality_review' | 'replanning' | 'curating_memory' | 'final_synthesis'
  | 'completed' | 'failed' | 'cancelled'

export type AgentKind = 'ceo' | 'manager' | 'worker' | 'verifier' | 'qa' | 'memory_curator'
export type AgentStatus =
  | 'created' | 'queued' | 'planning' | 'running' | 'waiting_for_tool'
  | 'waiting_for_children' | 'synthesizing' | 'verifying' | 'retrying'
  | 'completed' | 'failed' | 'cancelled'

export interface RunRecord {
  run_id: string
  project_id: string
  prompt: string
  provider: string
  model: string
  stage: RunStage
  round_number: number
  max_rounds: number
  created_at: string
  updated_at: string
  error_message: string | null
}

export interface AgentProfile {
  agent_id: string
  project_id: string
  role_key: string
  name: string
  kind: AgentKind
  role_description: string
  parent_agent_id: string | null
  status: AgentStatus
  created_at: string
  last_used_at: string
  tasks_completed: number
  tasks_failed: number
  average_verification_score: number | null
}

export interface AgentNodeState {
  profile: AgentProfile
  status: AgentStatus
  active_task_title: string | null
  claim_count: number
  evidence_count: number
  retry_count: number
  last_activity_at: string
}

export interface TaskRecord {
  task_id: string
  run_id: string
  parent_task_id: string | null
  agent_id: string
  title: string
  objective: string
  status: string
  attempt: number
  max_attempts: number
  created_at: string
  started_at: string | null
  completed_at: string | null
  error_message: string | null
}

export interface HiveEvent {
  event_id: string
  event_type: string
  timestamp: string
  run_id: string
  round_number: number
  task_id: string | null
  agent_id: string | null
  parent_agent_id: string | null
  message: string
  metadata: Record<string, unknown>
}

export interface AgentHandoff {
  handoff_id: string
  run_id: string
  round_number: number
  source_agent_id: string
  target_agent_id: string
  task_id: string | null
  kind: string
  title: string
  summary: string
  payload_preview: Record<string, unknown>
  created_at: string
  publication_status: string
}

export interface EvidenceSummary {
  evidence_id: string
  agent_id: string
  task_id: string
  title: string
  url: string | null
  source_type: string
  retrieved_at: string
  verification_status: string
}

export interface RunMetrics {
  llm_call_count: number
  web_search_count: number
  web_fetch_count: number
  agent_count: number
  task_count: number
  retry_count: number
  claim_count: number
  evidence_count: number
  failed_task_count: number
}

export interface SourceReference {
  evidence_id: string
  title: string
  url: string | null
  retrieved_at: string
  claims_supported: string[]
  verification_status: string
}

export interface FinalReport {
  title: string
  executive_summary: string
  answer: string
  key_findings: string[]
  risks: string[]
  uncertainties: string[]
  recommendations: string[]
  research_limitations: string[]
  sources: SourceReference[]
}

export interface RunSnapshot {
  run: RunRecord
  agents: AgentNodeState[]
  tasks: TaskRecord[]
  events: HiveEvent[]
  handoffs: AgentHandoff[]
  evidence: EvidenceSummary[]
  tool_activity: ToolActivity[]
  metrics: RunMetrics
  final_report: FinalReport | null
  error: string | null
}

export interface ToolActivity {
  tool_call_id: string
  agent_id: string | null
  task_id: string | null
  tool_name: string
  status: string
  created_at: string
  event: HiveEvent
}

export interface AgentDetails {
  agent: AgentProfile
  current_status: AgentStatus
  tasks: TaskRecord[]
  incoming_handoffs: AgentHandoff[]
  outgoing_handoffs: AgentHandoff[]
  status_history: HiveEvent[]
  tool_calls: ToolActivity[]
  evidence: EvidenceSummary[]
  reports: Array<{ report_type: string; data: Record<string, unknown> }>
}

export type StreamEnvelope =
  | { type: 'snapshot'; data: RunSnapshot }
  | { type: 'event'; data: HiveEvent }
  | { type: 'handoff'; data: AgentHandoff }
  | { type: 'run_state'; data: { run_id: string } }
  | { type: 'error'; data: { code?: string; message: string } }

export interface NewRunInput {
  prompt: string
  project_id: string
  provider: 'fake' | 'ollama' | 'openai'
  model?: string
  enable_web: boolean
  max_managers: number
  max_workers_per_manager: number
  max_research_rounds: number
  max_concurrent_llm_calls: number
}
