import type { ReactNode } from 'react'

interface Props {
  icon: ReactNode
  title: string
  description?: string
  action?: ReactNode
}

export function EmptyState({ icon, title, description, action }: Props) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="mb-4 rounded-full border border-border bg-raised p-4 text-slate-600">
        {icon}
      </div>
      <p className="text-sm font-semibold text-slate-400">{title}</p>
      {description && <p className="mt-1 text-xs text-slate-600">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
