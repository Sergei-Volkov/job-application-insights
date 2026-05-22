// All API requests go through /api.

const BASE = '/api'
const WRITE_API_KEY = (import.meta.env.VITE_WRITE_API_KEY as string | undefined)?.trim()

export class ApiError extends Error {
  status: number
  path: string
  detail?: string

  constructor(status: number, path: string, detail?: string) {
    const message = detail ? `API error: ${status} ${path} - ${detail}` : `API error: ${status} ${path}`
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.path = path
    this.detail = detail
  }
}

function writeHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (WRITE_API_KEY) {
    headers['X-API-Key'] = WRITE_API_KEY
  }
  return headers
}

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}
  if (WRITE_API_KEY) {
    headers['X-API-Key'] = WRITE_API_KEY
  }
  return headers
}

type ErrorPayload = {
  detail?: unknown
}

async function toApiError(res: Response, path: string): Promise<ApiError> {
  let detail: string | undefined
  const contentType = res.headers.get('content-type') || ''

  if (contentType.includes('application/json')) {
    try {
      const payload = (await res.json()) as ErrorPayload
      if (typeof payload.detail === 'string') {
        detail = payload.detail
      } else if (payload.detail !== undefined) {
        detail = JSON.stringify(payload.detail)
      }
    } catch {}
  } else {
    try {
      const text = (await res.text()).trim()
      if (text) detail = text
    } catch {}
  }

  return new ApiError(res.status, path, detail)
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
  match_profile: string
  first_seen_at: string
  last_seen_at: string
  listing_fingerprint: string
  change_note: string
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
  match_profile?: string
  first_seen_at?: string
  last_seen_at?: string
  listing_fingerprint?: string
  change_note?: string
  notes?: string
}

export interface DiscoveryRunPayload {
  limit?: number
  min_score?: number
  max_age_days?: number
  include_stretch?: boolean
  profile?: 'de' | 'swe' | 'other'
  salary_min_usd?: number
  timezones?: string[]
  seniority?: 'junior' | 'mid' | 'senior'
  cv_path?: string
  api_base_url?: string
  verbose?: boolean
  sources?: string[]
}

export interface DiscoveryRunResult {
  exit_code: number
  command: string[]
  stdout: string
  stderr: string
}

export interface GenerateDocumentsPayload {
  overwrite?: boolean
  author_name?: string
  your_name?: string
}

export interface GenerateDocumentsResult {
  vacancy_dir: string
  vacancy_path: string
  cv_path: string
  cover_letter_path: string
  notes_path: string
}

export interface WorkspaceFileResult {
  path: string
  content: string
}

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: authHeaders(),
  })
  if (!res.ok) throw await toApiError(res, path)
  return res.json() as Promise<T>
}

async function apiPatch<T>(path: string, payload: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PATCH',
    headers: writeHeaders(),
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw await toApiError(res, path)
  return res.json() as Promise<T>
}

async function apiPost<T>(path: string, payload?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: writeHeaders(),
    body: payload === undefined ? undefined : JSON.stringify(payload),
  })
  if (!res.ok) throw await toApiError(res, path)
  return res.json() as Promise<T>
}

async function apiPut<T>(path: string, payload: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PUT',
    headers: writeHeaders(),
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw await toApiError(res, path)
  return res.json() as Promise<T>
}

export const fetchStats = () => apiFetch<Stats>('/stats')
export const fetchSkills = () =>
  apiFetch<{ items: SkillItem[] }>('/missing-skills').then((d) => d.items)
export const fetchTrend = () =>
  apiFetch<{ items: TrendItem[] }>('/trend').then((d) => d.items)
export const fetchApplications = (limit = 500) =>
  apiFetch<ApplicationItem[]>(`/applications?limit=${limit}`)
export const updateApplication = (id: number, payload: ApplicationPatch) =>
  apiPatch<ApplicationItem>(`/applications/${id}`, payload)
export const runDiscovery = (payload: DiscoveryRunPayload) =>
  apiPost<DiscoveryRunResult>('/run-discovery', payload)
export const generateDocuments = (id: number, payload: GenerateDocumentsPayload) =>
  apiPost<GenerateDocumentsResult>(`/applications/${id}/generate-documents`, payload)
export const readWorkspaceFile = (path: string) =>
  apiFetch<WorkspaceFileResult>(`/workspace-file?path=${encodeURIComponent(path)}`)
export const writeWorkspaceFile = (path: string, content: string) =>
  apiPut<WorkspaceFileResult>('/workspace-file', { path, content })
