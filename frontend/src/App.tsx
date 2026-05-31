import { useEffect, useMemo, useRef, useState } from 'react'
import {
  fetchApplications,
  runDiscovery,
  fetchDiscoveryStatus,
  ApiError,
  generateDocuments,
  readWorkspaceFile,
  updateApplication,
  deleteApplication,
  upsertApplication,
  writeWorkspaceFile,
  type DiscoveryStatus,
  type GenerateDocumentsResult,
  type DiscoveryRunResult,
  type ApplicationItem,
} from './api'
import { DISCOVERY_SOURCES, NEXT_STEP_OPTIONS } from './appConstants'
import type { AppPage, DiscoveryProfile, EditableRow, GeneratedDocsMap, ListingFilter } from './appTypes'
import { getRowDocLinks } from './utils/docs'
import { filterApplications, isNewListing, isUpdatedListing, normalizedProfile } from './utils/listing'
import { renderMarkdownPreview, renderTexPreview } from './utils/preview'
import AnalyticsPage from './pages/AnalyticsPage'
import './App.css'

const SCORE_STRONG_MIN = 12
const SCORE_MEDIUM_MIN = 7

const DEFAULT_DISCOVERY_PARAMS = {
  limit: 40,
  min_score: 7,
  max_age_days: 45,
  include_stretch: false,
  salary_min_usd: '',
  timezones: '',
  seniority: '',
  use_outcome_priors: false,
  prior_lookback_days: 365,
  source_prior_weight: 1,
  role_prior_weight: 1,
  use_llm_reranker: false,
  llm_top_n: 20,
  llm_weight: 1,
  llm_model: '',
  llm_api_base_url: '',
  llm_dry_run: false,
  llm_max_calls: 20,
  llm_max_input_chars: 50000,
  llm_max_retries: 2,
  llm_retry_backoff_seconds: 0.5,
  llm_timeout_seconds: 20,
  output_dir: '',
}

type ScoreBreakdown = {
  score: number | null
  fit: string
  matchedKeywords: string[]
  missingSkills: string[]
  fitNotes: string
}

type LlmDryRunDiagnostics = {
  dryRun: boolean
  plannedCalls: number | null
  attempted: number | null
  adjusted: number | null
  usedInputChars: number | null
  warningsCount: number | null
}

export default function App() {
  const [applications, setApplications] = useState<EditableRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [discovering, setDiscovering] = useState(false)
  const [discoveryResult, setDiscoveryResult] = useState<DiscoveryRunResult | null>(null)
  const [discoveryProfile, setDiscoveryProfile] = useState<DiscoveryProfile>('de')
  const [profileFilter, setProfileFilter] = useState<'all' | DiscoveryProfile>('all')
  const [listingFilter, setListingFilter] = useState<ListingFilter>('all')
  const [sourceFilter, setSourceFilter] = useState('')
  const [generatedDocsById, setGeneratedDocsById] = useState<GeneratedDocsMap>({})
  const [activePage, setActivePage] = useState<AppPage>(() => {
    const saved = localStorage.getItem('activePage')
    return (saved as AppPage) || 'pipeline'
  })
  const [customNextStepById, setCustomNextStepById] = useState<Record<number, string>>({})
  const [discoveryParams, setDiscoveryParams] = useState<typeof DEFAULT_DISCOVERY_PARAMS>(() => {
    try {
      const saved = localStorage.getItem('discoveryParams')
      if (saved) return { ...DEFAULT_DISCOVERY_PARAMS, ...(JSON.parse(saved) as typeof DEFAULT_DISCOVERY_PARAMS) }
    } catch {}
    return DEFAULT_DISCOVERY_PARAMS
  })
  const [manualJobForm, setManualJobForm] = useState({ company: '', role: '', link: '', description: '' })
  const [discoveryCvPath, setDiscoveryCvPath] = useState<string>(() => localStorage.getItem('discoveryCvPath') || '')
  const [discoveryApiBaseUrl, setDiscoveryApiBaseUrl] = useState<string>(
    () => localStorage.getItem('discoveryApiBaseUrl') || ''
  )
  const [discoveryVerbose, setDiscoveryVerbose] = useState<boolean>(() => localStorage.getItem('discoveryVerbose') === 'true')
  const [discoverySourceSelection, setDiscoverySourceSelection] = useState<Record<string, boolean>>(
    () => Object.fromEntries(DISCOVERY_SOURCES.map((source) => [source.key, true]))
  )

  const [activeFilePath, setActiveFilePath] = useState('')
  const [fileContent, setFileContent] = useState('')
  const [fileDraft, setFileDraft] = useState('')
  const [fileLoading, setFileLoading] = useState(false)
  const [fileSaving, setFileSaving] = useState(false)
  const [fileDirty, setFileDirty] = useState(false)
  const [activeProcessId, setActiveProcessId] = useState<number | null>(null)
  const [lastProcessFileById, setLastProcessFileById] = useState<Record<number, string>>({})
  const editorSectionRef = useRef<HTMLElement | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const searchInputRef = useRef<HTMLInputElement | null>(null)
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null)
  const [cooldownSecsLeft, setCooldownSecsLeft] = useState(0)
  const [discoveryStatus, setDiscoveryStatus] = useState<DiscoveryStatus | null>(null)
  const discoveryPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadDashboard = (): Promise<void> => {
    setError(null)
    return Promise.all([fetchApplications()])
      .then(([a]) => {
        setApplications(a)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load data'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    localStorage.setItem('activePage', activePage)
  }, [activePage])

  useEffect(() => {
    localStorage.setItem('discoveryCvPath', discoveryCvPath)
  }, [discoveryCvPath])

  useEffect(() => {
    localStorage.setItem('discoveryApiBaseUrl', discoveryApiBaseUrl)
  }, [discoveryApiBaseUrl])

  useEffect(() => {
    localStorage.setItem('discoveryVerbose', discoveryVerbose ? 'true' : 'false')
  }, [discoveryVerbose])

  useEffect(() => {
    localStorage.setItem('discoveryParams', JSON.stringify(discoveryParams))
  }, [discoveryParams])

  useEffect(() => {
    if (cooldownSecsLeft <= 0) return
    const t = setTimeout(() => setCooldownSecsLeft((s) => Math.max(0, s - 1)), 1000)
    return () => clearTimeout(t)
  }, [cooldownSecsLeft])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (
        e.key === '/' &&
        !(e.target instanceof HTMLInputElement) &&
        !(e.target instanceof HTMLTextAreaElement) &&
        !(e.target instanceof HTMLSelectElement)
      ) {
        e.preventDefault()
        searchInputRef.current?.focus()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  useEffect(() => {
    loadDashboard()
  }, [])

  // Poll /discovery/status every 5 s while a run is in flight.
  // When the backend reports it is done, reload the dashboard.
  useEffect(() => {
    if (!discovering) {
      if (discoveryPollRef.current !== null) {
        clearInterval(discoveryPollRef.current)
        discoveryPollRef.current = null
      }
      return
    }

    const poll = async () => {
      try {
        const status = await fetchDiscoveryStatus()
        setDiscoveryStatus(status)
        if (!status.in_flight) {
          // Run finished on the backend side — reload dashboard
          setLoading(true)
          void loadDashboard()
        }
      } catch {
        // Swallow poll errors silently; the main triggerDiscovery error path handles failures
      }
    }

    void poll()
    discoveryPollRef.current = setInterval(() => void poll(), 5000)
    return () => {
      if (discoveryPollRef.current !== null) {
        clearInterval(discoveryPollRef.current)
        discoveryPollRef.current = null
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [discovering])

  const patchLocal = (id: number, patch: Partial<EditableRow>) => {
    setApplications((prev: EditableRow[]) =>
      prev.map((row: EditableRow) => (row.id === id ? { ...row, ...patch } : row))
    )
  }

  const [sortKey, setSortKey] = useState<'company' | 'fit_score' | 'status' | 'follow_up_date' | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  const handleSortClick = (key: 'company' | 'fit_score' | 'status' | 'follow_up_date') => {
    if (sortKey === key) {
      setSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  const availableSources = useMemo(() => {
    const sources = new Set(applications.map((row) => row.source).filter(Boolean))
    return Array.from(sources).sort()
  }, [applications])

  const filteredApplications = useMemo(() => {
    let filtered = filterApplications(applications, profileFilter, listingFilter)
    if (sourceFilter) {
      const src = sourceFilter.toLowerCase()
      filtered = filtered.filter((row) => (row.source || '').toLowerCase() === src)
    }
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase()
      filtered = filtered.filter(
        (row) =>
          row.company.toLowerCase().includes(q) ||
          row.role.toLowerCase().includes(q) ||
          (row.notes || '').toLowerCase().includes(q)
      )
    }
    if (!sortKey) return filtered
    return [...filtered].sort((a, b) => {
      let av: string | number = ''
      let bv: string | number = ''
      if (sortKey === 'fit_score') {
        av = a.fit_score ?? 0
        bv = b.fit_score ?? 0
      } else {
        av = (a[sortKey] || '').toLowerCase()
        bv = (b[sortKey] || '').toLowerCase()
      }
      if (av < bv) return sortDir === 'asc' ? -1 : 1
      if (av > bv) return sortDir === 'asc' ? 1 : -1
      return 0
    })
  }, [applications, listingFilter, profileFilter, searchQuery, sortDir, sortKey, sourceFilter])

  const activeProcessRow = useMemo(
    () => applications.find((row) => row.id === activeProcessId) ?? null,
    [applications, activeProcessId]
  )

  const activeFileExt = useMemo(() => {
    const lowered = activeFilePath.trim().toLowerCase()
    if (lowered.endsWith('.md')) return 'md'
    if (lowered.endsWith('.tex')) return 'tex'
    return ''
  }, [activeFilePath])

  const previewHtml = useMemo(() => {
    if (activeFileExt === 'md') return renderMarkdownPreview(fileDraft)
    if (activeFileExt === 'tex') return renderTexPreview(fileDraft)
    return ''
  }, [activeFileExt, fileDraft])

  const llmDryRunDiagnostics = useMemo<LlmDryRunDiagnostics | null>(() => {
    const output = discoveryResult?.stdout || ''
    if (!output.trim()) return null

    const parseLineValue = (key: string): string | null => {
      const line = output
        .split('\n')
        .map((part) => part.trim())
        .find((part) => part.startsWith(`- ${key}=`))
      if (!line) return null
      return line.slice(`- ${key}=`.length).trim()
    }

    const dryRunRaw = parseLineValue('llm_dry_run')
    if (!dryRunRaw) return null

    const toNumber = (value: string | null): number | null => {
      if (!value) return null
      const parsed = parseInt(value, 10)
      return Number.isNaN(parsed) ? null : parsed
    }

    const isDryRun = dryRunRaw.toLowerCase() === 'true'
    return {
      dryRun: isDryRun,
      plannedCalls: toNumber(parseLineValue('llm_planned_calls')),
      attempted: toNumber(parseLineValue('llm_attempted')),
      adjusted: toNumber(parseLineValue('llm_adjusted')),
      usedInputChars: toNumber(parseLineValue('llm_used_input_chars')),
      warningsCount: toNumber(parseLineValue('llm_warnings')),
    }
  }, [discoveryResult])

  const saveRow = async (row: EditableRow) => {
    patchLocal(row.id, { saving: true })
    try {
      const updated = await updateApplication(row.id, {
        selected: row.selected,
        date_applied: row.date_applied,
        status: row.status,
        next_step: row.next_step,
        follow_up_date: row.follow_up_date,
        resume_ref: row.resume_ref,
        cover_letter_ref: row.cover_letter_ref,
        notes: row.notes,
      })
      patchLocal(row.id, { ...updated, saving: false })
    } catch (e) {
      patchLocal(row.id, { saving: false })
      setError(e instanceof Error ? e.message : 'Failed to save application')
    }
  }

  const deleteRow = async (row: EditableRow) => {
    setPendingDeleteId(null)
    try {
      await deleteApplication(row.id)
      setApplications((prev) => prev.filter((r) => r.id !== row.id))
      if (activeProcessId === row.id) setActiveProcessId(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to delete application')
    }
  }


  const isStandardNextStep = (value: string | undefined) => !!value && NEXT_STEP_OPTIONS.includes(value)

  const nextStepSelectValue = (row: EditableRow) => {
    const value = (row.next_step || '').trim()
    if (!value) return ''
    return isStandardNextStep(value) ? value : '__custom__'
  }

  const handleNextStepSelect = (row: EditableRow, selected: string) => {
    if (selected === '__custom__') {
      const current = (row.next_step || '').trim()
      const customValue = customNextStepById[row.id] ?? (isStandardNextStep(current) ? '' : current)
      setCustomNextStepById((prev) => ({ ...prev, [row.id]: customValue }))
      patchLocal(row.id, { next_step: customValue })
      return
    }

    patchLocal(row.id, { next_step: selected })
  }

  const scoreBandLabel = (score: number) => {
    if (score >= SCORE_STRONG_MIN) return 'Strong'
    if (score >= SCORE_MEDIUM_MIN) return 'Medium'
    return 'Stretch'
  }

  const parseScoreBreakdown = (row: EditableRow): ScoreBreakdown => {
    const typed = row.score_breakdown
    if (typed && typeof typed === 'object') {
      return {
        score: typeof typed.score === 'number' ? typed.score : row.fit_score,
        fit: (typed.fit || row.fit || '').trim(),
        matchedKeywords: Array.isArray(typed.matched_keywords) ? typed.matched_keywords.filter(Boolean) : [],
        missingSkills: Array.isArray(typed.missing_skills) ? typed.missing_skills.filter(Boolean) : [],
        fitNotes: (typed.fit_notes || row.notes || '').trim(),
      }
    }

    let parsed: {
      score?: number
      fit?: string
      matched_keywords?: string[]
      missing_skills?: string[]
      fit_notes?: string
    } = {}

    try {
      parsed = row.change_note ? (JSON.parse(row.change_note) as typeof parsed) : {}
    } catch {
      parsed = {}
    }

    return {
      score: typeof parsed.score === 'number' ? parsed.score : row.fit_score,
      fit: (parsed.fit || row.fit || '').trim(),
      matchedKeywords: Array.isArray(parsed.matched_keywords) ? parsed.matched_keywords.filter(Boolean) : [],
      missingSkills: Array.isArray(parsed.missing_skills) ? parsed.missing_skills.filter(Boolean) : [],
      fitNotes: (parsed.fit_notes || row.notes || '').trim(),
    }
  }

  const startProcessForRow = async (row: EditableRow) => {
    setActiveProcessId(row.id)
    const rowDocs = getRowDocLinks(row, generatedDocsById)
    const preferredPath =
      lastProcessFileById[row.id] || rowDocs.vacancyPath || rowDocs.notesPath || rowDocs.coverLetterPath || rowDocs.cvPath

    if (preferredPath) {
      await openWorkspaceFile(preferredPath)
    }

    requestAnimationFrame(() => {
      editorSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }

  const openProcessFile = async (rowId: number, path: string) => {
    setLastProcessFileById((prev) => ({ ...prev, [rowId]: path }))
    await openWorkspaceFile(path)
  }

  const toggleApplied = async (row: EditableRow, checked: boolean) => {
    const previous = {
      selected: row.selected,
      date_applied: row.date_applied,
      status: row.status,
    }

    const nextStatus = checked
      ? 'Applied'
      : (row.status || '').toLowerCase() === 'applied'
      ? 'To review'
      : row.status || 'To review'

    const patch = {
      selected: checked ? 'yes' : 'no',
      date_applied: checked ? new Date().toLocaleDateString('en-CA') : '',
      status: nextStatus,
    }

    patchLocal(row.id, { ...patch, saving: true })
    try {
      const updated = await updateApplication(row.id, patch)
      patchLocal(row.id, { ...updated, saving: false })
    } catch (e) {
      patchLocal(row.id, { ...previous, saving: false })
      setError(e instanceof Error ? e.message : 'Failed to update application status')
    }
  }

  const generateDocsForRow = async (row: EditableRow, overwrite = false) => {
    if (overwrite) {
      const confirmed = window.confirm(
        'Regenerate and overwrite existing vacancy files for this role? Existing file content will be replaced.'
      )
      if (!confirmed) return
    }

    patchLocal(row.id, { generating: true })
    setError(null)
    try {
      const generated = await generateDocuments(row.id, {
        overwrite,
        author_name: undefined,
      })
      setGeneratedDocsById((prev) => ({ ...prev, [row.id]: generated }))
      patchLocal(row.id, {
        resume_ref: generated.cv_path,
        cover_letter_ref: generated.cover_letter_path,
        generating: false,
      })
      await openWorkspaceFile(generated.cover_letter_path)
    } catch (e) {
      patchLocal(row.id, { generating: false })
      if (e instanceof ApiError && e.status === 409) {
        setError(`${e.message}. Use Regenerate to overwrite files when needed.`)
      } else {
        setError(e instanceof Error ? e.message : 'Failed to generate tailored files')
      }
    }
  }

  const openWorkspaceFile = async (path: string) => {
    if (!path.trim()) return
    if (fileDirty && activeFilePath && activeFilePath !== path) {
      const confirmed = window.confirm('Unsaved editor changes detected. Discard changes and open another file?')
      if (!confirmed) return
    }

    setFileLoading(true)
    setError(null)
    try {
      const loaded = await readWorkspaceFile(path)
      setActiveFilePath(loaded.path)
      setFileContent(loaded.content)
      setFileDraft(loaded.content)
      setFileDirty(false)
    } catch (e) {
      const fallback = 'Failed to open file'
      if (e instanceof Error) {
        if (e.message.includes('404')) {
          setError(`File not found: ${path}. It may have been moved or deleted. Regenerate docs or update the file path.`)
        } else {
          setError(e.message || fallback)
        }
      } else {
        setError(fallback)
      }
    } finally {
      setFileLoading(false)
    }
  }

  const saveFile = async () => {
    if (!activeFilePath) return
    setFileSaving(true)
    setError(null)
    try {
      const saved = await writeWorkspaceFile(activeFilePath, fileDraft)
      setFileContent(saved.content)
      setFileDraft(saved.content)
      setFileDirty(false)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save file')
    } finally {
      setFileSaving(false)
    }
  }

  const triggerDiscovery = async () => {
    setDiscovering(true)
    setDiscoveryStatus(null)
    setError(null)
    try {
      const salaryMinUsd = discoveryParams.salary_min_usd.trim()
      const timezoneTokens = discoveryParams.timezones
        .split(',')
        .map((part) => part.trim())
        .filter(Boolean)
      const seniority = discoveryParams.seniority.trim() as '' | 'junior' | 'mid' | 'senior'
      const outputDir = discoveryParams.output_dir.trim()
      const llmModel = discoveryParams.llm_model.trim()
      const llmApiBaseUrl = discoveryParams.llm_api_base_url.trim()
      const selectedSources = DISCOVERY_SOURCES.map((source) => source.key).filter(
        (sourceKey) => discoverySourceSelection[sourceKey]
      )
      const result = await runDiscovery({
        limit: discoveryParams.limit,
        min_score: discoveryParams.min_score,
        max_age_days: discoveryParams.max_age_days,
        include_stretch: discoveryParams.include_stretch,
        profile: discoveryProfile,
        salary_min_usd: salaryMinUsd ? parseInt(salaryMinUsd, 10) || undefined : undefined,
        timezones: timezoneTokens.length > 0 ? timezoneTokens : undefined,
        seniority: seniority || undefined,
        use_outcome_priors: discoveryParams.use_outcome_priors,
        prior_lookback_days: discoveryParams.prior_lookback_days,
        source_prior_weight: discoveryParams.source_prior_weight,
        role_prior_weight: discoveryParams.role_prior_weight,
        use_llm_reranker: discoveryParams.use_llm_reranker,
        llm_top_n: discoveryParams.llm_top_n,
        llm_weight: discoveryParams.llm_weight,
        llm_model: llmModel || undefined,
        llm_api_base_url: llmApiBaseUrl || undefined,
        llm_dry_run: discoveryParams.llm_dry_run,
        llm_max_calls: discoveryParams.llm_max_calls,
        llm_max_input_chars: discoveryParams.llm_max_input_chars,
        llm_max_retries: discoveryParams.llm_max_retries,
        llm_retry_backoff_seconds: discoveryParams.llm_retry_backoff_seconds,
        llm_timeout_seconds: discoveryParams.llm_timeout_seconds,
        output_dir: outputDir || undefined,
        cv_path: discoveryCvPath.trim() || undefined,
        api_base_url: discoveryApiBaseUrl.trim() || undefined,
        verbose: discoveryVerbose,
        sources: selectedSources,
      })
      setDiscoveryResult(result)
      setLoading(true)
      await loadDashboard()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to run discovery')
    } finally {
      setDiscovering(false)
      setCooldownSecsLeft(30)
    }
  }

  return (
    <div className="container">
      <header>
        <div>
          <h1>Job Application Insights</h1>
          <p className="subtitle">FastAPI · SQLAlchemy · React · TypeScript</p>
        </div>
        <nav className="view-tabs" aria-label="Main views">
          <button
            className={`tab-btn${activePage === 'pipeline' ? ' active' : ''}`}
            onClick={() => setActivePage('pipeline')}
          >
            Tracker
          </button>
          <button
            className={`tab-btn${activePage === 'analytics' ? ' active' : ''}`}
            onClick={() => setActivePage('analytics')}
          >
            Analytics
          </button>
          <button
            className={`tab-btn${activePage === 'discovery' ? ' active' : ''}`}
            onClick={() => setActivePage('discovery')}
          >
            Discovery
          </button>
        </nav>
      </header>

      {error && <div className="error-banner">{error}</div>}
      {successMessage && <div className="success-banner">{successMessage}</div>}

      {loading ? (
        <p className="empty-state">Loading…</p>
      ) : (
        <>
          {activePage === 'analytics' && (
            <AnalyticsPage applications={applications} />
          )}

          {activePage === 'discovery' && (
            <>
              <section className="card">
                <h2>Discovery</h2>
                <p className="subtitle small">Run job discovery or add jobs manually.</p>
                <div className="toolbar">
                  <label className="toolbar-label" htmlFor="discovery-profile">
                    Profile
                  </label>
                  <select
                    id="discovery-profile"
                    className="text-input select-input compact-input"
                    value={discoveryProfile}
                    onChange={(e) => setDiscoveryProfile(e.target.value as DiscoveryProfile)}
                  >
                    <option value="de">DE</option>
                    <option value="swe">SWE</option>
                    <option value="sre">SRE</option>
                    <option value="other">Other</option>
                  </select>
                  <label className="toolbar-label" htmlFor="discovery-limit">
                    Limit
                  </label>
                  <input
                    id="discovery-limit"
                    className="text-input compact-input"
                    type="number"
                    value={discoveryParams.limit}
                    onChange={(e) => setDiscoveryParams({ ...discoveryParams, limit: parseInt(e.target.value) || 40 })}
                    min="1"
                  />
                  <label className="toolbar-label" htmlFor="discovery-min-score">
                    Min score
                  </label>
                  <input
                    id="discovery-min-score"
                    className="text-input compact-input"
                    type="number"
                    value={discoveryParams.min_score}
                    onChange={(e) => setDiscoveryParams({ ...discoveryParams, min_score: parseInt(e.target.value) || 7 })}
                    min="1"
                  />
                </div>
                <p className="subtitle small" style={{ marginTop: '8px', marginBottom: '8px' }}>
                  Score ranges: Strong {`>= ${SCORE_STRONG_MIN}`}, Medium {`${SCORE_MEDIUM_MIN}-${SCORE_STRONG_MIN - 1}`}, Stretch {`<= ${SCORE_MEDIUM_MIN - 1}`}
                </p>
                <div className="toolbar" style={{ marginTop: '8px' }}>
                  <label className="toolbar-label" htmlFor="discovery-cv-path">
                    CV path
                  </label>
                  <input
                    id="discovery-cv-path"
                    className="text-input"
                    type="text"
                    placeholder="applications/resumes/CV.tex"
                    value={discoveryCvPath}
                    onChange={(e) => setDiscoveryCvPath(e.target.value)}
                    style={{ minWidth: '260px', flex: 1 }}
                    title="CV path used for discovery scoring. Accepts workspace-relative or absolute paths."
                  />
                </div>
                <p className="subtitle small" style={{ marginTop: '8px', marginBottom: '8px' }}>
                  CV path is a per-run input. If empty, backend uses DISCOVERY_CV_PATH fallback from .env.
                </p>
                <details className="details-panel" style={{ marginTop: '8px' }}>
                  <summary className="muted-mini">Advanced discovery params</summary>
                  <div className="toolbar" style={{ marginTop: '8px' }}>
                    <label className="toolbar-label" htmlFor="discovery-api-base-url">
                      API base URL
                    </label>
                    <input
                      id="discovery-api-base-url"
                      className="text-input"
                      type="text"
                      placeholder="http://127.0.0.1:8000"
                      value={discoveryApiBaseUrl}
                      onChange={(e) => setDiscoveryApiBaseUrl(e.target.value)}
                      style={{ minWidth: '240px', flex: 1 }}
                      title="Optional override passed to discovery CLI --api-base-url."
                    />
                    <label className="toolbar-label" title="Enable verbose source diagnostics in discovery output.">
                      <input
                        type="checkbox"
                        checked={discoveryVerbose}
                        onChange={(e) => setDiscoveryVerbose(e.target.checked)}
                        style={{ marginRight: '4px' }}
                      />
                      Verbose logs
                    </label>
                  </div>
                  <div className="toolbar" style={{ marginTop: '8px' }}>
                    <label className="toolbar-label" htmlFor="discovery-salary-min-usd">
                      Min salary (USD)
                    </label>
                    <input
                      id="discovery-salary-min-usd"
                      className="text-input compact-input"
                      type="number"
                      min="0"
                      placeholder="optional"
                      value={discoveryParams.salary_min_usd}
                      onChange={(e) => setDiscoveryParams({ ...discoveryParams, salary_min_usd: e.target.value })}
                    />
                    <label className="toolbar-label" htmlFor="discovery-seniority">
                      Seniority
                    </label>
                    <select
                      id="discovery-seniority"
                      className="text-input select-input compact-input"
                      value={discoveryParams.seniority}
                      onChange={(e) => setDiscoveryParams({ ...discoveryParams, seniority: e.target.value })}
                    >
                      <option value="">Any</option>
                      <option value="junior">Junior+</option>
                      <option value="mid">Mid+</option>
                      <option value="senior">Senior</option>
                    </select>
                  </div>
                  <div className="toolbar" style={{ marginTop: '8px' }}>
                    <label className="toolbar-label" htmlFor="discovery-timezones">
                      Timezones
                    </label>
                    <input
                      id="discovery-timezones"
                      className="text-input"
                      type="text"
                      placeholder="UTC,CET,EMEA"
                      value={discoveryParams.timezones}
                      onChange={(e) => setDiscoveryParams({ ...discoveryParams, timezones: e.target.value })}
                      style={{ minWidth: '200px', flex: 1 }}
                    />
                    <label className="toolbar-label" htmlFor="discovery-output-dir">
                      Output dir
                    </label>
                    <input
                      id="discovery-output-dir"
                      className="text-input"
                      type="text"
                      placeholder="applications/tracker"
                      value={discoveryParams.output_dir}
                      onChange={(e) => setDiscoveryParams({ ...discoveryParams, output_dir: e.target.value })}
                      style={{ minWidth: '200px', flex: 1 }}
                    />
                  </div>
                  <div className="toolbar" style={{ marginTop: '8px' }}>
                    <label className="toolbar-label" title="Re-rank by historical outcome of source and role family.">
                      <input
                        type="checkbox"
                        checked={discoveryParams.use_outcome_priors}
                        onChange={(e) =>
                          setDiscoveryParams({
                            ...discoveryParams,
                            use_outcome_priors: e.target.checked,
                          })
                        }
                        style={{ marginRight: '4px' }}
                      />
                      Use outcome priors
                    </label>
                    <label className="toolbar-label" htmlFor="discovery-prior-lookback-days">
                      Prior lookback
                    </label>
                    <input
                      id="discovery-prior-lookback-days"
                      className="text-input compact-input"
                      type="number"
                      min="1"
                      value={discoveryParams.prior_lookback_days}
                      onChange={(e) =>
                        setDiscoveryParams({
                          ...discoveryParams,
                          prior_lookback_days: parseInt(e.target.value, 10) || 365,
                        })
                      }
                      disabled={!discoveryParams.use_outcome_priors}
                    />
                    <label className="toolbar-label" htmlFor="discovery-source-prior-weight">
                      Source weight
                    </label>
                    <input
                      id="discovery-source-prior-weight"
                      className="text-input compact-input"
                      type="number"
                      step="0.1"
                      value={discoveryParams.source_prior_weight}
                      onChange={(e) =>
                        setDiscoveryParams({
                          ...discoveryParams,
                          source_prior_weight: parseFloat(e.target.value) || 1,
                        })
                      }
                      disabled={!discoveryParams.use_outcome_priors}
                    />
                    <label className="toolbar-label" htmlFor="discovery-role-prior-weight">
                      Role weight
                    </label>
                    <input
                      id="discovery-role-prior-weight"
                      className="text-input compact-input"
                      type="number"
                      step="0.1"
                      value={discoveryParams.role_prior_weight}
                      onChange={(e) =>
                        setDiscoveryParams({
                          ...discoveryParams,
                          role_prior_weight: parseFloat(e.target.value) || 1,
                        })
                      }
                      disabled={!discoveryParams.use_outcome_priors}
                    />
                  </div>
                  <div className="toolbar" style={{ marginTop: '8px' }}>
                    <label className="toolbar-label" title="Use LLM to conservatively adjust score for top candidates.">
                      <input
                        type="checkbox"
                        checked={discoveryParams.use_llm_reranker}
                        onChange={(e) =>
                          setDiscoveryParams({
                            ...discoveryParams,
                            use_llm_reranker: e.target.checked,
                          })
                        }
                        style={{ marginRight: '4px' }}
                      />
                      Use LLM reranker
                    </label>
                    <label className="toolbar-label" htmlFor="discovery-llm-top-n">
                      LLM top N
                    </label>
                    <input
                      id="discovery-llm-top-n"
                      className="text-input compact-input"
                      type="number"
                      min="1"
                      value={discoveryParams.llm_top_n}
                      onChange={(e) =>
                        setDiscoveryParams({
                          ...discoveryParams,
                          llm_top_n: parseInt(e.target.value, 10) || 20,
                        })
                      }
                      disabled={!discoveryParams.use_llm_reranker}
                    />
                    <label className="toolbar-label" htmlFor="discovery-llm-weight">
                      LLM weight
                    </label>
                    <input
                      id="discovery-llm-weight"
                      className="text-input compact-input"
                      type="number"
                      step="0.1"
                      min="0"
                      value={discoveryParams.llm_weight}
                      onChange={(e) =>
                        setDiscoveryParams({
                          ...discoveryParams,
                          llm_weight: parseFloat(e.target.value) || 1,
                        })
                      }
                      disabled={!discoveryParams.use_llm_reranker}
                    />
                    <label className="toolbar-label" title="Dry-run mode: show planning diagnostics and skip external API calls.">
                      <input
                        type="checkbox"
                        checked={discoveryParams.llm_dry_run}
                        onChange={(e) =>
                          setDiscoveryParams({
                            ...discoveryParams,
                            llm_dry_run: e.target.checked,
                          })
                        }
                        style={{ marginRight: '4px' }}
                        disabled={!discoveryParams.use_llm_reranker}
                      />
                      Dry-run explain
                    </label>
                  </div>
                  <div className="toolbar" style={{ marginTop: '8px' }}>
                    <label className="toolbar-label" htmlFor="discovery-llm-model">
                      LLM model
                    </label>
                    <input
                      id="discovery-llm-model"
                      className="text-input"
                      type="text"
                      placeholder="gpt-4o-mini"
                      value={discoveryParams.llm_model}
                      onChange={(e) => setDiscoveryParams({ ...discoveryParams, llm_model: e.target.value })}
                      style={{ minWidth: '180px', flex: 1 }}
                      disabled={!discoveryParams.use_llm_reranker}
                    />
                    <label className="toolbar-label" htmlFor="discovery-llm-api-base-url">
                      LLM API base URL
                    </label>
                    <input
                      id="discovery-llm-api-base-url"
                      className="text-input"
                      type="text"
                      placeholder="https://api.openai.com/v1"
                      value={discoveryParams.llm_api_base_url}
                      onChange={(e) => setDiscoveryParams({ ...discoveryParams, llm_api_base_url: e.target.value })}
                      style={{ minWidth: '220px', flex: 1 }}
                      disabled={!discoveryParams.use_llm_reranker}
                    />
                  </div>
                  <div className="toolbar" style={{ marginTop: '8px' }}>
                    <label className="toolbar-label" htmlFor="discovery-llm-max-calls">
                      Max calls
                    </label>
                    <input
                      id="discovery-llm-max-calls"
                      className="text-input compact-input"
                      type="number"
                      min="1"
                      value={discoveryParams.llm_max_calls}
                      onChange={(e) =>
                        setDiscoveryParams({
                          ...discoveryParams,
                          llm_max_calls: parseInt(e.target.value, 10) || 20,
                        })
                      }
                      disabled={!discoveryParams.use_llm_reranker}
                    />
                    <label className="toolbar-label" htmlFor="discovery-llm-max-input-chars">
                      Max input chars
                    </label>
                    <input
                      id="discovery-llm-max-input-chars"
                      className="text-input compact-input"
                      type="number"
                      min="1000"
                      step="1000"
                      value={discoveryParams.llm_max_input_chars}
                      onChange={(e) =>
                        setDiscoveryParams({
                          ...discoveryParams,
                          llm_max_input_chars: parseInt(e.target.value, 10) || 50000,
                        })
                      }
                      disabled={!discoveryParams.use_llm_reranker}
                    />
                  </div>
                  <div className="toolbar" style={{ marginTop: '8px' }}>
                    <label className="toolbar-label" htmlFor="discovery-llm-max-retries">
                      Max retries
                    </label>
                    <input
                      id="discovery-llm-max-retries"
                      className="text-input compact-input"
                      type="number"
                      min="0"
                      value={discoveryParams.llm_max_retries}
                      onChange={(e) =>
                        setDiscoveryParams({
                          ...discoveryParams,
                          llm_max_retries: parseInt(e.target.value, 10) || 0,
                        })
                      }
                      disabled={!discoveryParams.use_llm_reranker}
                    />
                    <label className="toolbar-label" htmlFor="discovery-llm-retry-backoff-seconds">
                      Retry backoff (s)
                    </label>
                    <input
                      id="discovery-llm-retry-backoff-seconds"
                      className="text-input compact-input"
                      type="number"
                      step="0.1"
                      min="0"
                      value={discoveryParams.llm_retry_backoff_seconds}
                      onChange={(e) =>
                        setDiscoveryParams({
                          ...discoveryParams,
                          llm_retry_backoff_seconds: parseFloat(e.target.value) || 0,
                        })
                      }
                      disabled={!discoveryParams.use_llm_reranker}
                    />
                    <label className="toolbar-label" htmlFor="discovery-llm-timeout-seconds">
                      Timeout (s)
                    </label>
                    <input
                      id="discovery-llm-timeout-seconds"
                      className="text-input compact-input"
                      type="number"
                      min="5"
                      value={discoveryParams.llm_timeout_seconds}
                      onChange={(e) =>
                        setDiscoveryParams({
                          ...discoveryParams,
                          llm_timeout_seconds: parseInt(e.target.value, 10) || 20,
                        })
                      }
                      disabled={!discoveryParams.use_llm_reranker}
                    />
                  </div>
                </details>
                <div className="toolbar" style={{ marginTop: '8px' }}>
                  <label className="toolbar-label" htmlFor="discovery-max-age">
                    Max age (days)
                  </label>
                  <input
                    id="discovery-max-age"
                    className="text-input compact-input"
                    type="number"
                    value={discoveryParams.max_age_days}
                    onChange={(e) => setDiscoveryParams({ ...discoveryParams, max_age_days: parseInt(e.target.value) || 45 })}
                    min="1"
                  />
                  <label
                    className="toolbar-label"
                    title="Include lower-fit adjacent roles (Stretch) in shortlist results"
                  >
                    <input
                      type="checkbox"
                      checked={discoveryParams.include_stretch}
                      onChange={(e) => setDiscoveryParams({ ...discoveryParams, include_stretch: e.target.checked })}
                      style={{ marginRight: '4px' }}
                    />
                    Include stretch
                  </label>
                  <button className="save-btn" disabled={discovering || cooldownSecsLeft > 0} onClick={() => void triggerDiscovery()}>
                    {discovering ? 'Running...' : cooldownSecsLeft > 0 ? `Wait ${cooldownSecsLeft}s` : 'Run discovery'}
                  </button>
                </div>
                {discovering && discoveryStatus?.in_flight && (
                  <p className="discovery-status-line muted-mini">
                    {discoveryStatus.elapsed_seconds !== null
                      ? `Running… ${discoveryStatus.elapsed_seconds}s elapsed`
                      : 'Starting…'}
                  </p>
                )}
                <div className="details-panel" style={{ marginTop: '10px' }}>
                  <strong className="muted-mini">Websites</strong>
                  <div className="process-actions">
                    {DISCOVERY_SOURCES.map((source) => (
                      <label key={source.key} className="toolbar-label" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                        <input
                          type="checkbox"
                          checked={!!discoverySourceSelection[source.key]}
                          onChange={(e) =>
                            setDiscoverySourceSelection((prev) => ({
                              ...prev,
                              [source.key]: e.target.checked,
                            }))
                          }
                        />
                        {source.label}
                      </label>
                    ))}
                  </div>
                </div>
                {llmDryRunDiagnostics && (
                  <div className="dry-run-card">
                    <strong>LLM {llmDryRunDiagnostics.dryRun ? 'Dry-run' : 'Rerank'} Report</strong>
                    <div className="dry-run-grid">
                      <span>Dry-run mode</span>
                      <span>{llmDryRunDiagnostics.dryRun ? 'Yes' : 'No'}</span>
                      <span>Planned calls</span>
                      <span>{llmDryRunDiagnostics.plannedCalls ?? 'n/a'}</span>
                      <span>Attempted calls</span>
                      <span>{llmDryRunDiagnostics.attempted ?? 'n/a'}</span>
                      <span>Adjusted rows</span>
                      <span>{llmDryRunDiagnostics.adjusted ?? 'n/a'}</span>
                      <span>Used input chars</span>
                      <span>{llmDryRunDiagnostics.usedInputChars ?? 'n/a'}</span>
                      <span>Warnings</span>
                      <span>{llmDryRunDiagnostics.warningsCount ?? 'n/a'}</span>
                    </div>
                  </div>
                )}
                {discoveryResult && (
                  <div className="result-banner">
                    <strong>Discovery exit code:</strong> {discoveryResult.exit_code}
                    {discoveryResult.stdout && <pre>{discoveryResult.stdout}</pre>}
                    {discoveryResult.stderr && <pre>{discoveryResult.stderr}</pre>}
                  </div>
                )}
              </section>
              <section className="card">
                <h2>Add Job Manually</h2>
                <p className="subtitle small">Create a new job entry without discovery.</p>
                <div className="toolbar">
                  <input
                    className="text-input"
                    type="text"
                    placeholder="Company"
                    value={manualJobForm.company}
                    onChange={(e) => setManualJobForm({ ...manualJobForm, company: e.target.value })}
                  />
                  <input
                    className="text-input"
                    type="text"
                    placeholder="Role"
                    value={manualJobForm.role}
                    onChange={(e) => setManualJobForm({ ...manualJobForm, role: e.target.value })}
                  />
                  <input
                    className="text-input"
                    type="url"
                    placeholder="Job link (optional)"
                    value={manualJobForm.link}
                    onChange={(e) => setManualJobForm({ ...manualJobForm, link: e.target.value })}
                  />
                </div>
                <div style={{ marginTop: '8px' }}>
                  <label className="muted-mini" style={{ display: 'block', marginBottom: '4px' }}>Job description or notes (optional)</label>
                  <textarea
                    className="notes-input"
                    value={manualJobForm.description}
                    onChange={(e) => setManualJobForm({ ...manualJobForm, description: e.target.value })}
                    placeholder="Paste job description, key requirements, or any notes..."
                    style={{ minHeight: '80px' }}
                  />
                  <button
                    className="save-btn"
                    onClick={async () => {
                      if (manualJobForm.company.trim() && manualJobForm.role.trim()) {
                        try {
                          setError(null)
                          setSuccessMessage(null)
                          await upsertApplication({
                            company: manualJobForm.company.trim(),
                            role: manualJobForm.role.trim(),
                            link: manualJobForm.link.trim() || undefined,
                            notes: manualJobForm.description,
                            status: 'To review',
                            match_profile: discoveryProfile,
                            source: 'manual',
                          })
                          setManualJobForm({ company: '', role: '', link: '', description: '' })
                          setLoading(true)
                          loadDashboard()
                          setSuccessMessage('Job added successfully')
                        } catch (e) {
                          setError(e instanceof Error ? e.message : 'Failed to add job')
                        }
                      } else {
                        setError('Company and role are required')
                      }
                    }}
                    style={{ marginTop: '8px' }}
                  >
                    Add job
                  </button>
                </div>
              </section>
            </>
          )}

          {activePage === 'pipeline' && (
            <>
              <section className="card applications-card">
                <h2>Application Tracker</h2>
                <p className="subtitle small">Track status, keep notes, and manage generated docs in one place.</p>

                <div className="filters-row">
                  <label htmlFor="profile-filter">Match profile</label>
                  <select
                    id="profile-filter"
                    className="text-input select-input compact-input"
                    value={profileFilter}
                    onChange={(e) => setProfileFilter(e.target.value as 'all' | DiscoveryProfile)}
                  >
                    <option value="all">All</option>
                    <option value="de">DE</option>
                    <option value="swe">SWE</option>
                    <option value="sre">SRE</option>
                    <option value="other">Other</option>
                  </select>

                  <label htmlFor="listing-filter">Listing</label>
                  <select
                    id="listing-filter"
                    className="text-input select-input compact-input"
                    value={listingFilter}
                    onChange={(e) => setListingFilter(e.target.value as ListingFilter)}
                  >
                    <option value="all">All</option>
                    <option value="new">New</option>
                    <option value="updated">Updated</option>
                  </select>

                  {availableSources.length > 0 && (
                    <>
                      <label htmlFor="source-filter">Source</label>
                      <select
                        id="source-filter"
                        className="text-input select-input compact-input"
                        value={sourceFilter}
                        onChange={(e) => setSourceFilter(e.target.value)}
                      >
                        <option value="">All</option>
                        {availableSources.map((src) => (
                          <option key={src} value={src}>{src}</option>
                        ))}
                      </select>
                    </>
                  )}

                  <div className="search-wrap">
                    <input
                      ref={searchInputRef}
                      id="tracker-search"
                      className="text-input"
                      type="text"
                      placeholder='Search company, role, notes… ("/" to focus)'
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                    />
                    {searchQuery && (
                      <button
                        className="search-clear-btn"
                        title="Clear search"
                        onClick={() => setSearchQuery('')}
                        aria-label="Clear search"
                      >
                        ×
                      </button>
                    )}
                  </div>
                </div>

                <div className="table-wrap">
                  <table className="apps-table">
                    <thead>
                      <tr>
                        <th>Applied</th>
                        <th
                          className="sortable-th"
                          onClick={() => handleSortClick('company')}
                          title="Sort by company / role"
                        >
                          Role {sortKey === 'company' ? (sortDir === 'asc' ? '▲' : '▼') : '↕'}
                        </th>
                        <th
                          className="sortable-th"
                          onClick={() => handleSortClick('status')}
                          title="Sort by status"
                        >
                          Stage {sortKey === 'status' ? (sortDir === 'asc' ? '▲' : '▼') : '↕'}
                        </th>
                        <th
                          className="sortable-th"
                          onClick={() => handleSortClick('follow_up_date')}
                          title="Sort by follow-up date"
                        >
                          Due {sortKey === 'follow_up_date' ? (sortDir === 'asc' ? '▲' : '▼') : '↕'}
                        </th>
                        <th>Process</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredApplications.map((row) => {
                        const rowDocs = getRowDocLinks(row, generatedDocsById)
                        const scoreBreakdown = parseScoreBreakdown(row)
                        return (
                          <tr key={row.id}>
                            <td>
                              <input
                                type="checkbox"
                                checked={row.selected.toLowerCase() === 'yes'}
                                disabled={!!row.saving}
                                onChange={(e) => {
                                  void toggleApplied(row, e.target.checked)
                                }}
                              />
                            </td>
                            <td>
                              <div className="role-cell">
                                <div className="role-title-row">
                                  <strong>{row.company}</strong>
                                  <span className="profile-pill">{normalizedProfile(row).toUpperCase()}</span>
                                </div>
                                <span>{row.role}</span>
                                <span className="score-pill" title="Discovery fit score and band">
                                  Score {row.fit_score} · {scoreBandLabel(row.fit_score)}
                                </span>
                                {isUpdatedListing(row) && <span className="status-pill">Updated</span>}
                                {!isUpdatedListing(row) && isNewListing(row) && <span className="status-pill">New</span>}
                                <details className="row-details">
                                  <summary className="toggle-summary">Score breakdown</summary>
                                  <div className="details-panel score-breakdown">
                                    <div><strong>Total:</strong> {scoreBreakdown.score ?? row.fit_score}</div>
                                    <div><strong>Band:</strong> {scoreBreakdown.fit || scoreBandLabel(row.fit_score)}</div>
                                    <div>
                                      <strong>Matched keywords:</strong> {scoreBreakdown.matchedKeywords.length > 0 ? scoreBreakdown.matchedKeywords.join(', ') : 'None listed'}
                                    </div>
                                    <div>
                                      <strong>Missing/adjacent:</strong> {scoreBreakdown.missingSkills.length > 0 ? scoreBreakdown.missingSkills.join(', ') : 'None listed'}
                                    </div>
                                    <div>
                                      <strong>Notes:</strong> {scoreBreakdown.fitNotes || 'No notes yet'}
                                    </div>
                                    <div className="muted-mini">
                                      Ranges: Strong {`>= ${SCORE_STRONG_MIN}`}, Medium {`${SCORE_MEDIUM_MIN}-${SCORE_STRONG_MIN - 1}`}, Stretch {`<= ${SCORE_MEDIUM_MIN - 1}`}
                                    </div>
                                  </div>
                                </details>
                              </div>
                            </td>
                            <td>
                              <div className="stage-stack">
                                <select
                                  className="text-input select-input"
                                  value={row.status || 'To review'}
                                  onChange={(e) => patchLocal(row.id, { status: e.target.value })}
                                >
                                  <option value="To review">To review</option>
                                  <option value="Applied">Applied</option>
                                  <option value="Interview">Interview</option>
                                  <option value="Offer">Offer</option>
                                  <option value="Rejected">Rejected</option>
                                  <option value="Saved">Saved</option>
                                </select>
                                <select
                                  className="text-input select-input next-step-input"
                                  value={nextStepSelectValue(row)}
                                  onChange={(e) => handleNextStepSelect(row, e.target.value)}
                                >
                                  <option value="">None</option>
                                  {NEXT_STEP_OPTIONS.map((option) => (
                                    <option key={option} value={option}>
                                      {option}
                                    </option>
                                  ))}
                                  <option value="__custom__">Custom</option>
                                </select>
                                {nextStepSelectValue(row) === '__custom__' && (
                                  <input
                                    className="text-input"
                                    value={customNextStepById[row.id] ?? row.next_step ?? ''}
                                    onChange={(e) => {
                                      const value = e.target.value
                                      setCustomNextStepById((prev) => ({ ...prev, [row.id]: value }))
                                      patchLocal(row.id, { next_step: value })
                                    }}
                                    placeholder="Type custom next step"
                                  />
                                )}
                              </div>
                            </td>
                            <td>
                              <input
                                className="text-input date-input"
                                type="date"
                                value={row.follow_up_date || ''}
                                onChange={(e) => patchLocal(row.id, { follow_up_date: e.target.value })}
                              />
                            </td>
                            <td>
                              <button
                                className="secondary-btn"
                                title="Open this role in the editor workflow"
                                onClick={() => {
                                  void startProcessForRow(row)
                                }}
                              >
                                Process
                              </button>
                              {pendingDeleteId === row.id ? (
                                <div className="delete-confirm">
                                  <span className="muted-mini">Delete?</span>
                                  <button className="delete-btn" onClick={() => void deleteRow(row)}>Yes</button>
                                  <button className="secondary-btn" style={{ fontSize: '0.82rem', padding: '5px 10px' }} onClick={() => setPendingDeleteId(null)}>No</button>
                                </div>
                              ) : (
                                <button
                                  className="delete-btn"
                                  title="Permanently delete this application"
                                  disabled={!!row.saving}
                                  onClick={() => setPendingDeleteId(row.id)}
                                  style={{ marginTop: '4px' }}
                                >
                                  Delete
                                </button>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>
              </section>

              <section className="card editor-card editor-sticky" ref={editorSectionRef}>
                <h2>File Editor</h2>
                <p className="subtitle small">Use Process on a row, generate/open files here, then edit and save.</p>
                {activeProcessRow && (
                  <div className="details-panel process-panel" style={{ marginBottom: '10px' }}>
                    <strong>{activeProcessRow.company} - {activeProcessRow.role}</strong>
                    <div className="docs-actions process-actions" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(110px, max-content))' }}>
                      {(() => {
                        const docs = getRowDocLinks(activeProcessRow, generatedDocsById)
                        const hasAnyDocs = !!(docs.vacancyPath || docs.notesPath || docs.coverLetterPath || docs.cvPath)
                        return (
                          <>
                            {!hasAnyDocs && (
                              <span className="muted-mini">
                                No generated files yet. Click Generate files to create Vacancy, Notes, Cover, and CV.
                              </span>
                            )}
                            {docs.vacancyPath && (
                              <button className="link-btn" title="Open generated vacancy snapshot (read-only)" onClick={() => void openProcessFile(activeProcessRow.id, docs.vacancyPath || '')}>
                                Vacancy
                              </button>
                            )}
                            {docs.notesPath && (
                              <button className="link-btn" title="Open editable notes file" onClick={() => void openProcessFile(activeProcessRow.id, docs.notesPath || '')}>
                                Notes
                              </button>
                            )}
                            {docs.coverLetterPath && (
                              <button className="link-btn" title="Open editable cover letter" onClick={() => void openProcessFile(activeProcessRow.id, docs.coverLetterPath || '')}>
                                Cover
                              </button>
                            )}
                            {docs.cvPath && (
                              <button className="link-btn" title="Open editable CV (LaTeX)" onClick={() => void openProcessFile(activeProcessRow.id, docs.cvPath || '')}>
                                CV
                              </button>
                            )}
                          </>
                        )
                      })()}
                      {!(() => {
                        const docs = getRowDocLinks(activeProcessRow, generatedDocsById)
                        return !!(activeProcessRow.resume_ref || activeProcessRow.cover_letter_ref || docs.vacancyPath || docs.notesPath)
                      })() ? (
                        <button
                          className="secondary-btn process-generate-btn"
                          title="Generate role files from templates"
                          disabled={!!activeProcessRow.generating}
                          onClick={() => {
                            void generateDocsForRow(activeProcessRow)
                          }}
                        >
                          {activeProcessRow.generating ? 'Generating...' : 'Generate files'}
                        </button>
                      ) : (
                        <button
                          className="secondary-btn process-generate-btn"
                          title="Regenerate and overwrite existing role files"
                          disabled={!!activeProcessRow.generating}
                          onClick={() => {
                            void generateDocsForRow(activeProcessRow, true)
                          }}
                        >
                          {activeProcessRow.generating ? 'Generating...' : 'Regenerate files'}
                        </button>
                      )}
                    </div>
                  </div>
                )}
                {activeFilePath ? (
                  <>
                    <div className="editor-head">
                      <span className="editor-path">{activeFilePath}</span>
                      <button
                        className="save-btn"
                        title={activeFilePath.endsWith('/vacancy.md') ? 'Vacancy file is read-only' : 'Save current file changes'}
                        disabled={fileLoading || fileSaving || !fileDirty || activeFilePath.endsWith('/vacancy.md')}
                        onClick={() => void saveFile()}
                      >
                        {fileSaving ? 'Saving...' : activeFilePath.endsWith('/vacancy.md') ? 'Read only' : 'Save file'}
                      </button>
                    </div>
                    {activeFilePath.endsWith('/vacancy.md') && (
                      <p className="muted-mini">Vacancy files are read-only. Edit Notes, Cover, or CV in the editor instead.</p>
                    )}
                    {fileLoading ? (
                      <p className="empty-state">Opening file...</p>
                    ) : activeFileExt === 'md' || activeFileExt === 'tex' ? (
                      <div className="editor-split">
                        <textarea
                          className="editor-area"
                          readOnly={activeFilePath.endsWith('/vacancy.md')}
                          value={fileDraft}
                          onChange={(e) => {
                            if (activeFilePath.endsWith('/vacancy.md')) return
                            const next = e.target.value
                            setFileDraft(next)
                            setFileDirty(next !== fileContent)
                          }}
                        />
                        <div className="preview-area" aria-label="Rendered preview">
                          <div
                            className="preview-content"
                            dangerouslySetInnerHTML={{ __html: previewHtml }}
                          />
                        </div>
                      </div>
                    ) : (
                      <textarea
                        className="editor-area"
                        readOnly={activeFilePath.endsWith('/vacancy.md')}
                        value={fileDraft}
                        onChange={(e) => {
                          if (activeFilePath.endsWith('/vacancy.md')) return
                          const next = e.target.value
                          setFileDraft(next)
                          setFileDirty(next !== fileContent)
                        }}
                      />
                    )}
                  </>
                ) : (
                  <p className="empty-state">No file opened yet. Click Process on a tracker row.</p>
                )}
              </section>
            </>
          )}
        </>
      )}

    </div>
  )
}
