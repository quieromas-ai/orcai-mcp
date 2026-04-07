import type { AgentStatus, TaskStatus } from '../types'

type Status = AgentStatus | TaskStatus

const CONFIG: Record<Status, { dot: string; text: string; bg: string; border: string; pulse?: boolean }> = {
  idle:      { dot: 'bg-slate-500',   text: 'text-slate-400',  bg: 'bg-slate-900',   border: 'border-slate-700' },
  busy:      { dot: 'bg-amber-400',   text: 'text-amber-300',  bg: 'bg-amber-950',   border: 'border-amber-800', pulse: true },
  disabled:  { dot: 'bg-red-500',     text: 'text-red-400',    bg: 'bg-red-950',     border: 'border-red-900' },
  queued:    { dot: 'bg-sky-400',     text: 'text-sky-300',    bg: 'bg-sky-950',     border: 'border-sky-800' },
  running:   { dot: 'bg-emerald-400', text: 'text-emerald-300',bg: 'bg-emerald-950', border: 'border-emerald-800', pulse: true },
  completed: { dot: 'bg-emerald-500', text: 'text-emerald-400',bg: 'bg-emerald-950', border: 'border-emerald-800' },
  failed:    { dot: 'bg-rose-500',    text: 'text-rose-400',   bg: 'bg-rose-950',    border: 'border-rose-900' },
  cancelled: { dot: 'bg-slate-600',   text: 'text-slate-500',  bg: 'bg-slate-900',   border: 'border-slate-700' },
}

interface Props {
  status: Status
  size?: 'sm' | 'md'
}

export function StatusBadge({ status, size = 'md' }: Props) {
  const c = CONFIG[status] ?? CONFIG.idle
  const px = size === 'sm' ? 'px-1.5 py-0.5 text-xs' : 'px-2 py-0.5 text-xs'

  return (
    <span className={`inline-flex items-center gap-1.5 rounded border font-mono ${px} ${c.bg} ${c.border} ${c.text}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${c.dot} ${c.pulse ? 'animate-pulse-slow' : ''}`} />
      {status}
    </span>
  )
}
