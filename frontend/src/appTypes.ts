import type { ApplicationItem, GenerateDocumentsResult } from './api'

export type EditableRow = ApplicationItem & {
  saving?: boolean
  generating?: boolean
  rowError?: string | null
}

export type DiscoveryProfile = 'de' | 'swe' | 'sre' | 'other'

export type ListingFilter = 'all' | 'updated' | 'new'

export type GeneratedDocsMap = Record<number, GenerateDocumentsResult>

export type RowDocLinks = {
  vacancyPath?: string
  notesPath?: string
  coverLetterPath?: string
  cvPath?: string
}

export type AppPage = 'pipeline' | 'analytics' | 'discovery'
