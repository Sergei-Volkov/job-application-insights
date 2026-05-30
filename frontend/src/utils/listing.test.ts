import { describe, it, expect } from 'vitest'
import { normalizedProfile, isNewListing, isUpdatedListing, filterApplications } from './listing'
import type { EditableRow } from '../appTypes'

const row = (overrides: Partial<EditableRow> = {}): EditableRow =>
  ({
    id: 1,
    company: 'Acme',
    role: 'Engineer',
    link: 'https://example.com',
    status: 'To review',
    match_profile: '',
    ...overrides,
  } as EditableRow)

describe('normalizedProfile', () => {
  it('returns de for empty string', () => {
    expect(normalizedProfile(row({ match_profile: '' }))).toBe('de')
  })
  it('returns de for unknown value', () => {
    expect(normalizedProfile(row({ match_profile: 'xyz' }))).toBe('de')
  })
  it('returns swe', () => {
    expect(normalizedProfile(row({ match_profile: 'swe' }))).toBe('swe')
  })
  it('returns sre', () => {
    expect(normalizedProfile(row({ match_profile: 'SRE' }))).toBe('sre')
  })
  it('returns other', () => {
    expect(normalizedProfile(row({ match_profile: 'other' }))).toBe('other')
  })
  it('trims whitespace', () => {
    expect(normalizedProfile(row({ match_profile: '  de  ' }))).toBe('de')
  })
})

describe('isUpdatedListing', () => {
  it('detects updated on in change_note', () => {
    expect(isUpdatedListing(row({ change_note: 'Updated on 2026-01-01' }))).toBe(true)
  })
  it('returns false when no change_note', () => {
    expect(isUpdatedListing(row({ change_note: '' }))).toBe(false)
  })
})

describe('isNewListing', () => {
  it('returns true when first_seen_at === last_seen_at and no update note', () => {
    expect(isNewListing(row({ first_seen_at: '2026-01-01', last_seen_at: '2026-01-01', change_note: '' }))).toBe(true)
  })
  it('returns false when listing has been updated', () => {
    expect(
      isNewListing(row({ first_seen_at: '2026-01-01', last_seen_at: '2026-01-02', change_note: '' }))
    ).toBe(false)
  })
  it('returns false when change_note says updated', () => {
    expect(
      isNewListing(
        row({ first_seen_at: '2026-01-01', last_seen_at: '2026-01-01', change_note: 'Updated on 2026-01-01' })
      )
    ).toBe(false)
  })
})

describe('filterApplications', () => {
  const rows = [
    row({ id: 1, match_profile: 'de', first_seen_at: '2026-01-01', last_seen_at: '2026-01-01', change_note: '' }),
    row({ id: 2, match_profile: 'swe', first_seen_at: '2026-01-01', last_seen_at: '2026-01-02', change_note: '' }),
    row({ id: 3, match_profile: 'sre', first_seen_at: '2026-01-01', last_seen_at: '2026-01-01', change_note: 'Updated on 2026-01-01' }),
  ]

  it('returns all rows for all/all', () => {
    expect(filterApplications(rows, 'all', 'all')).toHaveLength(3)
  })
  it('filters by profile sre', () => {
    const result = filterApplications(rows, 'sre', 'all')
    expect(result).toHaveLength(1)
    expect(result[0].id).toBe(3)
  })
  it('filters by listing new', () => {
    const result = filterApplications(rows, 'all', 'new')
    expect(result).toHaveLength(1)
    expect(result[0].id).toBe(1)
  })
  it('filters by listing updated', () => {
    const result = filterApplications(rows, 'all', 'updated')
    expect(result).toHaveLength(1)
    expect(result[0].id).toBe(3)
  })
})
