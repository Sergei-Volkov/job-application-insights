import type { RefObject } from 'react'
import type { GenerateDocumentsResult } from '../api'
import type { EditableRow, GeneratedDocsMap } from '../appTypes'
import { getRowDocLinks } from '../utils/docs'

type WorkspaceEditorProps = {
  activeProcessRow: EditableRow | null
  generatedDocsById: GeneratedDocsMap
  activeFilePath: string
  activeFileExt: string
  fileDraft: string
  fileContent: string
  fileLoading: boolean
  fileSaving: boolean
  fileDirty: boolean
  previewHtml: string
  editorSectionRef: RefObject<HTMLElement | null>
  setFileDraft: (draft: string) => void
  setFileDirty: (dirty: boolean) => void
  openProcessFile: (rowId: number, path: string) => Promise<void>
  generateDocsForRow: (row: EditableRow, overwrite?: boolean) => Promise<void>
  saveFile: () => Promise<void>
}

export default function WorkspaceEditor({
  activeProcessRow,
  generatedDocsById,
  activeFilePath,
  activeFileExt,
  fileDraft,
  fileContent,
  fileLoading,
  fileSaving,
  fileDirty,
  previewHtml,
  editorSectionRef,
  setFileDraft,
  setFileDirty,
  openProcessFile,
  generateDocsForRow,
  saveFile,
}: WorkspaceEditorProps) {
  // silence unused import warning — GenerateDocumentsResult used via generatedDocsById type
  void (undefined as unknown as GenerateDocumentsResult)

  return (
    <section className="card editor-card editor-sticky" ref={editorSectionRef as RefObject<HTMLElement>}>
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
                  dangerouslySetInnerHTML={{ __html: previewHtml }}
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
  )
}
