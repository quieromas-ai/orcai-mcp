import { get, post, patch, del } from './client'
import type { Agent, AgentCreate, AgentLogsResponse, AgentUpdate } from '../types'

export const fetchAgents     = () => get<{ agents: Agent[]; total: number }>('/agents')
export const fetchActiveAgents = () => get<{ agents: Agent[]; active_count: number; queue_depth: number }>('/agents/active')
export const createAgent     = (data: AgentCreate) => post<Agent>('/agents', data)
export const updateAgent     = (id: string, data: AgentUpdate) => patch<Agent>(`/agents/${id}`, data)
export const deleteAgent     = (id: string) => del(`/agents/${id}`)
export const checkAgentHealth = (id: string) => get<{ agent_id: string; healthy: boolean; reason?: string }>(`/agents/${id}/health`)
export const fetchAgentLogs  = (id: string, tail = 50) => get<AgentLogsResponse>(`/agents/${id}/logs?tail=${tail}`)
