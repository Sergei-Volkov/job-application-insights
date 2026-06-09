import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import DiscoveryPage from './DiscoveryPage'
import type { DiscoveryRunResult, DiscoveryStatus } from '../api'

// ── API module mock ──────────────────────────────────────────────────────────

const apiMocks = vi.hoisted(() => ({
  runDiscovery: vi.fn(),
  fetchDiscoveryStatus: vi.fn(),
  upsertApplication: vi.fn(),
  extractJobFromUrl: vi.fn(),
}))

vi.mock('../api', () => apiMocks)

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeResult(overrides: Partial<DiscoveryRunResult> = {}): DiscoveryRunResult {
  return {
    exit_code: 0,
    command: [],
    stdout: 'Discovery completed successfully. Enable verbose=true to inspect execution logs.',
    stderr: '',
    source_results: [],
    strict_count: 3,
    broad_count: 8,
    synced_count: 3,
    failed_count: 0,
    ...overrides,
  }
}

function makeStatus(overrides: Partial<DiscoveryStatus> = {}): DiscoveryStatus {
  return {
    in_flight: false,
    elapsed_seconds: null,
    cooldown_seconds_remaining: null,
    ...overrides,
  }
}

function renderDiscoveryPage() {
  const setError = vi.fn()
  const setSuccessMessage = vi.fn()
  const setLoading = vi.fn()
  const onRunComplete = vi.fn().mockResolvedValue(undefined)
  const onOpenTracker = vi.fn()

  render(
    <DiscoveryPage
      setError={setError}
      setSuccessMessage={setSuccessMessage}
      setLoading={setLoading}
      onRunComplete={onRunComplete}
      onOpenTracker={onOpenTracker}
    />
  )

  return { setError, setSuccessMessage, setLoading, onRunComplete, onOpenTracker }
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe('DiscoveryPage', () => {
  afterEach(() => {
    cleanup()
    localStorage.clear()
  })
  beforeEach(() => {
    vi.resetAllMocks()
    localStorage.clear()
  })

  it('renders the profile selector and Run discovery button', () => {
    renderDiscoveryPage()

    expect(screen.getByRole('combobox', { name: /profile/i })).toBeTruthy()
    expect(screen.getByRole('button', { name: /run discovery/i })).toBeTruthy()
  })

  it('renders checkboxes for all discovery sources', () => {
    renderDiscoveryPage()

    expect(screen.getByRole('checkbox', { name: /we work remotely/i })).toBeTruthy()
    expect(screen.getByRole('checkbox', { name: /remotive/i })).toBeTruthy()
    expect(screen.getByRole('checkbox', { name: /remote ok/i })).toBeTruthy()
    expect(screen.getByRole('checkbox', { name: /arbeitnow/i })).toBeTruthy()
  })

  it('calls runDiscovery with default params and shows result on success', async () => {
    const result = makeResult({ strict_count: 5, broad_count: 12, synced_count: 5 })
    apiMocks.runDiscovery.mockResolvedValue(result)
    apiMocks.fetchDiscoveryStatus.mockResolvedValue(makeStatus())

    const { onRunComplete, setLoading } = renderDiscoveryPage()

    const runBtn = screen.getByRole('button', { name: /run discovery/i })
    await userEvent.click(runBtn)

    await waitFor(() => expect(apiMocks.runDiscovery).toHaveBeenCalledOnce())

    const callArg = apiMocks.runDiscovery.mock.calls[0][0] as Record<string, unknown>
    expect(callArg.limit).toBe(40)
    expect(callArg.min_score).toBe(7)
    expect(callArg.max_age_days).toBe(45)
    expect(callArg.include_stretch).toBe(false)

    await waitFor(() => expect(onRunComplete).toHaveBeenCalled())
    expect(setLoading).toHaveBeenCalledWith(true)

    expect(screen.getByText(/discovery exit code/i)).toBeTruthy()
    // strict_count is rendered as <strong>{strict_count}</strong>; get all '5' elements
    const fives = screen.getAllByText('5')
    expect(fives.length).toBeGreaterThan(0)
  })

  it('calls setError when runDiscovery throws', async () => {
    apiMocks.runDiscovery.mockRejectedValue(new Error('Network error'))
    apiMocks.fetchDiscoveryStatus.mockResolvedValue(makeStatus())

    const { setError } = renderDiscoveryPage()

    await userEvent.click(screen.getByRole('button', { name: /run discovery/i }))

    await waitFor(() => expect(setError).toHaveBeenCalledWith('Network error'))
  })

  it('forwards the selected profile to runDiscovery', async () => {
    apiMocks.runDiscovery.mockResolvedValue(makeResult())
    apiMocks.fetchDiscoveryStatus.mockResolvedValue(makeStatus())

    renderDiscoveryPage()

    const profileSelect = screen.getByRole('combobox', { name: /profile/i })
    await userEvent.selectOptions(profileSelect, 'swe')

    await userEvent.click(screen.getByRole('button', { name: /run discovery/i }))

    await waitFor(() => expect(apiMocks.runDiscovery).toHaveBeenCalledOnce())
    const callArg = apiMocks.runDiscovery.mock.calls[0][0] as Record<string, unknown>
    expect(callArg.profile).toBe('swe')
  })

  it('omits unchecked sources from the runDiscovery payload', async () => {
    apiMocks.runDiscovery.mockResolvedValue(makeResult())
    apiMocks.fetchDiscoveryStatus.mockResolvedValue(makeStatus())

    renderDiscoveryPage()

    // Uncheck Remotive
    const remotiveBox = screen.getByRole('checkbox', { name: /remotive/i })
    await userEvent.click(remotiveBox)

    await userEvent.click(screen.getByRole('button', { name: /run discovery/i }))

    await waitFor(() => expect(apiMocks.runDiscovery).toHaveBeenCalledOnce())
    const callArg = apiMocks.runDiscovery.mock.calls[0][0] as Record<string, unknown>
    const sources = callArg.sources as string[]
    expect(sources).not.toContain('remotive')
    expect(sources).toContain('wwr')
  })

  it('reset button restores default discovery params and clears localStorage', async () => {
    renderDiscoveryPage()

    // Change the limit
    const limitInput = screen.getByRole('spinbutton', { name: /limit/i }) as HTMLInputElement
    fireEvent.change(limitInput, { target: { value: '99' } })

    expect(limitInput.value).toBe('99')

    // Click Reset
    const resetBtn = screen.getByRole('button', { name: /reset/i })
    await userEvent.click(resetBtn)

    // After reset, discoveryParams reverts to defaults; useEffect writes them back to localStorage
    await waitFor(() => expect(limitInput.value).toBe('40'))
    // localStorage is re-written with default params (not null) after the useEffect fires
    const stored = localStorage.getItem('discoveryParams')
    expect(stored).not.toBeNull()
    const parsed = JSON.parse(stored!) as Record<string, unknown>
    expect(Number(parsed.limit)).toBe(40)
  })

  it('shows Add job button and calls upsertApplication when company and role are filled', async () => {
    apiMocks.upsertApplication.mockResolvedValue({})
    apiMocks.fetchDiscoveryStatus.mockResolvedValue(makeStatus())

    const { onRunComplete, setSuccessMessage } = renderDiscoveryPage()

    const companyInput = screen.getByPlaceholderText('Company')
    const roleInput = screen.getByPlaceholderText('Role')

    await userEvent.type(companyInput, 'Acme Corp')
    await userEvent.type(roleInput, 'Backend Engineer')

    await userEvent.click(screen.getByRole('button', { name: /add job/i }))

    await waitFor(() => expect(apiMocks.upsertApplication).toHaveBeenCalledOnce())
    const payload = apiMocks.upsertApplication.mock.calls[0][0] as Record<string, unknown>
    expect(payload.company).toBe('Acme Corp')
    expect(payload.role).toBe('Backend Engineer')
    expect(payload.status).toBe('To review')
    expect(payload.source).toBe('manual')

    await waitFor(() => expect(onRunComplete).toHaveBeenCalled())
    expect(setSuccessMessage).toHaveBeenCalledWith('Job added successfully')
  })

  it('shows setError when Add job is clicked with empty company', async () => {
    const { setError } = renderDiscoveryPage()

    // Leave company blank
    await userEvent.type(screen.getByPlaceholderText('Role'), 'Engineer')
    await userEvent.click(screen.getByRole('button', { name: /add job/i }))

    expect(setError).toHaveBeenCalledWith('Company and role are required')
    expect(apiMocks.upsertApplication).not.toHaveBeenCalled()
  })

  it('persists discoveryParams to localStorage after a param change', async () => {
    renderDiscoveryPage()

    const limitInput = screen.getByRole('spinbutton', { name: /limit/i }) as HTMLInputElement
    fireEvent.change(limitInput, { target: { value: '20' } })

    await waitFor(() => {
      const stored = localStorage.getItem('discoveryParams')
      expect(stored).not.toBeNull()
      const parsed = JSON.parse(stored!) as Record<string, unknown>
      expect(Number(parsed.limit)).toBe(20)
    })
  })

  it('ingests manual URL and prefills company/role', async () => {
    apiMocks.extractJobFromUrl.mockResolvedValue({
      url: 'https://example.com/jobs/42',
      source: 'example.com',
      page_title: 'Data Engineer at Acme',
      company: 'Acme',
      role: 'Data Engineer',
      location: 'Remote',
      remote_type: 'Remote',
      description: 'Build ELT pipelines.',
    })
    renderDiscoveryPage()

    await userEvent.type(screen.getByPlaceholderText('Job link (optional)'), 'https://example.com/jobs/42')
    await userEvent.click(screen.getByRole('button', { name: 'Ingest URL' }))

    await waitFor(() => expect(apiMocks.extractJobFromUrl).toHaveBeenCalledOnce())
    const companyInput = screen.getByPlaceholderText('Company') as HTMLInputElement
    const roleInput = screen.getByPlaceholderText('Role') as HTMLInputElement
    expect(companyInput.value).toBe('Acme')
    expect(roleInput.value).toBe('Data Engineer')
  })

  it('shows Open in Tracker action after manual add', async () => {
    apiMocks.upsertApplication.mockResolvedValue({})
    const { onOpenTracker } = renderDiscoveryPage()

    expect(screen.queryByRole('button', { name: 'Open in Tracker' })).toBeNull()

    await userEvent.type(screen.getByPlaceholderText('Company'), 'Acme')
    await userEvent.type(screen.getByPlaceholderText('Role'), 'Backend Engineer')
    await userEvent.click(screen.getByRole('button', { name: /add job/i }))

    const openTrackerBtn = await screen.findByRole('button', { name: 'Open in Tracker' })
    await userEvent.click(openTrackerBtn)

    expect(localStorage.getItem('trackerSearchSeed')).toBe('Acme Backend Engineer')
    expect(onOpenTracker).toHaveBeenCalled()
  })
})
