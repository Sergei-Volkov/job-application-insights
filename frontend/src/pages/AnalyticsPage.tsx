import { useMemo, useState } from 'react'
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
import type { DiscoveryProfile, EditableRow, ListingFilter } from '../appTypes'
import { filterApplications } from '../utils/listing'

type Props = {
  applications: EditableRow[]
}

export default function AnalyticsPage({ applications }: Props) {
  const [profileFilter, setProfileFilter] = useState<'all' | DiscoveryProfile>('all')
  const [listingFilter, setListingFilter] = useState<ListingFilter>('all')

  const filteredApps = useMemo(
    () => filterApplications(applications, profileFilter, listingFilter),
    [applications, profileFilter, listingFilter]
  )

  const statusData = useMemo(() => {
    const byStatus: Record<string, number> = {}
    filteredApps.forEach((row) => {
      const status = row.status || 'To review'
      byStatus[status] = (byStatus[status] || 0) + 1
    })
    return (Object.entries(byStatus) as [string, number][])
      .sort((a, b) => b[1] - a[1])
      .map(([name, count]) => ({ name, count }))
  }, [filteredApps])

  const skillData = useMemo(() => {
    const marker = 'missing or adjacent tools:'
    const found: string[] = []
    filteredApps.forEach((row) => {
      const text = (row.notes || '').trim()
      const lower = text.toLowerCase()
      if (!lower.includes(marker)) return
      const idx = lower.indexOf(marker)
      const raw = text.slice(idx + marker.length)
      raw
        .split(',')
        .map((part) => part.trim().replace(/[.]+$/g, ''))
        .filter(Boolean)
        .forEach((part) => found.push(part))
    })
    if (found.length === 0) return [] as { skill: string; count: number }[]
    const counts: Record<string, number> = {}
    found.forEach((skill) => {
      counts[skill] = (counts[skill] || 0) + 1
    })
    return (Object.entries(counts) as [string, number][])
      .sort((a, b) => b[1] - a[1])
      .map(([skill, count]) => ({ skill, count }))
  }, [filteredApps])

  const trendData = useMemo(() => {
    const weekCounter: Record<string, number> = {}
    const isoWeek = (value: string) => {
      const date = new Date(value)
      if (Number.isNaN(date.getTime())) return ''
      const utcDate = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()))
      const day = utcDate.getUTCDay() || 7
      utcDate.setUTCDate(utcDate.getUTCDate() + 4 - day)
      const yearStart = new Date(Date.UTC(utcDate.getUTCFullYear(), 0, 1))
      const weekNo = Math.ceil((((utcDate.getTime() - yearStart.getTime()) / 86400000) + 1) / 7)
      return `${utcDate.getUTCFullYear()}-W${String(weekNo).padStart(2, '0')}`
    }
    filteredApps.forEach((row) => {
      const week = isoWeek((row.date_found || '').trim())
      if (!week) return
      weekCounter[week] = (weekCounter[week] || 0) + 1
    })
    return (Object.entries(weekCounter) as [string, number][])
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([week, count]) => ({ week, count }))
  }, [filteredApps])

  return (
    <>
      <section className="card">
        <div className="filters-row">
          <label htmlFor="analytics-profile-filter">Match profile</label>
          <select
            id="analytics-profile-filter"
            className="text-input select-input compact-input"
            value={profileFilter}
            onChange={(e) => setProfileFilter(e.target.value as 'all' | DiscoveryProfile)}
          >
            <option value="all">All</option>
            <option value="de">DE</option>
            <option value="swe">SWE</option>
            <option value="sre">SRE</option>
            <option value="other">Other</option>
          </select>
          <label htmlFor="analytics-listing-filter">Listing</label>
          <select
            id="analytics-listing-filter"
            className="text-input select-input compact-input"
            value={listingFilter}
            onChange={(e) => setListingFilter(e.target.value as ListingFilter)}
          >
            <option value="all">All</option>
            <option value="new">New</option>
            <option value="updated">Updated</option>
          </select>
        </div>
      </section>
      <section className="grid top-grid">
        <div className="card stat-card">
          <h2>Total Applications</h2>
          <p className="metric">{filteredApps.length}</p>
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
          {skillData.length === 0 ? (
            <p className="empty-state">No missing-skill markers in filtered rows.</p>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart
                data={skillData}
                layout="vertical"
                margin={{ top: 4, right: 16, left: 0, bottom: 0 }}
              >
                <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="skill" width={90} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="count" fill="#0369a1" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="card chart-card">
          <h2>Weekly Trend</h2>
          {trendData.length === 0 ? (
            <p className="empty-state">No dated applications yet.</p>
          ) : (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={trendData} margin={{ top: 4, right: 16, left: -16, bottom: 0 }}>
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
    </>
  )
}
