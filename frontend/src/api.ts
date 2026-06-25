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

function buildHeaders(includeContentType = false): Record<string, string> {
  const headers: Record<string, string> = {}
  if (includeContentType) {
    headers['Content-Type'] = 'application/json'
  }
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

export interface ScoreBreakdown {
  score: number | null
  fit: string
  matched_keywords: string[]
  missing_skills: string[]
  fit_notes: string
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
  score_breakdown?: ScoreBreakdown | null
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
  notes?: string
}

export interface ApplicationUpsert {
  company: string
  role: string
  link?: string
  location?: string
  remote_type?: string
  notes?: string
  status?: string
  match_profile?: string
  source?: string
}

export interface JobUrlExtractPayload {
  url: string
}

export interface JobUrlExtractResult {
  url: string
  source: string
  page_title: string
  company: string
  role: string
  location: string
  remote_type: string
  description: string
}

export interface DiscoveryRunPayload {
  limit?: number
  min_score?: number
  max_age_days?: number
  include_stretch?: boolean
  profile?: 'de' | 'swe' | 'sre' | 'other'
  salary_min_usd?: number
  timezones?: string[]
  seniority?: 'junior' | 'mid' | 'senior'
  use_outcome_priors?: boolean
  prior_lookback_days?: number
  source_prior_weight?: number
  role_prior_weight?: number
  use_llm_reranker?: boolean
  llm_top_n?: number
  llm_weight?: number
  llm_model?: string
  llm_api_base_url?: string
  llm_dry_run?: boolean
  llm_max_calls?: number
  llm_max_input_chars?: number
  llm_max_retries?: number
  llm_retry_backoff_seconds?: number
  llm_timeout_seconds?: number
  output_dir?: string
  cv_path?: string
  api_base_url?: string
  verbose?: boolean
  sources?: string[]
}

export interface SourceRunResult {
  key: string
  label: string
  collected: number
  error: string
}

export interface DiscoveryRunResult {
  exit_code: number
  command: string[]
  stdout: string
  stderr: string
  source_results: SourceRunResult[]
  strict_count: number
  broad_count: number
  synced_count: number
  failed_count: number
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
    headers: buildHeaders(),
  })
  if (!res.ok) throw await toApiError(res, path)
  return res.json() as Promise<T>
}

async function apiPatch<T>(path: string, payload: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PATCH',
    headers: buildHeaders(true),
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw await toApiError(res, path)
  return res.json() as Promise<T>
}

async function apiPost<T>(path: string, payload?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: buildHeaders(true),
    body: payload === undefined ? undefined : JSON.stringify(payload),
  })
  if (!res.ok) throw await toApiError(res, path)
  return res.json() as Promise<T>
}

async function apiPut<T>(path: string, payload: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PUT',
    headers: buildHeaders(true),
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw await toApiError(res, path)
  return res.json() as Promise<T>
}

async function apiDelete(path: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'DELETE',
    headers: buildHeaders(true),
  })
  if (!res.ok) throw await toApiError(res, path)
}

export interface PaginatedApplications {
  items: ApplicationItem[]
  total: number
  limit: number
  offset: number
}

export const fetchApplications = (limit = 50, offset = 0) =>
  apiFetch<PaginatedApplications>(`/applications?limit=${limit}&offset=${offset}`)
export const updateApplication = (id: number, payload: ApplicationPatch) =>
  apiPatch<ApplicationItem>(`/applications/${id}`, payload)
export const deleteApplication = (id: number) =>
  apiDelete(`/applications/${id}`)
export const upsertApplication = (payload: ApplicationUpsert) =>
  apiPost<ApplicationItem>('/applications/upsert', payload)
export const extractJobFromUrl = (payload: JobUrlExtractPayload) =>
  apiPost<JobUrlExtractResult>('/applications/extract-url', payload)
export const runDiscovery = (payload: DiscoveryRunPayload) =>
  apiPost<DiscoveryRunResult>('/run-discovery', payload)

export type DiscoveryStatus = {
  in_flight: boolean
  elapsed_seconds: number | null
  cooldown_seconds_remaining: number | null
}

export const fetchDiscoveryStatus = () =>
  apiFetch<DiscoveryStatus>('/discovery/status')
export const generateDocuments = (id: number, payload: GenerateDocumentsPayload) =>
  apiPost<GenerateDocumentsResult>(`/applications/${id}/generate-documents`, payload)
export const readWorkspaceFile = (path: string) =>
  apiFetch<WorkspaceFileResult>(`/workspace-file?path=${encodeURIComponent(path)}`)
export const writeWorkspaceFile = (path: string, content: string) =>
  apiPut<WorkspaceFileResult>('/workspace-file', { path, content })

