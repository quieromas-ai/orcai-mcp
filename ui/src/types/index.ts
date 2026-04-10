export type AgentStatus = 'idle' | 'busy' | 'disabled'
export type TaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
export type AgentRunner = 'api' | 'cli'

export interface Agent {
  id: string
  name: string
  role: string
  status: AgentStatus
  system_prompt: string
  model_preference: string
  runner: AgentRunner
  skills: string[]
  config: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface Task {
  id: string
  agent_id: string
  description: string
  status: TaskStatus
  priority: number
  input_context: Record<string, unknown>
  output: { text: string } | null
  error: string | null
  max_retries: number
  retry_count: number
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface Skill {
  id: string
  name: string
  description: string
  file_path: string
  version: string
  installed_at: string
}

export interface DashboardStats {
  total_agents: number
  active_agents: number
  queued_tasks: number
  total_skills: number
  tasks_today: number
  queue_depth: number
}

export interface AgentCreate {
  name: string
  role: string
  system_prompt: string
  model_preference: string
  config: { runner: AgentRunner }
}

export interface AgentUpdate {
  name?: string
  role?: string
  system_prompt?: string
  model_preference?: string
  status?: AgentStatus
  config?: Record<string, unknown>
}

export interface TaskCreate {
  agent_id: string
  description: string
  priority: number
  input_context?: Record<string, unknown>
}

export interface SkillCreate {
  name: string
  description: string
  content: string
  version: string
  assign_to: string[]
}

export interface AgentLogEntry {
  task_id: string
  status: TaskStatus
  description: string
  response: string | null
  error: string | null
  started_at: string | null
  completed_at: string | null
}

export interface AgentLogsResponse {
  agent_id: string
  total: number
  logs: AgentLogEntry[]
}
