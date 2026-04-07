import { useQuery } from '@tanstack/react-query'
import { Bot, ListTodo, Puzzle, Activity } from 'lucide-react'
import { fetchDashboardStats } from '../api/dashboard'
import { fetchTasks } from '../api/tasks'
import { fetchAgents } from '../api/agents'
import { StatCard } from '../components/StatCard'
import { StatusBadge } from '../components/StatusBadge'

function ago(iso: string) {
  const secs = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  return `${Math.floor(secs / 3600)}h ago`
}

export function Dashboard() {
  const { data: stats } = useQuery({
    queryKey: ['dashboard-stats'],
    queryFn: fetchDashboardStats,
    refetchInterval: 5000,
  })
  const { data: tasksData } = useQuery({
    queryKey: ['tasks-recent'],
    queryFn: () => fetchTasks(),
    refetchInterval: 5000,
  })
  const { data: agentsData } = useQuery({
    queryKey: ['agents'],
    queryFn: fetchAgents,
    refetchInterval: 5000,
  })

  const recentTasks = (tasksData?.tasks ?? []).slice(0, 10)
  const agents = agentsData?.agents ?? []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-base font-semibold text-slate-200">Dashboard</h1>
        <p className="mt-0.5 text-xs text-slate-600">Live overview — refreshes every 5s</p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <StatCard
          label="Active Agents"
          value={stats?.active_agents ?? '—'}
          icon={<Bot size={18} />}
          accent={Boolean(stats?.active_agents)}
          sub={stats ? `of ${stats.total_agents} total` : undefined}
        />
        <StatCard
          label="Queue Depth"
          value={stats?.queue_depth ?? '—'}
          icon={<Activity size={18} />}
          sub={stats ? `${stats.queued_tasks} queued tasks` : undefined}
        />
        <StatCard
          label="Skills"
          value={stats?.total_skills ?? '—'}
          icon={<Puzzle size={18} />}
        />
        <StatCard
          label="Tasks Today"
          value={stats?.tasks_today ?? '—'}
          icon={<ListTodo size={18} />}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Recent tasks */}
        <div className="rounded-lg border border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <span className="text-xs font-semibold uppercase tracking-widest text-slate-500">Recent Tasks</span>
            <span className="font-mono text-xs text-slate-700">{tasksData?.total ?? 0} total</span>
          </div>
          {recentTasks.length === 0 ? (
            <p className="px-4 py-8 text-center text-xs text-slate-700">No tasks yet</p>
          ) : (
            <ul className="divide-y divide-border">
              {recentTasks.map(task => (
                <li key={task.id} className="flex items-center gap-3 px-4 py-2.5 hover:bg-raised/50">
                  <StatusBadge status={task.status} size="sm" />
                  <span className="min-w-0 flex-1 truncate text-xs text-slate-400">{task.description}</span>
                  <span className="shrink-0 font-mono text-xs text-slate-700">{ago(task.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Agent status grid */}
        <div className="rounded-lg border border-border bg-surface">
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <span className="text-xs font-semibold uppercase tracking-widest text-slate-500">Agents</span>
            <span className="font-mono text-xs text-slate-700">{agents.length} registered</span>
          </div>
          {agents.length === 0 ? (
            <p className="px-4 py-8 text-center text-xs text-slate-700">No agents registered</p>
          ) : (
            <div className="grid grid-cols-2 gap-2 p-3">
              {agents.map(agent => (
                <div key={agent.id} className="rounded-md border border-border bg-base p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate font-mono text-xs font-bold text-slate-300">{agent.name}</p>
                      <p className="mt-0.5 truncate text-xs text-slate-600">{agent.role || '—'}</p>
                    </div>
                    <StatusBadge status={agent.status} size="sm" />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
