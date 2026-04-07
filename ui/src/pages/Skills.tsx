import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import Editor from '@monaco-editor/react'
import { Plus, Puzzle } from 'lucide-react'
import { fetchSkills, installSkill } from '../api/skills'
import { fetchAgents } from '../api/agents'
import { Drawer } from '../components/Drawer'
import { EmptyState } from '../components/EmptyState'
import type { SkillCreate } from '../types'

const EMPTY_FORM: SkillCreate = {
  name: '',
  description: '',
  content: '# Skill\n\nDescribe what this skill does and how agents should use it.\n',
  version: '1.0.0',
  assign_to: [],
}

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

export function Skills() {
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({ queryKey: ['skills'], queryFn: fetchSkills })
  const { data: agentsData } = useQuery({ queryKey: ['agents'], queryFn: fetchAgents })

  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<SkillCreate>(EMPTY_FORM)

  const installMut = useMutation({
    mutationFn: installSkill,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['skills'] })
      setOpen(false)
      setForm(EMPTY_FORM)
    },
  })

  const skills = data?.skills ?? []
  const agents = agentsData?.agents ?? []

  function toggleAgent(id: string) {
    setForm(f => ({
      ...f,
      assign_to: f.assign_to.includes(id)
        ? f.assign_to.filter(a => a !== id)
        : [...f.assign_to, id],
    }))
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold text-slate-200">Skills</h1>
          <p className="mt-0.5 text-xs text-slate-600">{data?.total ?? 0} installed</p>
        </div>
        <button
          onClick={() => setOpen(true)}
          className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-blue-500"
        >
          <Plus size={13} />
          Install Skill
        </button>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-16 text-xs text-slate-600">Loading…</div>
      ) : skills.length === 0 ? (
        <EmptyState
          icon={<Puzzle size={24} />}
          title="No skills installed"
          description="Install reusable instruction sets that agents can apply to tasks."
          action={
            <button
              onClick={() => setOpen(true)}
              className="flex items-center gap-1.5 rounded-md bg-accent px-3 py-2 text-xs font-semibold text-white hover:bg-blue-500"
            >
              <Plus size={13} /> Install Skill
            </button>
          }
        />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {skills.map(skill => (
            <div
              key={skill.id}
              className="flex flex-col rounded-lg border border-border bg-surface p-4 transition-colors hover:border-border-bright"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <div className="rounded-md border border-border bg-raised p-1.5 text-accent">
                    <Puzzle size={13} />
                  </div>
                  <span className="font-mono text-xs font-bold text-slate-200">{skill.name}</span>
                </div>
                <span className="shrink-0 rounded border border-border px-1.5 py-0.5 font-mono text-xs text-slate-600">
                  v{skill.version}
                </span>
              </div>

              {skill.description && (
                <p className="mt-2 text-xs text-slate-500 line-clamp-2">{skill.description}</p>
              )}

              <p className="mt-3 truncate font-mono text-xs text-slate-700">{skill.file_path}</p>
            </div>
          ))}
        </div>
      )}

      <Drawer
        open={open}
        onClose={() => { setOpen(false); setForm(EMPTY_FORM) }}
        title="Install Skill"
        footer={
          <div className="flex items-center justify-end gap-2">
            <button
              onClick={() => { setOpen(false); setForm(EMPTY_FORM) }}
              className="rounded-md px-4 py-2 text-xs text-slate-500 hover:text-slate-300"
            >
              Cancel
            </button>
            <button
              onClick={() => installMut.mutate(form)}
              disabled={installMut.isPending || !form.name || !form.content}
              className="rounded-md bg-accent px-4 py-2 text-xs font-semibold text-white disabled:opacity-50 hover:bg-blue-500"
            >
              {installMut.isPending ? 'Installing…' : 'Install'}
            </button>
          </div>
        }
      >
        <div className="space-y-4">
          <Input label="Name *" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="e.g. react-component" />
          <Input label="Description" value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} placeholder="What does this skill do?" />
          <Input label="Version" value={form.version} onChange={e => setForm(f => ({ ...f, version: e.target.value }))} />

          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-slate-400">Content *</span>
            <div className="overflow-hidden rounded-md border border-border">
              <Editor
                height={280}
                language="markdown"
                theme="vs-dark"
                value={form.content}
                onChange={v => setForm(f => ({ ...f, content: v ?? '' }))}
                options={{ minimap: { enabled: false }, fontSize: 12, lineNumbers: 'off', wordWrap: 'on', scrollBeyondLastLine: false, padding: { top: 8, bottom: 8 } }}
              />
            </div>
          </label>

          {agents.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-medium text-slate-400">Assign to agents</p>
              <div className="space-y-1.5 rounded-md border border-border bg-base p-3">
                {agents.map(agent => (
                  <label key={agent.id} className="flex cursor-pointer items-center gap-2.5">
                    <input
                      type="checkbox"
                      checked={form.assign_to.includes(agent.id)}
                      onChange={() => toggleAgent(agent.id)}
                      className="rounded border-border accent-accent"
                    />
                    <span className="font-mono text-xs text-slate-300">{agent.name}</span>
                    <span className="text-xs text-slate-600">{agent.role}</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          {installMut.error && (
            <p className="text-xs text-rose-400">{installMut.error.message}</p>
          )}
        </div>
      </Drawer>
    </div>
  )
}
