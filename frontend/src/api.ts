// All requests go through /api, which is proxied to the FastAPI backend:
// - In dev: Vite dev server proxy (vite.config.ts)
// - In Docker: nginx reverse proxy (nginx.conf)

const BASE = '/api'
const WRITE_API_KEY = (import.meta.env.VITE_WRITE_API_KEY as string | undefined)?.trim()

function writeHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (WRITE_API_KEY) {
    headers['X-API-Key'] = WRITE_API_KEY
  }
  return headers
}

export interface Stats {
  total_applications: number
  by_status: Record<string, number>
  by_stage: Record<string, number>
}

export interface SkillItem {
  skill: string
  count: number
}

export interface TrendItem {
  week: string
  count: number
}

export interface ApplicationItem {
  id: number
  selected: string
  date_found: string
  date_applied: string
  company: string
  role: string
  location: string
  source: string
  remote_type: string
  fit: string
  fit_score: number
  link: string
  status: string
  next_step: string
  follow_up_date: string
  resume_ref: string
  cover_letter_ref: string
  notes: string
}

export interface ApplicationPatch {
  selected?: string
  date_applied?: string
  status?: string
  next_step?: string
  follow_up_date?: string
  resume_ref?: string
  cover_letter_ref?: string
  notes?: string
}

export interface DiscoveryRunPayload {
  limit?: number
  min_score?: number
  max_age_days?: number
  include_stretch?: boolean
}

export interface DiscoveryRunResult {
  exit_code: number
  command: string[]
  stdout: string
  stderr: string
}

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`API error: ${res.status} ${path}`)
  return res.json() as Promise<T>
}

async function apiPatch<T>(path: string, payload: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PATCH',
    headers: writeHeaders(),
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`API error: ${res.status} ${path}`)
  return res.json() as Promise<T>
}

async function apiPost<T>(path: string, payload?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: writeHeaders(),
    body: payload === undefined ? undefined : JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`API error: ${res.status} ${path}`)
  return res.json() as Promise<T>
}

export const fetchStats = () => apiFetch<Stats>('/stats')
export const fetchSkills = () =>
  apiFetch<{ items: SkillItem[] }>('/missing-skills').then((d) => d.items)
export const fetchTrend = () =>
  apiFetch<{ items: TrendItem[] }>('/trend').then((d) => d.items)
export const fetchApplications = (limit = 25) =>
  apiFetch<ApplicationItem[]>(`/applications?limit=${limit}`)
export const updateApplication = (id: number, payload: ApplicationPatch) =>
  apiPatch<ApplicationItem>(`/applications/${id}`, payload)
export const runDiscovery = (payload: DiscoveryRunPayload) =>
  apiPost<DiscoveryRunResult>('/run-discovery', payload)
