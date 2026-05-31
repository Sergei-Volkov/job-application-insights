import { useEffect, useMemo, useRef, useState } from 'react'
import {
  fetchApplications,
  generateDocuments,
  readWorkspaceFile,
  updateApplication,
  deleteApplication,
  writeWorkspaceFile,
  ApiError,
  type GenerateDocumentsResult,
  type ApplicationItem,
} from './api'
import { NEXT_STEP_OPTIONS, SCORE_STRONG_MIN, SCORE_MEDIUM_MIN } from './appConstants'
import type { AppPage, DiscoveryProfile, EditableRow, GeneratedDocsMap, ListingFilter } from './appTypes'
import { getRowDocLinks } from './utils/docs'
import { filterApplications, isNewListing, isUpdatedListing, normalizedProfile } from './utils/listing'
import { renderMarkdownPreview, renderTexPreview } from './utils/preview'
import AnalyticsPage from './pages/AnalyticsPage'
import DiscoveryPage from './pages/DiscoveryPage'
import ConfirmModal from './components/ConfirmModal'
import WorkspaceEditor from './components/WorkspaceEditor'
import './App.css'

type ScoreBreakdown = {
  score: number | null
  fit: string
  matchedKeywords: string[]
  missingSkills: string[]
  fitNotes: string
}

export default function App() {
  const [applications, setApplications] = useState<EditableRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [profileFilter, setProfileFilter] = useState<'all' | DiscoveryProfile>('all')
  const [listingFilter, setListingFilter] = useState<ListingFilter>('all')
  const [generatedDocsById, setGeneratedDocsById] = useState<GeneratedDocsMap>({})
  const [activePage, setActivePage] = useState<AppPage>(() => {
    const saved = localStorage.getItem('activePage')
    return (saved as AppPage) || 'pipeline'
  })
  const [customNextStepById, setCustomNextStepById] = useState<Record<number, string>>({})
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
  const [sortKey, setSortKey] = useState<'company' | 'fit_score' | 'status' | 'follow_up_date' | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')

  const [confirmModal, setConfirmModal] = useState<{ message: string } | null>(null)
  const confirmResolveRef = useRef<((value: boolean) => void) | null>(null)

  const showConfirm = (message: string): Promise<boolean> =>
    new Promise((resolve) => {
      confirmResolveRef.current = resolve
      setConfirmModal({ message })
    })

  const handleModalConfirm = () => {
    setConfirmModal(null)
    confirmResolveRef.current?.(true)
  }

  const handleModalCancel = () => {
    setConfirmModal(null)
    confirmResolveRef.current?.(false)
  }

  const loadDashboard = (): Promise<void> => {
    setError(null)
    return Promise.all([fetchApplications()])
      .then(([a]) => { setApplications(a) })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load data'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { localStorage.setItem('activePage', activePage) }, [activePage])

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

  useEffect(() => { void loadDashboard() }, [])

  const patchLocal = (id: number, patch: Partial<EditableRow>) => {
    setApplications((prev: EditableRow[]) =>
      prev.map((row: EditableRow) => (row.id === id ? { ...row, ...patch } : row))
    )
  }

  const handleSortClick = (key: 'company' | 'fit_score' | 'status' | 'follow_up_date') => {
    if (sortKey === key) {
      setSortDir((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  const filteredApplications = useMemo(() => {
    let filtered = filterApplications(applications, profileFilter, listingFilter)
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
  }, [applications, listingFilter, profileFilter, searchQuery, sortDir, sortKey])

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
      const confirmed = await showConfirm(
        'Regenerate and overwrite existing vacancy files for this role? Existing file content will be replaced.'
      )
      if (!confirmed) return
    }

    patchLocal(row.id, { generating: true })
    setError(null)
    try {
      const generated: GenerateDocumentsResult = await generateDocuments(row.id, { overwrite, author_name: undefined })
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
      const confirmed = await showConfirm('Unsaved editor changes detected. Discard changes and open another file?')
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

  void (undefined as unknown as ApplicationItem)

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

      {confirmModal && (
        <ConfirmModal
          message={confirmModal.message}
          onConfirm={handleModalConfirm}
          onCancel={handleModalCancel}
        />
      )}

      {error && <div className="error-banner">{error}</div>}
      {successMessage && <div className="success-banner">{successMessage}</div>}

      {loading ? (
        <p className="empty-state">Loading...</p>
      ) : (
        <>
          {activePage === 'analytics' && (
            <AnalyticsPage applications={applications} />
          )}

          {activePage === 'discovery' && (
            <DiscoveryPage
              setError={setError}
              setSuccessMessage={setSuccessMessage}
              setLoading={setLoading}
              onRunComplete={loadDashboard}
            />
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

                  <div className="search-wrap">
                    <input
                      ref={searchInputRef}
                      id="tracker-search"
                      className="text-input"
                      type="text"
                      placeholder='Search company, role, notes... ("/" to focus)'
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
                        x
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
                          Role {sortKey === 'company' ? (sortDir === 'asc' ? 'up' : 'down') : 'sort'}
                        </th>
                        <th
                          className="sortable-th"
                          onClick={() => handleSortClick('status')}
                          title="Sort by status"
                        >
                          Stage {sortKey === 'status' ? (sortDir === 'asc' ? 'up' : 'down') : 'sort'}
                        </th>
                        <th
                          className="sortable-th"
                          onClick={() => handleSortClick('follow_up_date')}
                          title="Sort by follow-up date"
                        >
                          Due {sortKey === 'follow_up_date' ? (sortDir === 'asc' ? 'up' : 'down') : 'sort'}
                        </th>
                        <th>Process</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredApplications.map((row) => {
                        const scoreBreakdown = parseScoreBreakdown(row)
                        return (
                          <tr key={row.id}>
                            <td>
                              <input
                                type="checkbox"
                                checked={row.selected.toLowerCase() === 'yes'}
                                disabled={!!row.saving}
                                onChange={(e) => { void toggleApplied(row, e.target.checked) }}
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
                                  Score {row.fit_score}
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
                                      Ranges: Strong {SCORE_STRONG_MIN}+, Medium {SCORE_MEDIUM_MIN}-{SCORE_STRONG_MIN - 1}, Stretch below {SCORE_MEDIUM_MIN}
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
                                onClick={() => { void startProcessForRow(row) }}
                              >
                                Process
                              </button>
                              {pendingDeleteId === row.id ? (
                                <div className="delete-confirm">
                                  <span className="muted-mini">Delete?</span>
                                  <button className="delete-btn" onClick={() => void deleteRow(row)}>Yes</button>
                                  <button className="secondary-btn" onClick={() => setPendingDeleteId(null)}>No</button>
                                </div>
                              ) : (
                                <button
                                  className="delete-btn"
                                  title="Permanently delete this application"
                                  disabled={!!row.saving}
                                  onClick={() => setPendingDeleteId(row.id)}
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

              <WorkspaceEditor
                activeProcessRow={activeProcessRow}
                generatedDocsById={generatedDocsById}
                activeFilePath={activeFilePath}
                activeFileExt={activeFileExt}
                fileDraft={fileDraft}
                fileContent={fileContent}
                fileLoading={fileLoading}
                fileSaving={fileSaving}
                fileDirty={fileDirty}
                previewHtml={previewHtml}
                editorSectionRef={editorSectionRef}
                setFileDraft={setFileDraft}
                setFileDirty={setFileDirty}
                openProcessFile={openProcessFile}
                generateDocsForRow={generateDocsForRow}
                saveFile={saveFile}
              />
            </>
          )}
        </>
      )}
    </div>
  )
}
