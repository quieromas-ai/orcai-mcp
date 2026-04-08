const BASE = import.meta.env.VITE_API_BASE_URL ?? ''
const API = `${BASE}/api/v1`

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (res.status === 204) return undefined as T
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error((body as { detail?: string }).detail ?? res.statusText)
  }
  return res.json() as Promise<T>
}

export const get  = <T>(path: string)                    => request<T>(path)
export const post = <T>(path: string, data: unknown)     => request<T>(path, { method: 'POST', body: JSON.stringify(data) })
export const patch = <T>(path: string, data: unknown)    => request<T>(path, { method: 'PATCH', body: JSON.stringify(data) })
export const del  = (path: string)                       => request<void>(path, { method: 'DELETE' })
export const healthCheck = () => fetch(`${BASE}/health`).then(r => r.json())
