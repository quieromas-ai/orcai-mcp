import { useEffect, type ReactNode } from 'react'
import { X } from 'lucide-react'

interface Props {
  open: boolean
  onClose: () => void
  title: string
  children: ReactNode
  footer?: ReactNode
  width?: string
}

export function Drawer({ open, onClose, title, children, footer, width = 'w-[540px]' }: Props) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    if (open) document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open, onClose])

  return (
    <>
      {/* Backdrop */}
      <div
        className={`fixed inset-0 z-40 bg-black/70 backdrop-blur-sm transition-opacity duration-200 ${open ? 'opacity-100' : 'pointer-events-none opacity-0'}`}
        onClick={onClose}
      />

      {/* Panel */}
      <div
        className={`
          fixed right-0 top-0 z-50 flex h-full flex-col border-l border-border bg-surface
          shadow-2xl transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]
          ${width}
          ${open ? 'translate-x-0' : 'translate-x-full'}
        `}
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-border px-6 py-4">
          <h2 className="text-sm font-semibold text-slate-200">{title}</h2>
          <button
            onClick={onClose}
            className="rounded p-1 text-slate-500 transition-colors hover:bg-raised hover:text-slate-300"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5">
          {children}
        </div>

        {/* Footer */}
        {footer && (
          <div className="shrink-0 border-t border-border px-6 py-4">
            {footer}
          </div>
        )}
      </div>
    </>
  )
}
