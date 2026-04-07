import { useState, useEffect } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { LayoutDashboard, Bot, ListTodo, Puzzle, Settings, Menu, X, Zap } from 'lucide-react'
import { healthCheck } from '../api/client'

const NAV = [
  { to: '/',         label: 'Dashboard', icon: LayoutDashboard },
  { to: '/agents',   label: 'Agents',    icon: Bot },
  { to: '/tasks',    label: 'Tasks',     icon: ListTodo },
  { to: '/skills',   label: 'Skills',    icon: Puzzle },
  { to: '/settings', label: 'Settings',  icon: Settings },
]

export function Layout() {
  const [collapsed, setCollapsed] = useState(false)
  const [connected, setConnected] = useState<boolean | null>(null)

  useEffect(() => {
    const check = () =>
      healthCheck()
        .then(() => setConnected(true))
        .catch(() => setConnected(false))
    check()
    const id = setInterval(check, 15_000)
    return () => clearInterval(id)
  }, [])

  return (
    <div
      className="flex h-screen w-screen overflow-hidden bg-base font-sans text-slate-200"
      style={{
        backgroundImage:
          "radial-gradient(circle, rgba(26,39,68,0.5) 1px, transparent 1px)",
        backgroundSize: "28px 28px",
      }}
    >
      {/* Sidebar */}
      <aside
        className={`
          relative flex shrink-0 flex-col border-r border-border bg-base/80 backdrop-blur-sm
          transition-[width] duration-300 ease-in-out
          ${collapsed ? 'w-14' : 'w-52'}
        `}
        style={{ boxShadow: '1px 0 0 rgba(59,130,246,0.08)' }}
      >
        {/* Logo */}
        <div className="flex h-14 items-center gap-2.5 border-b border-border px-3">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-accent/10 text-accent ring-1 ring-accent/20">
            <Zap size={14} />
          </div>
          {!collapsed && (
            <span className="font-mono text-xs font-bold tracking-widest text-slate-300">
              orcai-mcp
            </span>
          )}
          <button
            onClick={() => setCollapsed(c => !c)}
            className="ml-auto rounded p-1 text-slate-600 hover:text-slate-400"
          >
            {collapsed ? <Menu size={14} /> : <X size={14} />}
          </button>
        </div>

        {/* Nav */}
        <nav className="flex flex-1 flex-col gap-0.5 p-2">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-md px-2.5 py-2 text-xs font-medium transition-colors
                ${isActive
                  ? 'bg-accent/10 text-accent ring-1 ring-accent/20'
                  : 'text-slate-500 hover:bg-raised hover:text-slate-300'
                }`
              }
            >
              <Icon size={15} className="shrink-0" />
              {!collapsed && <span>{label}</span>}
            </NavLink>
          ))}
        </nav>

        {/* Connection dot */}
        <div className={`flex items-center gap-2 border-t border-border p-3 ${collapsed ? 'justify-center' : ''}`}>
          <span
            className={`h-2 w-2 rounded-full ${
              connected === null ? 'bg-slate-600' :
              connected ? 'bg-emerald-400 animate-pulse-slow' : 'bg-red-500'
            }`}
          />
          {!collapsed && (
            <span className="font-mono text-xs text-slate-600">
              {connected === null ? 'checking…' : connected ? 'connected' : 'offline'}
            </span>
          )}
        </div>
      </aside>

      {/* Main */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Topbar */}
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-base/60 px-6 backdrop-blur-sm">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-slate-600">:8100</span>
          </div>
          <div className="flex items-center gap-2">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                connected === null ? 'bg-slate-600' :
                connected ? 'bg-emerald-400' : 'bg-red-500'
              }`}
            />
            <span className="font-mono text-xs text-slate-500">
              {connected === null ? '—' : connected ? 'ok' : 'unreachable'}
            </span>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto">
          <div className="animate-fade-in p-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
