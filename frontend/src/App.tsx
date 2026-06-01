import { Component, useEffect, useState } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { fetchApplications } from './api'
import type { AppPage, EditableRow } from './appTypes'
import AnalyticsPage from './pages/AnalyticsPage'
import DiscoveryPage from './pages/DiscoveryPage'
import TrackerPage from './pages/TrackerPage'
import './App.css'

// ── Error boundary ────────────────────────────────────────────────────────────

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  constructor(props: { children: ReactNode }) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Unhandled render error:', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="error-banner" style={{ margin: '2rem', padding: '1.5rem' }}>
          <strong>Something went wrong.</strong>{' '}
          <span>{this.state.error.message}</span>
          <br />
          <button
            className="secondary-btn"
            style={{ marginTop: '1rem' }}
            onClick={() => this.setState({ error: null })}
          >
            Try again
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

export default function App() {
  const [applications, setApplications] = useState<EditableRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [activePage, setActivePage] = useState<AppPage>(() => {
    const saved = localStorage.getItem('activePage')
    return (saved as AppPage) || 'pipeline'
  })

  const loadDashboard = (): Promise<void> => {
    setError(null)
    return fetchApplications()
      .then((res) => setApplications(res.items))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load data'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    void loadDashboard()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    localStorage.setItem('activePage', activePage)
  }, [activePage])

  // Auto-clear success messages after 8 s
  useEffect(() => {
    if (!successMessage) return
    const t = setTimeout(() => setSuccessMessage(null), 8000)
    return () => clearTimeout(t)
  }, [successMessage])

  return (
    <div className="container">
      <header>
        <div>
          <h1>Job Application Insights</h1>
          <p className="subtitle">FastAPI · SQLAlchemy · React · TypeScript</p>
        </div>
        <nav className="view-tabs" aria-label="Main views">
          <button
            className={`tab-btn${activePage === 'pipeline' ? ' active' : ''}`}
            onClick={() => setActivePage('pipeline')}
          >
            Tracker
          </button>
          <button
            className={`tab-btn${activePage === 'analytics' ? ' active' : ''}`}
            onClick={() => setActivePage('analytics')}
          >
            Analytics
          </button>
          <button
            className={`tab-btn${activePage === 'discovery' ? ' active' : ''}`}
            onClick={() => setActivePage('discovery')}
          >
            Discovery
          </button>
        </nav>
      </header>

      {error && <div className="error-banner">{error}</div>}
      {successMessage && <div className="success-banner">{successMessage}</div>}

      {loading ? (
        <p className="empty-state">Loading…</p>
      ) : (
        <ErrorBoundary>
          {activePage === 'analytics' && (
            <AnalyticsPage applications={applications} />
          )}

          {activePage === 'discovery' && (
            <DiscoveryPage
              setError={setError}
              setSuccessMessage={setSuccessMessage}
              setLoading={setLoading}
              onRunComplete={loadDashboard}
            />
          )}

          {activePage === 'pipeline' && (
            <TrackerPage
              applications={applications}
              setApplications={setApplications}
              setError={setError}
              setSuccessMessage={setSuccessMessage}
            />
          )}
        </ErrorBoundary>
      )}
    </div>
  )
}
