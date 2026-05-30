import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App'
import type { ApplicationItem, DiscoveryRunResult, GenerateDocumentsResult } from './api'

vi.mock('recharts', () => {
  const passthrough = ({ children }: { children?: unknown }) => children
  return {
    Bar: passthrough,
    BarChart: passthrough,
    CartesianGrid: passthrough,
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
    updateApplication: vi.fn(),
    generateDocuments: vi.fn(),
    readWorkspaceFile: vi.fn(),
    writeWorkspaceFile: vi.fn(),
  }
})

vi.mock('./api', () => apiMocks)

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = vi.fn()
}

function makeRow(): ApplicationItem {
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
  }
}

describe('App tracker workflow', () => {
  it('supports generate, open, save, and mark applied flow', async () => {
    const runResult: DiscoveryRunResult = { exit_code: 0, command: [], stdout: '', stderr: '' }
    const generated: GenerateDocumentsResult = {
      vacancy_dir: 'applications/vacancies/northwind_data_engineer',
      vacancy_path: 'applications/vacancies/northwind_data_engineer/vacancy.md',
      cv_path: 'applications/vacancies/northwind_data_engineer/cv.tex',
      cover_letter_path: 'applications/vacancies/northwind_data_engineer/cover_letter.md',
      notes_path: 'applications/vacancies/northwind_data_engineer/notes.md',
    }

    apiMocks.fetchApplications.mockResolvedValue([makeRow()])
    apiMocks.runDiscovery.mockResolvedValue(runResult)
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
})
