import { useMemo, useRef, useState } from 'react'
import DOMPurify from 'dompurify'
import {
  fetchApplications,
  generateDocuments,
  readWorkspaceFile,
  updateApplication,
  deleteApplication,
  writeWorkspaceFile,
  ApiError,
} from '../api'
import { NEXT_STEP_OPTIONS, SCORE_STRONG_MIN, SCORE_MEDIUM_MIN } from '../appConstants'
import type { DiscoveryProfile, EditableRow, GeneratedDocsMap, ListingFilter } from '../appTypes'
import { getRowDocLinks } from '../utils/docs'
import { filterApplications, isNewListing, isUpdatedListing, normalizedProfile } from '../utils/listing'
import { renderMarkdownPreview, renderTexPreview } from '../utils/preview'

type ScoreBreakdown = {
  score: number | null
  fit: string
  matchedKeywords: string[]
  missingSkills: string[]
  fitNotes: string
}

type TrackerPageProps = {
  applications: EditableRow[]
  setApplications: React.Dispatch<React.SetStateAction<EditableRow[]>>
  setError: (msg: string | null) => void
  setSuccessMessage: (msg: string | null) => void
}

export default function TrackerPage({ applications, setApplications, setError, setSuccessMessage }: TrackerPageProps) {
  const [profileFilter, setProfileFilter] = useState<'all' | DiscoveryProfile>('all')
  const [listingFilter, setListingFilter] = useState<ListingFilter>('all')
  const [sourceFilter, setSourceFilter] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [sortKey, setSortKey] = useState<'company' | 'fit_score' | 'status' | 'follow_up_date' | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [generatedDocsById, setGeneratedDocsById] = useState<GeneratedDocsMap>({})
  const [customNextStepById, setCustomNextStepById] = useState<Record<number, string>>({})
  const [activeFilePath, setActiveFilePath] = useState('')
  const [fileContent, setFileContent] = useState('')
  const [fileDraft, setFileDraft] = useState('')
  const [fileLoading, setFileLoading] = useState(false)
  const [fileSaving, setFileSaving] = useState(false)
  const [fileDirty, setFileDirty] = useState(false)
  const [activeProcessId, setActiveProcessId] = useState<number | null>(null)
  const [lastProcessFileById, setLastProcessFileById] = useState<Record<number, string>>({})
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const editorSectionRef = useRef<HTMLElement | null>(null)
  const searchInputRef = useRef<HTMLInputElement | null>(null)

  const loadMore = (): void => {
    setLoadingMore(true)
    fetchApplications(50, applications.length)
      .then((more) => setApplications((prev) => [...prev, ...more]))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load more'))
      .finally(() => setLoadingMore(false))
  }

  const patchLocal = (id: number, patch: Partial<EditableRow>) => {
    setApplications((prev) => prev.map((row) => (row.id === id ? { ...row, ...patch } : row)))
  }

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
    let parsed: { score?: number; fit?: string; matched_keywords?: string[]; missing_skills?: string[]; fit_notes?: string } = {}
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

  const saveRow = async (row: EditableRow) => {
    const scrollY = window.scrollY
    patchLocal(row.id, { saving: true, rowError: null })
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
      patchLocal(row.id, { ...updated, saving: false, rowError: null })
    } catch (e) {
      patchLocal(row.id, { saving: false, rowError: e instanceof Error ? e.message : 'Failed to save' })
    } finally {
      window.scrollTo({ top: scrollY })
    }
  }

  const deleteRow = async (row: EditableRow) => {
    setPendingDeleteId(null)
    try {
      await deleteApplication(row.id)
      setApplications((prev) => prev.filter((r) => r.id !== row.id))
      if (activeProcessId === row.id) setActiveProcessId(null)
    } catch (e) {
      patchLocal(row.id, { rowError: e instanceof Error ? e.message : 'Failed to delete' })
    }
  }

  const toggleApplied = async (row: EditableRow, checked: boolean) => {
    const scrollY = window.scrollY
    const previous = { selected: row.selected, date_applied: row.date_applied, status: row.status }
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
    patchLocal(row.id, { ...patch, saving: true, rowError: null })
    try {
      const updated = await updateApplication(row.id, patch)
      patchLocal(row.id, { ...updated, saving: false, rowError: null })
    } catch (e) {
      patchLocal(row.id, { ...previous, saving: false, rowError: e instanceof Error ? e.message : 'Failed to update status' })
    } finally {
      window.scrollTo({ top: scrollY })
    }
  }

  const generateDocsForRow = async (row: EditableRow, overwrite = false) => {
    if (overwrite) {
      const confirmed = window.confirm(
        'Regenerate and overwrite existing vacancy files for this role? Existing file content will be replaced.'
      )
      if (!confirmed) return
    }
    patchLocal(row.id, { generating: true, rowError: null })
    setError(null)
    try {
      const generated = await generateDocuments(row.id, { overwrite, author_name: undefined })
      setGeneratedDocsById((prev) => ({ ...prev, [row.id]: generated }))
      patchLocal(row.id, { resume_ref: generated.cv_path, cover_letter_ref: generated.cover_letter_path, generating: false })
      await openWorkspaceFile(generated.cover_letter_path)
    } catch (e) {
      const msg = e instanceof ApiError && e.status === 409
        ? `${e.message}. Use Regenerate to overwrite files when needed.`
        : e instanceof Error ? e.message : 'Failed to generate tailored files'
      patchLocal(row.id, { generating: false, rowError: msg })
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

  const startProcessForRow = async (row: EditableRow) => {
    setActiveProcessId(row.id)
    const rowDocs = getRowDocLinks(row, generatedDocsById)
    const preferredPath =
      lastProcessFileById[row.id] || rowDocs.vacancyPath || rowDocs.notesPath || rowDocs.coverLetterPath || rowDocs.cvPath
    if (preferredPath) {
      await openWorkspaceFile(preferredPath)
    }
    editorSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  const openProcessFile = async (rowId: number, path: string) => {
    setLastProcessFileById((prev) => ({ ...prev, [rowId]: path }))
    await openWorkspaceFile(path)
  }

  // '/' shortcut to focus search
  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
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

  return (
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div onKeyDown={handleKeyDown}>
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
                          Score {row.fit_score} · {scoreBandLabel(row.fit_score)}
                        </span>
                        {isUpdatedListing(row) && <span className="status-pill">Updated</span>}
                        {!isUpdatedListing(row) && isNewListing(row) && <span className="status-pill">New</span>}
                        {row.rowError && (
                          <span className="row-error-pill" title={row.rowError}>
                            ⚠ {row.rowError}
                            <button className="dismiss-error-btn" onClick={() => patchLocal(row.id, { rowError: null })} aria-label="Dismiss error">×</button>
                          </span>
                        )}
                        <details className="row-details">
                          <summary className="toggle-summary">Score breakdown</summary>
                          <div className="details-panel score-breakdown">
                            <div><strong>Total:</strong> {scoreBreakdown.score ?? row.fit_score}</div>
                            <div><strong>Band:</strong> {scoreBreakdown.fit || scoreBandLabel(row.fit_score)}</div>
                            <div>
                              <strong>Matched keywords:</strong>{' '}
                              {scoreBreakdown.matchedKeywords.length > 0 ? scoreBreakdown.matchedKeywords.join(', ') : 'None listed'}
                            </div>
                            <div>
                              <strong>Missing/adjacent:</strong>{' '}
                              {scoreBreakdown.missingSkills.length > 0 ? scoreBreakdown.missingSkills.join(', ') : 'None listed'}
                            </div>
                            <div><strong>Notes:</strong> {scoreBreakdown.fitNotes || 'No notes yet'}</div>
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
                            <option key={option} value={option}>{option}</option>
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
                        title="Save changes for this row"
                        disabled={!!row.saving}
                        onClick={() => { void saveRow(row) }}
                      >
                        {row.saving ? 'Saving…' : 'Save'}
                      </button>
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
                          <button
                            className="secondary-btn"
                            style={{ fontSize: '0.82rem', padding: '5px 10px' }}
                            onClick={() => setPendingDeleteId(null)}
                          >
                            No
                          </button>
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
          <div className="pagination-bar">
            <span className="muted-mini">{filteredApplications.length} shown of {applications.length} loaded</span>
            <button
              className="btn-secondary"
              onClick={loadMore}
              disabled={loadingMore}
            >
              {loadingMore ? 'Loading…' : 'Load more'}
            </button>
          </div>
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
                  onClick={() => { void generateDocsForRow(activeProcessRow) }}
                >
                  {activeProcessRow.generating ? 'Generating...' : 'Generate files'}
                </button>
              ) : (
                <button
                  className="secondary-btn process-generate-btn"
                  title="Regenerate and overwrite existing role files"
                  disabled={!!activeProcessRow.generating}
                  onClick={() => { void generateDocsForRow(activeProcessRow, true) }}
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
                    dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(previewHtml) }}
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
    </div>
  )
}


