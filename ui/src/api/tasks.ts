import { get, post } from './client'
import type { Task, TaskCreate } from '../types'

export const fetchTasks      = (params?: { status?: string; agent_id?: string }) => {
  const qs = new URLSearchParams()
  if (params?.status)   qs.set('status', params.status)
  if (params?.agent_id) qs.set('agent_id', params.agent_id)
  const q = qs.toString()
  return get<{ tasks: Task[]; total: number }>(`/tasks${q ? `?${q}` : ''}`)
}
export const delegateTask    = (data: TaskCreate) => post<{ task_id: string; status: string; position: number }>('/tasks/delegate', data)
export const fetchTaskStatus = (id: string) => get<{ task_id: string; status: string; output: unknown; error: string | null }>(`/tasks/${id}/status`)
