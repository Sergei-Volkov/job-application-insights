import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AnalyticsPage from './AnalyticsPage'
import type { EditableRow } from '../appTypes'

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

function makeRow(overrides: Partial<EditableRow> = {}): EditableRow {
  return {
    id: 1,
    selected: 'no',
    date_found: '2026-05-01',
    date_applied: '',
    company: 'Acme',
    role: 'Data Engineer',
    location: 'Remote',
    source: 'Remotive',
    remote_type: 'Remote',
    fit: 'Strong',
    fit_score: 20,
    link: 'https://example.com',
    status: 'Applied',
    next_step: '',
    follow_up_date: '',
    resume_ref: '',
    cover_letter_ref: '',
    match_profile: 'de',
    first_seen_at: '2026-05-01',
    last_seen_at: '2026-05-01',
    listing_fingerprint: 'abc',
    change_note: '',
    notes: '',
    ...overrides,
  }
}

// metric element that shows the total count
const getMetric = () => screen.getByText(/^\d+$/, { selector: '.metric' })

describe('AnalyticsPage', () => {
  afterEach(cleanup)

  it('renders total applications count', () => {
    render(<AnalyticsPage applications={[makeRow(), makeRow({ id: 2, company: 'Beta' })]} />)
    expect(getMetric().textContent).toBe('2')
    expect(screen.getByText('Total Applications')).toBeTruthy()
  })

  it('shows 0 when no applications', () => {
    render(<AnalyticsPage applications={[]} />)
    expect(getMetric().textContent).toBe('0')
  })

  it('filters by match profile — only de rows visible in count', async () => {
    const rows = [
      makeRow({ id: 1, match_profile: 'de' }),
      makeRow({ id: 2, match_profile: 'swe', company: 'SweComp' }),
    ]
    render(<AnalyticsPage applications={rows} />)
    expect(getMetric().textContent).toBe('2')

    const profileSelect = screen.getByLabelText('Match profile')
    await userEvent.selectOptions(profileSelect, 'de')
    expect(getMetric().textContent).toBe('1')
  })

  it('shows skill gap empty state when no notes contain the marker', () => {
    render(<AnalyticsPage applications={[makeRow({ notes: 'No marker here' })]} />)
    const empties = screen.getAllByText(/No missing-skill markers/i)
    expect(empties.length).toBeGreaterThan(0)
  })

  it('hides skill gap empty state when notes contain the marker', () => {
    const row = makeRow({
      notes: 'Direct overlap on Python. missing or adjacent tools: dbt, Snowflake.',
    })
    render(<AnalyticsPage applications={[row]} />)
    expect(screen.queryAllByText(/No missing-skill markers/i)).toHaveLength(0)
    expect(screen.getByText('Skill Gaps')).toBeTruthy()
  })

  it('shows weekly trend empty state when no dated rows', () => {
    render(<AnalyticsPage applications={[makeRow({ date_found: '' })]} />)
    const empties = screen.getAllByText(/No dated applications/i)
    expect(empties.length).toBeGreaterThan(0)
  })

  it('hides weekly trend empty state when rows have dates', () => {
    render(<AnalyticsPage applications={[makeRow({ date_found: '2026-05-01' })]} />)
    expect(screen.queryAllByText(/No dated applications/i)).toHaveLength(0)
    expect(screen.getByText('Weekly Trend')).toBeTruthy()
  })

  it('filters by listing updated — only rows with updated on in change_note', async () => {
    const updatedRow = makeRow({ id: 1, change_note: 'updated on 2026-05-10' })
    const normalRow = makeRow({ id: 2, company: 'Fresh', change_note: '' })
    render(<AnalyticsPage applications={[updatedRow, normalRow]} />)

    const listingSelect = screen.getByLabelText('Listing')
    await userEvent.selectOptions(listingSelect, 'updated')
    expect(getMetric().textContent).toBe('1')
  })

  it('filters by listing new — only rows where first_seen_at equals last_seen_at', async () => {
    const today = new Date().toISOString().slice(0, 10)
    const newRow = makeRow({ id: 1, first_seen_at: today, last_seen_at: today })
    const oldRow = makeRow({ id: 2, company: 'Old', first_seen_at: '2026-01-01', last_seen_at: today })
    render(<AnalyticsPage applications={[newRow, oldRow]} />)

    const listingSelect = screen.getByLabelText('Listing')
    await userEvent.selectOptions(listingSelect, 'new')
    expect(getMetric().textContent).toBe('1')
  })
})
