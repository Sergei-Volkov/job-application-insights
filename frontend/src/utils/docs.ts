import type { GeneratedDocsMap, RowDocLinks, EditableRow } from '../appTypes'

export const getRowDocLinks = (row: EditableRow, generatedDocsById: GeneratedDocsMap): RowDocLinks => {
  const generated = generatedDocsById[row.id]
  if (generated) {
    return {
      vacancyPath: generated.vacancy_path,
      notesPath: generated.notes_path,
      coverLetterPath: generated.cover_letter_path,
      cvPath: generated.cv_path,
    }
  }

  const cover = (row.cover_letter_ref || '').replace(/\\/g, '/')
  const cv = (row.resume_ref || '').replace(/\\/g, '/')
  const candidate = cover || cv
  if (!candidate) {
    return {
      coverLetterPath: cover || undefined,
      cvPath: cv || undefined,
    }
  }

  const coverSuffix = '/cover_letter.md'
  const cvSuffix = '/cv.tex'
  let baseDir = ''

  if (candidate.endsWith(coverSuffix)) {
    baseDir = candidate.slice(0, -coverSuffix.length)
  } else if (candidate.endsWith(cvSuffix)) {
    baseDir = candidate.slice(0, -cvSuffix.length)
  }

  if (!baseDir) {
    return {
      coverLetterPath: cover || undefined,
      cvPath: cv || undefined,
    }
  }

  return {
    vacancyPath: `${baseDir}/vacancy.md`,
    notesPath: `${baseDir}/notes.md`,
    coverLetterPath: cover || `${baseDir}/cover_letter.md`,
    cvPath: cv || `${baseDir}/cv.tex`,
  }
}
