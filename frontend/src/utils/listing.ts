import type { DiscoveryProfile, EditableRow, ListingFilter } from '../appTypes'

export const normalizedProfile = (row: EditableRow): DiscoveryProfile => {
  const value = (row.match_profile || '').trim().toLowerCase()
  if (value === 'swe' || value === 'sre' || value === 'other') return value
  return 'de'
}

export const isUpdatedListing = (row: EditableRow) =>
  (row.change_note || '').toLowerCase().includes('updated on')

export const isNewListing = (row: EditableRow) => {
  const first = (row.first_seen_at || '').trim()
  const last = (row.last_seen_at || '').trim()
  return !!first && first === last && !isUpdatedListing(row)
}

export const filterApplications = (
  rows: EditableRow[],
  profileFilter: 'all' | DiscoveryProfile,
  listingFilter: ListingFilter
) => {
  return rows.filter((row) => {
    const profileOk = profileFilter === 'all' || normalizedProfile(row) === profileFilter
    const listingOk =
      listingFilter === 'all' ||
      (listingFilter === 'updated' && isUpdatedListing(row)) ||
      (listingFilter === 'new' && isNewListing(row))
    return profileOk && listingOk
  })
}
