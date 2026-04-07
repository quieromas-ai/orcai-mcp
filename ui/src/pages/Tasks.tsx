import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, ListTodo } from 'lucide-react'
import { fetchTasks } from '../api/tasks'
import { fetchAgents } from '../api/agents'
import { StatusBadge } from '../components/StatusBadge'
import { EmptyState } from '../components/EmptyState'
import type { TaskStatus } from '../types'

const STATUS_FILTERS: (TaskStatus | 'all')[] = ['all', 'queued', 'running', 'completed', 'failed']

function duration(start: string | null, end: string | null): string {
  if (!start) return '—'
  const ms = (end ? new Date(end) : new Date()).getTime() - new Date(start).getTime()
  const s = Math.floor(ms / 1000)
  if (s < 60) return `${s}s`
  return `${Math.floor(s / 60)}m ${s % 60}s`
}

function fmt(iso: string) {
  const d = new Date(iso)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

const PRIORITY_LABEL: Record<number, string> = { 1: 'low', 2: 'low+', 3: 'med', 4: 'high', 5: 'crit' }
const PRIORITY_COLOR: Record<number, string> = {
  1: 'text-slate-600', 2: 'text-slate-500', 3: 'text-sky-400', 4: 'text-amber-400', 5: 'text-rose-400',
}

export function Tasks() {
  const [statusFilter, setStatusFilter] = useState<TaskStatus | 'all'>('all')
  const [agentFilter, setAgentFilter] = useState<string>('')
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const { data, isLoading } = useQuery({
    queryKey: ['tasks', statusFilter, agentFilter],
    queryFn: () => fetchTasks({
      status: statusFilter === 'all' ? undefined : statusFilter,
      agent_id: agentFilter || undefined,
    }),
    refetchInterval: 5000,
  })

  const { data: agentsData } = useQuery({ queryKey: ['agents'], queryFn: fetchAgents })
  const agentMap = Object.fromEntries((agentsData?.agents ?? []).map(a => [a.id, a.name]))

  function toggleExpand(id: string) {
    setExpanded(s => {
      const n = new Set(s)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })
  }

  const tasks = data?.tasks ?? []

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-base font-semibold text-slate-200">Tasks</h1>
        <p className="mt-0.5 text-xs text-slate-600">{data?.total ?? 0} total — auto-refreshes</p>
      </div>

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1 rounded-lg border border-border bg-surface p-1">
          {STATUS_FILTERS.map(s => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`rounded-md px-3 py-1 font-mono text-xs font-medium transition-colors
                ${statusFilter === s ? 'bg-accent/10 text-accent ring-1 ring-accent/20' : 'text-slate-600 hover:text-slate-400'}`}
            >
              {s}
            </button>
          ))}
        </div>

        <select
          value={agentFilter}
          onChange={e => setAgentFilter(e.target.value)}
          className="rounded-md border border-border bg-surface px-3 py-1.5 text-xs text-slate-400 outline-none focus:border-accent"
        >
          <option value="">All agents</option>
          {agentsData?.agents.map(a => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
      </div>

      <div className="rounded-lg border border-border bg-surface">
        {isLoading ? (
          <div className="flex items-center justify-center py-16 text-xs text-slate-600">Loading…</div>
        ) : tasks.length === 0 ? (
          <EmptyState icon={<ListTodo size={24} />} title="No tasks" description="Delegate tasks via MCP tools or the Agents page." />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr>
                <th className="w-6 border-b border-border px-2 py-3" />
                <th className="border-b border-border px-4 py-3 text-left text-xs font-semibold uppercase tracking-widest text-slate-500">Created</th>
                <th className="border-b border-border px-4 py-3 text-left text-xs font-semibold uppercase tracking-widest text-slate-500">Agent</th>
                <th className="border-b border-border px-4 py-3 text-left text-xs font-semibold uppercase tracking-widest text-slate-500">Description</th>
                <th className="border-b border-border px-4 py-3 text-left text-xs font-semibold uppercase tracking-widest text-slate-500">Status</th>
                <th className="border-b border-border px-4 py-3 text-left text-xs font-semibold uppercase tracking-widest text-slate-500">Priority</th>
                <th className="border-b border-border px-4 py-3 text-left text-xs font-semibold uppercase tracking-widest text-slate-500">Duration</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map(task => {
                const isOpen = expanded.has(task.id)
                const hasDetail = task.output || task.error || task.retry_count > 0
                return (
                  <>
                    <tr
                      key={task.id}
                      className="group border-b border-border/50 hover:bg-raised/40"
                      onClick={() => hasDetail && toggleExpand(task.id)}
                    >
                      <td className="px-2 py-3 text-slate-700">
                        {hasDetail && (isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />)}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-600">{fmt(task.created_at)}</td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-400">
                        {agentMap[task.agent_id] ?? task.agent_id.slice(0, 8)}
                      </td>
                      <td className="max-w-xs px-4 py-3">
                        <span className="block truncate text-xs text-slate-300">{task.description}</span>
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={task.status} size="sm" />
                      </td>
                      <td className="px-4 py-3">
                        <span className={`font-mono text-xs ${PRIORITY_COLOR[task.priority] ?? 'text-slate-600'}`}>
                          {PRIORITY_LABEL[task.priority] ?? task.priority}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-slate-600">
                        {duration(task.started_at, task.completed_at)}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr key={`${task.id}-detail`} className="border-b border-border/50 bg-base/60">
                        <td colSpan={7} className="px-8 py-3">
                          <div className="space-y-2">
                            {task.output?.text && (
                              <div>
                                <p className="mb-1 text-xs font-semibold text-slate-500">Output</p>
                                <pre className="max-h-48 overflow-y-auto rounded-md border border-border bg-raised p-3 font-mono text-xs text-slate-300 whitespace-pre-wrap">
                                  {task.output.text}
                                </pre>
                              </div>
                            )}
                            {task.error && (
                              <div>
                                <p className="mb-1 text-xs font-semibold text-slate-500">Error</p>
                                <pre className="rounded-md border border-rose-900 bg-rose-950/40 p-3 font-mono text-xs text-rose-400 whitespace-pre-wrap">
                                  {task.error}
                                </pre>
                              </div>
                            )}
                            {task.retry_count > 0 && (
                              <p className="font-mono text-xs text-amber-500">
                                Retried {task.retry_count}/{task.max_retries} times
                              </p>
                            )}
                            <p className="font-mono text-xs text-slate-700">id: {task.id}</p>
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
