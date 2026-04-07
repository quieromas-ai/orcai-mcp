import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Copy, Check, Eye, EyeOff } from 'lucide-react'
import { healthCheck } from '../api/client'

interface HealthData {
  status: string
  agents: number
  queue_depth: number
}

export function Settings() {
  const [tokenVisible, setTokenVisible] = useState(false)
  const [copied, setCopied] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<HealthData | null>(null)
  const [testError, setTestError] = useState<string | null>(null)

  const baseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8100'
  const mcpUrl = `${baseUrl}/mcp`

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: healthCheck,
    retry: false,
  })

  async function copyUrl() {
    await navigator.clipboard.writeText(mcpUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  async function testConnection() {
    setTesting(true)
    setTestResult(null)
    setTestError(null)
    try {
      const res = await healthCheck()
      setTestResult(res as HealthData)
    } catch {
      setTestError('Could not reach server')
    } finally {
      setTesting(false)
    }
  }

  const Section = ({ title, children }: { title: string; children: React.ReactNode }) => (
    <div className="rounded-lg border border-border bg-surface">
      <div className="border-b border-border px-5 py-3">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-500">{title}</h2>
      </div>
      <div className="space-y-4 p-5">{children}</div>
    </div>
  )

  const Row = ({ label, children }: { label: string; children: React.ReactNode }) => (
    <div className="flex items-center justify-between gap-4">
      <span className="shrink-0 text-xs text-slate-500">{label}</span>
      <div className="min-w-0 flex-1 text-right">{children}</div>
    </div>
  )

  return (
    <div className="mx-auto max-w-xl space-y-5">
      <div>
        <h1 className="text-base font-semibold text-slate-200">Settings</h1>
        <p className="mt-0.5 text-xs text-slate-600">Server configuration and connection info</p>
      </div>

      <Section title="Connection">
        <Row label="Server URL">
          <div className="flex items-center justify-end gap-2">
            <span className="font-mono text-xs text-slate-400">{baseUrl}</span>
            <button onClick={copyUrl} className="rounded p-1 text-slate-600 hover:text-slate-300">
              {copied ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
            </button>
          </div>
        </Row>
        <Row label="MCP Endpoint">
          <span className="font-mono text-xs text-accent">{mcpUrl}</span>
        </Row>
        <Row label="Status">
          <div className="flex items-center justify-end gap-1.5">
            <span className={`h-1.5 w-1.5 rounded-full ${health?.status === 'ok' ? 'bg-emerald-400' : 'bg-red-500'}`} />
            <span className="font-mono text-xs text-slate-400">
              {health?.status === 'ok' ? 'connected' : 'unreachable'}
            </span>
          </div>
        </Row>

        <div className="pt-1">
          <button
            onClick={testConnection}
            disabled={testing}
            className="rounded-md border border-border px-3 py-1.5 text-xs text-slate-400 transition-colors hover:border-accent/50 hover:text-slate-200 disabled:opacity-50"
          >
            {testing ? 'Testing…' : 'Test Connection'}
          </button>
          {testResult && (
            <div className="mt-2 rounded-md border border-emerald-800 bg-emerald-950/30 p-3 font-mono text-xs">
              <p className="text-emerald-400">✓ Connected</p>
              <p className="mt-1 text-slate-500">agents: {testResult.agents} · queue: {testResult.queue_depth}</p>
            </div>
          )}
          {testError && (
            <div className="mt-2 rounded-md border border-rose-900 bg-rose-950/30 p-3 font-mono text-xs text-rose-400">
              ✗ {testError}
            </div>
          )}
        </div>
      </Section>

      <Section title="Authentication">
        <Row label="Auth Token">
          <div className="flex items-center justify-end gap-2">
            <span className="font-mono text-xs text-slate-500">
              {tokenVisible ? (import.meta.env.VITE_AUTH_TOKEN ?? '(not set)') : '••••••••••••'}
            </span>
            <button
              onClick={() => setTokenVisible(v => !v)}
              className="rounded p-1 text-slate-600 hover:text-slate-300"
            >
              {tokenVisible ? <EyeOff size={13} /> : <Eye size={13} />}
            </button>
          </div>
        </Row>
        <p className="text-xs text-slate-700">
          Set <code className="font-mono text-slate-500">MCP_AUTH_TOKEN</code> env var on the server.
          Disable auth with <code className="font-mono text-slate-500">MCP_AUTH_DISABLED=true</code>.
        </p>
      </Section>

      <Section title="Capacity">
        <Row label="Max Concurrent Agents">
          <span className="font-mono text-xs text-slate-300">{health ? '3' : '—'}</span>
        </Row>
        <Row label="Queue Depth">
          <span className="font-mono text-xs text-slate-300">{health?.queue_depth ?? '—'}</span>
        </Row>
        <p className="text-xs text-slate-700">
          Configure via <code className="font-mono text-slate-500">MAX_CONCURRENT_AGENTS</code> and <code className="font-mono text-slate-500">TASK_QUEUE_SIZE</code> env vars.
        </p>
      </Section>

      <Section title="IDE Integration">
        <div className="space-y-2">
          <p className="text-xs text-slate-500">Register this server with Claude Code:</p>
          <pre className="overflow-x-auto rounded-md border border-border bg-base p-3 font-mono text-xs text-slate-400">
            {`orcai-mcp register --ide claude`}
          </pre>
          <p className="text-xs text-slate-500">Or add manually to <code className="text-slate-400">.mcp.json</code>:</p>
          <pre className="overflow-x-auto rounded-md border border-border bg-base p-3 font-mono text-xs text-slate-400">
            {`{\n  "mcpServers": {\n    "orcai-mcp": {\n      "type": "http",\n      "url": "${mcpUrl}"\n    }\n  }\n}`}
          </pre>
        </div>
      </Section>
    </div>
  )
}
