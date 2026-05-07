import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  fetchApplications,
  fetchSkills,
  runDiscovery,
  fetchStats,
  fetchTrend,
  updateApplication,
  type DiscoveryRunResult,
  type ApplicationItem,
  type SkillItem,
  type Stats,
  type TrendItem,
} from './api'
import './App.css'

type EditableRow = ApplicationItem & {
  saving?: boolean
}

export default function App() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [skills, setSkills] = useState<SkillItem[]>([])
  const [trend, setTrend] = useState<TrendItem[]>([])
  const [applications, setApplications] = useState<EditableRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [discovering, setDiscovering] = useState(false)
  const [discoveryResult, setDiscoveryResult] = useState<DiscoveryRunResult | null>(null)

  const loadDashboard = () => {
    setError(null)
    Promise.all([fetchStats(), fetchSkills(), fetchTrend(), fetchApplications(30)])
      .then(([s, sk, t, a]) => {
        setStats(s)
        setSkills(sk)
        setTrend(t)
        setApplications(a)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load data'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    loadDashboard()
  }, [])

  const statusData = stats
    ? (Object.entries(stats.by_status) as [string, number][])
        .sort((a, b) => b[1] - a[1])
        .map(([name, count]) => ({ name, count }))
    : []

  const patchLocal = (id: number, patch: Partial<EditableRow>) => {
    setApplications((prev: EditableRow[]) =>
      prev.map((row: EditableRow) => (row.id === id ? { ...row, ...patch } : row))
    )
  }

  const saveRow = async (row: EditableRow) => {
    patchLocal(row.id, { saving: true })
    try {
      const updated = await updateApplication(row.id, {
        selected: row.selected,
        date_applied: row.date_applied,
        status: row.status,
        next_step: row.next_step,
        follow_up_date: row.follow_up_date,
        resume_ref: row.resume_ref,
        cover_letter_ref: row.cover_letter_ref,
        notes: row.notes,
      })
      patchLocal(row.id, { ...updated, saving: false })
    } catch (e) {
      patchLocal(row.id, { saving: false })
      setError(e instanceof Error ? e.message : 'Failed to save application')
    }
  }

  const triggerDiscovery = async () => {
    setDiscovering(true)
    setError(null)
    try {
      const result = await runDiscovery({ limit: 40, min_score: 7, max_age_days: 45 })
      setDiscoveryResult(result)
      setLoading(true)
      loadDashboard()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to run discovery')
    } finally {
      setDiscovering(false)
    }
  }

  return (
    <div className="container">
      <header>
        <h1>Job Application Insights</h1>
        <p className="subtitle">FastAPI · SQLAlchemy · React · TypeScript</p>
        <div className="toolbar">
          <button className="save-btn" disabled={discovering} onClick={() => void triggerDiscovery()}>
            {discovering ? 'Running discovery...' : 'Run discovery'}
          </button>
        </div>
      </header>

      {error && <div className="error-banner">{error}</div>}
      {discoveryResult && (
        <div className="result-banner">
          <strong>Discovery exit code:</strong> {discoveryResult.exit_code}
          {discoveryResult.stdout && <pre>{discoveryResult.stdout}</pre>}
          {discoveryResult.stderr && <pre>{discoveryResult.stderr}</pre>}
        </div>
      )}

      {loading ? (
        <p className="empty-state">Loading…</p>
      ) : (
        <>
          <section className="grid top-grid">
            <div className="card stat-card">
              <h2>Total Applications</h2>
              <p className="metric">{stats?.total_applications ?? '—'}</p>
            </div>

            <div className="card chart-card">
              <h2>By Status</h2>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={statusData} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#0f766e" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section className="grid bottom-grid">
            <div className="card chart-card">
              <h2>Skill Gaps</h2>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart
                  data={skills}
                  layout="vertical"
                  margin={{ top: 4, right: 16, left: 0, bottom: 0 }}
                >
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
                  <YAxis type="category" dataKey="skill" width={90} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#0369a1" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="card chart-card">
              <h2>Weekly Trend</h2>
              {trend.length === 0 ? (
                <p className="empty-state">No dated applications yet.</p>
              ) : (
                <ResponsiveContainer width="100%" height={240}>
                  <LineChart data={trend} margin={{ top: 4, right: 16, left: -16, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="week" tick={{ fontSize: 10 }} />
                    <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Line
                      type="monotone"
                      dataKey="count"
                      stroke="#0f766e"
                      strokeWidth={2}
                      dot={{ r: 4 }}
                      activeDot={{ r: 6 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </div>
          </section>

          <section className="card applications-card">
            <h2>Application Tracker</h2>
            <p className="subtitle small">Edit status, next step, follow-up date, and resume/cover references per role.</p>

            <div className="table-wrap">
              <table className="apps-table">
                <thead>
                  <tr>
                    <th>Applied</th>
                    <th>Company / Role</th>
                    <th>Status</th>
                    <th>Next Step</th>
                    <th>Follow-up</th>
                    <th>Resume Ref</th>
                    <th>Cover Letter Ref</th>
                    <th>Save</th>
                  </tr>
                </thead>
                <tbody>
                  {applications.map((row) => (
                    <tr key={row.id}>
                      <td>
                        <input
                          type="checkbox"
                          checked={row.selected.toLowerCase() === 'yes'}
                          onChange={(e) =>
                            patchLocal(row.id, {
                              selected: e.target.checked ? 'yes' : 'no',
                              date_applied: e.target.checked
                                ? new Date().toISOString().slice(0, 10)
                                : '',
                              status: e.target.checked ? 'Applied' : row.status,
                            })
                          }
                        />
                      </td>
                      <td>
                        <div className="role-cell">
                          <strong>{row.company}</strong>
                          <span>{row.role}</span>
                        </div>
                      </td>
                      <td>
                        <select
                          className="text-input select-input"
                          value={row.status || 'To review'}
                          onChange={(e) => patchLocal(row.id, { status: e.target.value })}
                        >
                          <option>To review</option>
                          <option>Applied</option>
                          <option>Interview</option>
                          <option>Offer</option>
                          <option>Rejected</option>
                          <option>Saved</option>
                        </select>
                      </td>
                      <td>
                        <input
                          className="text-input"
                          value={row.next_step || ''}
                          onChange={(e) => patchLocal(row.id, { next_step: e.target.value })}
                          placeholder="Tailor CV and apply soon"
                        />
                      </td>
                      <td>
                        <input
                          className="text-input date-input"
                          type="date"
                          value={row.follow_up_date || ''}
                          onChange={(e) => patchLocal(row.id, { follow_up_date: e.target.value })}
                        />
                      </td>
                      <td>
                        <input
                          className="text-input"
                          value={row.resume_ref || ''}
                          onChange={(e) => patchLocal(row.id, { resume_ref: e.target.value })}
                          placeholder="resume_v2.pdf"
                        />
                      </td>
                      <td>
                        <input
                          className="text-input"
                          value={row.cover_letter_ref || ''}
                          onChange={(e) => patchLocal(row.id, { cover_letter_ref: e.target.value })}
                          placeholder="vacancies/.../cover_letter.md"
                        />
                      </td>
                      <td>
                        <button
                          className="save-btn"
                          disabled={!!row.saving}
                          onClick={() => {
                            void saveRow(row)
                          }}
                        >
                          {row.saving ? 'Saving...' : 'Save'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
