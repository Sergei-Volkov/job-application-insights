import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import type { ApplicationItem, GenerateDocumentsResult } from './api'

vi.mock('recharts', () => {
  const passthrough = ({ children }: { children?: unknown }) => children
  return {
    Bar: passthrough,
    BarChart: passthrough,
    CartesianGrid: passthrough,
    Legend: passthrough,
    Line: passthrough,
    LineChart: passthrough,
    ResponsiveContainer: passthrough,
    Tooltip: passthrough,
    XAxis: passthrough,
    YAxis: passthrough,
  }
})

const apiMocks = vi.hoisted(() => {
  return {
    fetchApplications: vi.fn(),
    runDiscovery: vi.fn(),
    fetchDiscoveryStatus: vi.fn(),
    updateApplication: vi.fn(),
    generateDocuments: vi.fn(),
    readWorkspaceFile: vi.fn(),
    writeWorkspaceFile: vi.fn(),
    deleteApplication: vi.fn(),
    upsertApplication: vi.fn(),
    extractJobFromUrl: vi.fn(),
  }
})

vi.mock('./api', () => apiMocks)

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn()
}

function makeRow(overrides: Partial<ApplicationItem> = {}): ApplicationItem {
  return {
    id: 1,
    selected: 'no',
    date_found: '2026-05-08',
    date_applied: '',
    company: 'Northwind',
    role: 'Data Engineer',
    location: 'Remote',
    source: 'Mock Source',
    remote_type: 'Remote',
    fit: 'Strong',
    fit_score: 20,
    link: 'https://example.com/job/1',
    status: 'To review',
    next_step: 'Tailor CV and apply soon',
    follow_up_date: '',
    resume_ref: '',
    cover_letter_ref: '',
    match_profile: 'de',
    first_seen_at: '2026-05-08',
    last_seen_at: '2026-05-08',
    listing_fingerprint: 'abc',
    change_note: '',
    notes: 'Mock notes',
    ...overrides,
  }
}

describe('App tracker workflow', () => {
  afterEach(cleanup)
  beforeEach(() => vi.resetAllMocks())

  it('supports generate, open, save, and mark applied flow', async () => {
    const generated: GenerateDocumentsResult = {
      vacancy_dir: 'applications/vacancies/northwind_data_engineer',
      vacancy_path: 'applications/vacancies/northwind_data_engineer/vacancy.md',
      cv_path: 'applications/vacancies/northwind_data_engineer/cv.tex',
      cover_letter_path: 'applications/vacancies/northwind_data_engineer/cover_letter.md',
      notes_path: 'applications/vacancies/northwind_data_engineer/notes.md',
    }

    apiMocks.fetchApplications.mockResolvedValue({ items: [makeRow()], total: 1, limit: 50, offset: 0 })
    apiMocks.generateDocuments.mockResolvedValue(generated)
    apiMocks.readWorkspaceFile.mockResolvedValue({ path: generated.cover_letter_path, content: 'Cover Draft' })
    apiMocks.writeWorkspaceFile.mockResolvedValue({ path: generated.cover_letter_path, content: 'Cover Draft edited' })
    apiMocks.updateApplication.mockImplementation(async (_id: number, patch: Partial<ApplicationItem>) => ({
      ...makeRow(),
      ...patch,
    }))

    render(<App />)

    await screen.findByText('Application Tracker')

    const processBtn = screen.getByRole('button', { name: 'Process' })
    await userEvent.click(processBtn)

    const generateBtn = await screen.findByRole('button', { name: 'Generate files' })
    await userEvent.click(generateBtn)

    await waitFor(() => {
      expect(apiMocks.generateDocuments).toHaveBeenCalled()
      expect(apiMocks.readWorkspaceFile).toHaveBeenCalledWith(generated.cover_letter_path)
    })

    const editor = document.querySelector('textarea.editor-area')
    expect(editor).toBeTruthy()
    if (!editor) {
      throw new Error('Editor textarea not found')
    }
    await userEvent.clear(editor)
    await userEvent.type(editor, 'Cover Draft edited')

    const saveFileBtn = screen.getByRole('button', { name: 'Save file' })
    await userEvent.click(saveFileBtn)

    await waitFor(() => {
      expect(apiMocks.writeWorkspaceFile).toHaveBeenCalledWith(generated.cover_letter_path, 'Cover Draft edited')
    })

    const appliedCheckbox = screen.getByRole('checkbox')
    await userEvent.click(appliedCheckbox)

    await waitFor(() => {
      expect(apiMocks.updateApplication).toHaveBeenCalled()
    })

    const calls = apiMocks.updateApplication.mock.calls
    const lastCall = calls[calls.length - 1]
    expect(lastCall).toBeTruthy()
    if (lastCall) {
      const patch = lastCall[1] as { selected: string; status: string; date_applied: string }
      expect(patch.selected).toBe('yes')
      expect(patch.status).toBe('Applied')
      expect(typeof patch.date_applied).toBe('string')
      expect(patch.date_applied.length).toBe(10)
    }
  })

  it('filters tracker rows via search box', async () => {
    apiMocks.fetchApplications.mockResolvedValue({
      items: [
        makeRow({ id: 1, company: 'Northwind', role: 'Data Engineer' }),
        makeRow({ id: 2, company: 'Acme Corp', role: 'Backend Engineer' }),
      ],
      total: 2,
      limit: 50,
      offset: 0,
    })
    render(<App />)
    await screen.findByText('Application Tracker')

    const searchInput = screen.getByPlaceholderText(/Search company/i)
    await userEvent.type(searchInput, 'Acme')

    expect(screen.getByText('Acme Corp')).toBeTruthy()
    expect(screen.queryByText('Northwind')).toBeNull()
  })

  it('shows inline delete confirmation and removes row on confirm', async () => {
    apiMocks.fetchApplications.mockResolvedValue({ items: [makeRow()], total: 1, limit: 50, offset: 0 })
    apiMocks.deleteApplication.mockResolvedValue(undefined)
    render(<App />)
    await screen.findByText('Application Tracker')

    const deleteBtn = screen.getByRole('button', { name: 'Delete' })
    await userEvent.click(deleteBtn)

    expect(screen.getByText('Delete?')).toBeTruthy()
    const confirmBtn = screen.getByRole('button', { name: 'Yes' })
    await userEvent.click(confirmBtn)

    await waitFor(() => {
      expect(apiMocks.deleteApplication).toHaveBeenCalledWith(1)
    })
    expect(screen.queryByText('Northwind')).toBeNull()
  })

  it('renders score breakdown details panel with keyword data', async () => {
    apiMocks.fetchApplications.mockResolvedValue({
      items: [
        makeRow({
          fit_score: 14,
          score_breakdown: {
            score: 14,
            fit: 'Strong',
            matched_keywords: ['Python', 'SQL'],
            missing_skills: ['dbt'],
            fit_notes: 'Direct overlap on Python, SQL.',
          },
        }),
      ],
      total: 1,
      limit: 50,
      offset: 0,
    })
    render(<App />)
    await screen.findByText('Application Tracker')

    const summary = screen.getByText('Score breakdown')
    await userEvent.click(summary)

    const panel = document.querySelector('.score-breakdown')
    expect(panel).toBeTruthy()
    expect(panel!.textContent).toContain('Python, SQL')
    expect(panel!.textContent).toContain('dbt')
    expect(panel!.textContent).toContain('Direct overlap on Python, SQL')
  })

  it('shows Open job link when present and No link when missing', async () => {
    apiMocks.fetchApplications.mockResolvedValue({
      items: [
        makeRow({ id: 1, link: 'https://example.com/job/with-link' }),
        makeRow({ id: 2, company: 'NoLink Inc', role: 'Engineer', link: '' }),
      ],
      total: 2,
      limit: 50,
      offset: 0,
    })

    render(<App />)
    await screen.findByText('Application Tracker')

    const openJobLinks = screen.getAllByRole('link', { name: 'Open job' })
    expect(openJobLinks.length).toBe(1)
    expect(screen.getByText('No link')).toBeTruthy()
  })

  it('adds a job via tracker quick add and shows it in table', async () => {
    apiMocks.fetchApplications.mockResolvedValue({
      items: [makeRow()],
      total: 1,
      limit: 50,
      offset: 0,
    })
    apiMocks.upsertApplication.mockResolvedValue(
      makeRow({ id: 7, company: 'Quick Co', role: 'Platform Engineer', link: 'https://example.com/job/quick' })
    )

    render(<App />)
    await screen.findByText('Application Tracker')

    const companyInput = screen.getByPlaceholderText('Company')
    const roleInput = screen.getByPlaceholderText('Role')
    const linkInput = screen.getByPlaceholderText('Job link (optional)')

    await userEvent.type(companyInput, 'Quick Co')
    await userEvent.type(roleInput, 'Platform Engineer')
    await userEvent.type(linkInput, 'https://example.com/job/quick')

    await userEvent.click(screen.getByRole('button', { name: 'Quick add' }))

    await waitFor(() => {
      expect(apiMocks.upsertApplication).toHaveBeenCalled()
    })
    expect(screen.getByText('Quick Co')).toBeTruthy()
    expect(screen.getByText('Platform Engineer')).toBeTruthy()
  })

  it('ingests a job URL into visible quick-add fields before saving', async () => {
    apiMocks.fetchApplications.mockResolvedValue({
      items: [makeRow()],
      total: 1,
      limit: 50,
      offset: 0,
    })
    apiMocks.extractJobFromUrl.mockResolvedValue({
      url: 'https://example.com/job/quick',
      source: 'example.com',
      page_title: 'Platform Engineer at Quick Co',
      company: 'Quick Co',
      role: 'Platform Engineer',
      location: 'Remote',
      remote_type: 'Remote',
      description: 'Build reliable data pipelines and tooling.',
    })
    apiMocks.upsertApplication.mockResolvedValue(
      makeRow({
        id: 7,
        company: 'Quick Co',
        role: 'Platform Engineer',
        link: 'https://example.com/job/quick',
      })
    )

    render(<App />)
    await screen.findByText('Application Tracker')

    const companyInput = screen.getByPlaceholderText('Company') as HTMLInputElement
    const roleInput = screen.getByPlaceholderText('Role') as HTMLInputElement
    const linkInput = screen.getByPlaceholderText('Job link (optional)') as HTMLInputElement
    const locationInput = screen.getByPlaceholderText('Location (optional)') as HTMLInputElement
    const remoteTypeInput = screen.getByPlaceholderText('Remote type (optional)') as HTMLInputElement
    const notesInput = screen.getByPlaceholderText('Notes (optional)') as HTMLTextAreaElement

    await userEvent.type(linkInput, 'https://example.com/job/quick')
    await userEvent.click(screen.getByRole('button', { name: 'Ingest URL' }))

    await waitFor(() => {
      expect(apiMocks.extractJobFromUrl).toHaveBeenCalledWith({ url: 'https://example.com/job/quick' })
    })

    expect(companyInput.value).toBe('Quick Co')
    expect(roleInput.value).toBe('Platform Engineer')
    expect(locationInput.value).toBe('Remote')
    expect(remoteTypeInput.value).toBe('Remote')
    expect(notesInput.value).toContain('Build reliable data pipelines and tooling.')

    await userEvent.click(screen.getByRole('button', { name: 'Quick add' }))

    await waitFor(() => {
      expect(apiMocks.upsertApplication).toHaveBeenCalledWith(
        expect.objectContaining({
          company: 'Quick Co',
          role: 'Platform Engineer',
          link: 'https://example.com/job/quick',
          location: 'Remote',
          remote_type: 'Remote',
          notes: expect.stringContaining('Build reliable data pipelines and tooling.'),
          status: 'To review',
          match_profile: 'de',
          source: 'manual',
        })
      )
    })
  })

  it('prefills tracker search from seed and clears seed key', async () => {
    localStorage.setItem('trackerSearchSeed', 'Acme')
    apiMocks.fetchApplications.mockResolvedValue({
      items: [
        makeRow({ id: 1, company: 'Northwind', role: 'Data Engineer' }),
        makeRow({ id: 2, company: 'Acme Corp', role: 'Backend Engineer' }),
      ],
      total: 2,
      limit: 50,
      offset: 0,
    })

    render(<App />)
    await screen.findByText('Application Tracker')

    const searchInput = screen.getByPlaceholderText(/Search company/i) as HTMLInputElement
    expect(searchInput.value).toBe('Acme')
    expect(localStorage.getItem('trackerSearchSeed')).toBeNull()

    expect(screen.getByText('Acme Corp')).toBeTruthy()
    expect(screen.queryByText('Northwind')).toBeNull()
  })
})
