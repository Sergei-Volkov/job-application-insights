import { describe, it, expect } from 'vitest'
import { getRowDocLinks } from './docs'
import type { EditableRow } from '../appTypes'

const row = (overrides: Partial<EditableRow> = {}): EditableRow =>
  ({
    id: 1,
    company: 'Acme',
    role: 'Engineer',
    link: 'https://example.com',
    status: 'To review',
    cover_letter_ref: '',
    resume_ref: '',
    ...overrides,
  } as EditableRow)

describe('getRowDocLinks', () => {
  it('returns generated links when present in generatedDocsById', () => {
    const generated = {
      1: {
        vacancy_path: 'v/vacancy.md',
        notes_path: 'v/notes.md',
        cover_letter_path: 'v/cover_letter.md',
        cv_path: 'v/cv.tex',
      },
    }
    const result = getRowDocLinks(row(), generated as any)
    expect(result.vacancyPath).toBe('v/vacancy.md')
    expect(result.coverLetterPath).toBe('v/cover_letter.md')
    expect(result.cvPath).toBe('v/cv.tex')
  })

  it('derives sibling paths from cover_letter_ref', () => {
    const r = row({ cover_letter_ref: 'applications/vacancies/acme_engineer/cover_letter.md' })
    const result = getRowDocLinks(r, {})
    expect(result.vacancyPath).toBe('applications/vacancies/acme_engineer/vacancy.md')
    expect(result.notesPath).toBe('applications/vacancies/acme_engineer/notes.md')
    expect(result.cvPath).toBe('applications/vacancies/acme_engineer/cv.tex')
  })

  it('derives sibling paths from resume_ref when cover_letter_ref is empty', () => {
    const r = row({ resume_ref: 'applications/vacancies/acme_engineer/cv.tex' })
    const result = getRowDocLinks(r, {})
    expect(result.vacancyPath).toBe('applications/vacancies/acme_engineer/vacancy.md')
    expect(result.coverLetterPath).toBe('applications/vacancies/acme_engineer/cover_letter.md')
  })

  it('normalises backslashes from Windows paths', () => {
    const r = row({ cover_letter_ref: 'applications\\vacancies\\acme_engineer\\cover_letter.md' })
    const result = getRowDocLinks(r, {})
    expect(result.vacancyPath).toBe('applications/vacancies/acme_engineer/vacancy.md')
  })

  it('returns only the refs when path suffix is unrecognised', () => {
    const r = row({ cover_letter_ref: 'some/random/path.txt' })
    const result = getRowDocLinks(r, {})
    expect(result.vacancyPath).toBeUndefined()
    expect(result.coverLetterPath).toBe('some/random/path.txt')
  })

  it('returns empty links when no refs and no generated docs', () => {
    const result = getRowDocLinks(row(), {})
    expect(result.coverLetterPath).toBeUndefined()
    expect(result.cvPath).toBeUndefined()
  })
})
