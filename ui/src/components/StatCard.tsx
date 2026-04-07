import type { ReactNode } from 'react'

interface Props {
  label: string
  value: number | string
  icon: ReactNode
  accent?: boolean
  sub?: string
}

export function StatCard({ label, value, icon, accent, sub }: Props) {
  return (
    <div
      className={`
        relative overflow-hidden rounded-lg border p-5
        bg-surface border-border
        transition-colors hover:border-border-bright
        ${accent ? 'ring-1 ring-accent/20' : ''}
      `}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium tracking-widest text-slate-500 uppercase">{label}</p>
          <p className={`mt-1.5 font-mono text-3xl font-bold tabular-nums ${accent ? 'text-accent' : 'text-slate-100'}`}>
            {value}
          </p>
          {sub && <p className="mt-1 text-xs text-slate-600">{sub}</p>}
        </div>
        <div className={`rounded-md p-2 ${accent ? 'bg-accent/10 text-accent' : 'bg-raised text-slate-500'}`}>
          {icon}
        </div>
      </div>
      {accent && (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-transparent via-accent/40 to-transparent" />
      )}
    </div>
  )
}
