import { describe, it, expect } from 'vitest'
import { renderMarkdownPreview } from './preview'

describe('renderMarkdownPreview', () => {
  it('returns empty placeholder for empty input', () => {
    expect(renderMarkdownPreview('')).toContain('preview-empty')
  })

  it('renders h1 heading', () => {
    expect(renderMarkdownPreview('# Hello')).toBe('<h1>Hello</h1>')
  })

  it('renders h3 heading', () => {
    expect(renderMarkdownPreview('### Section')).toBe('<h3>Section</h3>')
  })

  it('wraps bullet list items in ul', () => {
    const html = renderMarkdownPreview('- Apple\n- Banana')
    expect(html).toContain('<ul>')
    expect(html).toContain('<li>Apple</li>')
    expect(html).toContain('<li>Banana</li>')
    expect(html).toContain('</ul>')
  })

  it('renders inline bold', () => {
    const html = renderMarkdownPreview('This is **bold** text.')
    expect(html).toContain('<strong>bold</strong>')
  })

  it('renders inline code', () => {
    const html = renderMarkdownPreview('Use `python` here.')
    expect(html).toContain('<code>python</code>')
  })

  it('renders inline link', () => {
    const html = renderMarkdownPreview('[click](https://example.com)')
    expect(html).toContain('<a href="https://example.com"')
    expect(html).toContain('click')
  })

  it('escapes HTML special characters', () => {
    const html = renderMarkdownPreview('<script>alert("xss")</script>')
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
  })

  it('renders fenced code block', () => {
    const src = '```\nconst x = 1\n```'
    const html = renderMarkdownPreview(src)
    expect(html).toContain('<pre><code>')
    expect(html).toContain('const x = 1')
    expect(html).toContain('</code></pre>')
  })

  it('handles CRLF line endings', () => {
    const html = renderMarkdownPreview('# Title\r\n\r\nParagraph.')
    expect(html).toContain('<h1>Title</h1>')
    expect(html).toContain('Paragraph.')
  })

  it('closes unclosed list at end of input', () => {
    const html = renderMarkdownPreview('- Item A')
    expect(html).toContain('</ul>')
  })
})
