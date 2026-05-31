const escapeHtml = (value: string) =>
  value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/\"/g, '&quot;')
    .replace(/'/g, '&#39;')

export const renderMarkdownPreview = (source: string) => {
  if (!source.trim()) return '<p class="preview-empty">No preview content.</p>'
  const lines = source.replace(/\r\n/g, '\n').split('\n')
  const chunks: string[] = []
  let inList = false
  let inCode = false

  for (const rawLine of lines) {
    const line = rawLine

    if (line.trim().startsWith('```')) {
      if (inCode) {
        chunks.push('</code></pre>')
      } else {
        chunks.push('<pre><code>')
      }
      inCode = !inCode
      continue
    }

    if (inCode) {
      chunks.push(`${escapeHtml(line)}\n`)
      continue
    }

    const heading = line.match(/^(#{1,6})\s+(.*)$/)
    if (heading) {
      if (inList) {
        chunks.push('</ul>')
        inList = false
      }
      const level = heading[1].length
      chunks.push(`<h${level}>${escapeHtml(heading[2])}</h${level}>`)
      continue
    }

    const bullet = line.match(/^\s*[-*+]\s+(.*)$/)
    if (bullet) {
      if (!inList) {
        chunks.push('<ul>')
        inList = true
      }
      chunks.push(`<li>${escapeHtml(bullet[1])}</li>`)
      continue
    }

    if (inList) {
      chunks.push('</ul>')
      inList = false
    }

    if (!line.trim()) {
      chunks.push('<div class="preview-paragraph spacer"></div>')
      continue
    }

    const inline = escapeHtml(line)
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/__(.+?)__/g, '<strong>$1</strong>')
      .replace(/(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)/g, '<em>$1</em>')
      .replace(/_(.+?)_/g, '<em>$1</em>')
      .replace(/`(.+?)`/g, '<code>$1</code>')
      .replace(/\[(.+?)\]\((https?:\/\/.+?)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')

    chunks.push(`<p class="preview-paragraph">${inline}</p>`)
  }

  if (inList) chunks.push('</ul>')
  if (inCode) chunks.push('</code></pre>')

  return chunks.join('\n') || '<p class="preview-empty">No preview content.</p>'
}

export const renderTexPreview = (source: string) => {
  const normalized = source.replace(/\r\n/g, '\n')
  const lines = normalized.split('\n')
  const chunks: string[] = []
  let inList = false

  const flushList = () => {
    if (inList) {
      chunks.push('</ul>')
      inList = false
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trim()
    if (!line) {
      flushList()
      chunks.push('<div class="preview-paragraph spacer"></div>')
      continue
    }

    const section = line.match(/^\\(sub)*section\{(.+?)\}/)
    if (section) {
      flushList()
      const level = line.startsWith('\\subsection') ? 3 : 2
      chunks.push(`<h${level}>${escapeHtml(section[2])}</h${level}>`)
      continue
    }

    if (line.startsWith('\\begin{itemize}')) {
      flushList()
      chunks.push('<ul>')
      inList = true
      continue
    }

    if (line.startsWith('\\end{itemize}')) {
      flushList()
      continue
    }

    const item = line.match(/^\\item\s*(.*)$/)
    if (item) {
      if (!inList) {
        chunks.push('<ul>')
        inList = true
      }
      chunks.push(`<li>${escapeHtml(item[1])}</li>`)
      continue
    }

    const cleaned = escapeHtml(line)
      .replace(/\\textbf\{(.+?)\}/g, '<strong>$1</strong>')
      .replace(/\\textit\{(.+?)\}/g, '<em>$1</em>')
      .replace(/\\href\{(.+?)\}\{(.+?)\}/g, '<a href="$1" target="_blank" rel="noreferrer">$2</a>')
      .replace(/\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})?/g, '')

    chunks.push(`<p class="preview-paragraph">${cleaned}</p>`)
  }

  flushList()
  return chunks.join('\n') || '<p class="preview-empty">No preview content.</p>'
}
