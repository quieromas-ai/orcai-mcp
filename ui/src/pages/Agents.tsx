import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Editor from '@monaco-editor/react'
import { Plus, Pencil, Trash2, ChevronUp, ChevronDown } from 'lucide-react'
import { fetchAgents, createAgent, updateAgent, deleteAgent } from '../api/agents'
import { Drawer } from '../components/Drawer'
import { StatusBadge } from '../components/StatusBadge'
import { EmptyState } from '../components/EmptyState'
import { Bot } from 'lucide-react'
import type { Agent, AgentCreate, AgentRunner, AgentStatus } from '../types'

const MODELS = ['claude-sonnet-4-6', 'claude-opus-4-6', 'claude-haiku-4-5-20251001']

const EMPTY_FORM: AgentCreate = {
  name: '',
  role: '',
  system_prompt: '',
  model_preference: 'claude-sonnet-4-6',
  config: { runner: 'api' },
}

type SortField = 'name' | 'role' | 'status' | 'model_preference'

function Input({ label, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-slate-400">{label}</span>
      <input
        className="w-full rounded-md border border-border bg-base px-3 py-2 text-sm text-slate-200 outline-none placeholder:text-slate-700 focus:border-accent focus:ring-1 focus:ring-accent/30"
        {...props}
      />
    </label>
  )
}

export function Agents() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['agents'], queryFn: fetchAgents })

  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<Agent | null>(null)
  const [form, setForm] = useState<AgentCreate>(EMPTY_FORM)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [sortField, setSortField] = useState<SortField>('name')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  const invalidate = () => qc.invalidateQueries({ queryKey: ['agents'] })

  const createMut = useMutation({
    mutationFn: createAgent,
    onSuccess: () => { invalidate(); closeDrawer() },
  })
  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof updateAgent>[1] }) =>
      updateAgent(id, data),
    onSuccess: () => { invalidate(); closeDrawer() },
  })
  const deleteMut = useMutation({
    mutationFn: deleteAgent,
    onSuccess: () => { invalidate(); setDeletingId(null) },
  })

  function openCreate() {
    setEditing(null)
    setForm(EMPTY_FORM)
    setOpen(true)
  }

  function openEdit(agent: Agent) {
    setEditing(agent)
    setForm({
      name: agent.name,
      role: agent.role,
      system_prompt: agent.system_prompt,
      model_preference: agent.model_preference,
      config: { runner: ((agent.config?.runner as AgentRunner) ?? 'api') },
    })
    setOpen(true)
  }

  function closeDrawer() {
    setOpen(false)
    setEditing(null)
  }

  function handleSubmit() {
    if (editing) {
      updateMut.mutate({ id: editing.id, data: { ...form } })
    } else {
      createMut.mutate(form)
    }
  }

  function toggleSort(field: SortField) {
    if (sortField === field) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortField(field); setSortDir('asc') }
  }

  function toggleStatus(agent: Agent) {
    const next: AgentStatus = agent.status === 'disabled' ? 'idle' : 'disabled'
    updateMut.mutate({ id: agent.id, data: { status: next } })
  }

  const agents = [...(data?.agents ?? [])].sort((a, b) => {
    const av = a[sortField] as string
    const bv = b[sortField] as string
    return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av)
  })

  const SortIcon = ({ field }: { field: SortField }) =>
    sortField === field ? (
      sortDir === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />
    ) : (
      <ChevronUp size={12} className="opacity-20" />
    )

  const Th = ({ field, label }: { field: SortField; label: string }) => (
    <th
      onClick={() => toggleSort(field)}
      className="cursor-pointer select-none border-b border-border px-4 py-3 text-left text-xs font-semibold uppercase tracking-widest text-slate-500 hover:text-slate-400"
    >
      <span className="flex items-center gap-1">
        {label}
        <SortIcon field={field} />
      </span>
    </th>
  )

  const isPending = createMut.isPending || updateMut.isPending

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold text-slate-200">Agents</h1>
          <p className="mt-0.5 text-xs text-slate-600">{data?.total ?? 0} registered</p>
        </div>
        <button
          onClick={openCreate}
          className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-blue-500"
        >
          <Plus size={13} />
          New Agent
        </button>
      </div>

      <div className="rounded-lg border border-border bg-surface">
        {isLoading ? (
          <div className="flex items-center justify-center py-16 text-xs text-slate-600">Loading…</div>
        ) : agents.length === 0 ? (
          <EmptyState
            icon={<Bot size={24} />}
            title="No agents yet"
            description="Create your first agent to start delegating tasks."
            action={
              <button
                onClick={openCreate}
                className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-2 text-xs font-semibold text-white hover:bg-blue-500"
              >
                <Plus size={13} /> New Agent
              </button>
            }
          />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr>
                <Th field="name" label="Name" />
                <Th field="role" label="Role" />
                <Th field="status" label="Status" />
                <Th field="model_preference" label="Model" />
                <th className="border-b border-border px-4 py-3 text-left text-xs font-semibold uppercase tracking-widest text-slate-500">Runner</th>
                <th className="border-b border-border px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {agents.map(agent => (
                <tr key={agent.id} className="group border-b border-border/50 hover:bg-raised/40">
                  <td className="px-4 py-3">
                    <span className="font-mono text-xs font-bold text-slate-300">{agent.name}</span>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">{agent.role || '—'}</td>
                  <td className="px-4 py-3">
                    <button onClick={() => toggleStatus(agent)} className="transition-opacity hover:opacity-80">
                      <StatusBadge status={agent.status} size="sm" />
                    </button>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-600">{agent.model_preference}</td>
                  <td className="px-4 py-3">
                    <span className={`font-mono text-xs ${(agent.config?.runner as string) === 'cli' ? 'text-amber-400' : 'text-sky-400'}`}>
                      {(agent.config?.runner as string) ?? 'api'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                      <button
                        onClick={() => openEdit(agent)}
                        className="rounded p-1 text-slate-600 hover:bg-raised hover:text-slate-300"
                      >
                        <Pencil size={13} />
                      </button>
                      {deletingId === agent.id ? (
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => deleteMut.mutate(agent.id)}
                            className="rounded px-2 py-0.5 text-xs font-semibold text-rose-400 hover:bg-rose-950"
                          >
                            Confirm
                          </button>
                          <button
                            onClick={() => setDeletingId(null)}
                            className="rounded px-2 py-0.5 text-xs text-slate-600 hover:text-slate-400"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setDeletingId(agent.id)}
                          className="rounded p-1 text-slate-600 hover:bg-rose-950 hover:text-rose-400"
                        >
                          <Trash2 size={13} />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <Drawer
        open={open}
        onClose={closeDrawer}
        title={editing ? `Edit — ${editing.name}` : 'New Agent'}
        footer={
          <div className="flex items-center justify-end gap-2">
            <button onClick={closeDrawer} className="rounded-md px-4 py-2 text-xs text-slate-500 hover:text-slate-300">
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={isPending || !form.name}
              className="rounded-md bg-accent px-4 py-2 text-xs font-semibold text-white disabled:opacity-50 hover:bg-blue-500"
            >
              {isPending ? 'Saving…' : editing ? 'Save Changes' : 'Create Agent'}
            </button>
          </div>
        }
      >
        <div className="space-y-4">
          <Input label="Name *" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="e.g. Frontend Dev" />
          <Input label="Role" value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value }))} placeholder="e.g. frontend, backend" />

          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-slate-400">Model</span>
            <select
              value={form.model_preference}
              onChange={e => setForm(f => ({ ...f, model_preference: e.target.value }))}
              className="w-full rounded-md border border-border bg-base px-3 py-2 text-sm text-slate-200 outline-none focus:border-accent"
            >
              {MODELS.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          </label>

          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-slate-400">Runner</span>
            <div className="flex rounded-md border border-border bg-base p-0.5">
              {(['api', 'cli'] as AgentRunner[]).map(r => (
                <button
                  key={r}
                  onClick={() => setForm(f => ({ ...f, config: { runner: r } }))}
                  className={`flex-1 rounded py-1.5 font-mono text-xs font-bold transition-colors
                    ${form.config.runner === r
                      ? r === 'cli' ? 'bg-amber-950 text-amber-300' : 'bg-sky-950 text-sky-300'
                      : 'text-slate-600 hover:text-slate-400'}`}
                >
                  {r.toUpperCase()}
                </button>
              ))}
            </div>
          </label>

          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-slate-400">System Prompt</span>
            <div className="overflow-hidden rounded-md border border-border">
              <Editor
                height={240}
                language="markdown"
                theme="vs-dark"
                value={form.system_prompt}
                onChange={v => setForm(f => ({ ...f, system_prompt: v ?? '' }))}
                options={{ minimap: { enabled: false }, fontSize: 12, lineNumbers: 'off', wordWrap: 'on', scrollBeyondLastLine: false, padding: { top: 8, bottom: 8 } }}
              />
            </div>
          </label>

          {(createMut.error || updateMut.error) && (
            <p className="text-xs text-rose-400">
              {(createMut.error ?? updateMut.error)?.message}
            </p>
          )}
        </div>
      </Drawer>
    </div>
  )
}
