import { useEffect, useMemo, useRef, useState } from 'react'
import { runDiscovery, fetchDiscoveryStatus, upsertApplication } from '../api'
import type { DiscoveryRunResult, DiscoveryStatus } from '../api'
import { DISCOVERY_SOURCES, SCORE_STRONG_MIN, SCORE_MEDIUM_MIN } from '../appConstants'
import type { DiscoveryProfile } from '../appTypes'

const DEFAULT_DISCOVERY_PARAMS = {
  limit: 40,
  min_score: 7,
  max_age_days: 45,
  include_stretch: false,
  salary_min_usd: '',
  timezones: '',
  seniority: '',
  use_outcome_priors: false,
  prior_lookback_days: 365,
  source_prior_weight: 1,
  role_prior_weight: 1,
  use_llm_reranker: false,
  llm_top_n: 20,
  llm_weight: 1,
  llm_model: '',
  llm_api_base_url: '',
  llm_dry_run: false,
  llm_max_calls: 20,
  llm_max_input_chars: 50000,
  llm_max_retries: 2,
  llm_retry_backoff_seconds: 0.5,
  llm_timeout_seconds: 20,
  output_dir: '',
}

type LlmDryRunDiagnostics = {
  dryRun: boolean
  plannedCalls: number | null
  attempted: number | null
  adjusted: number | null
  usedInputChars: number | null
  warningsCount: number | null
}

type DiscoveryPageProps = {
  setError: (msg: string | null) => void
  setSuccessMessage: (msg: string | null) => void
  setLoading: (loading: boolean) => void
  onRunComplete: () => Promise<void>
}

export default function DiscoveryPage({ setError, setSuccessMessage, setLoading, onRunComplete }: DiscoveryPageProps) {
  const [discoveryProfile, setDiscoveryProfile] = useState<DiscoveryProfile>('de')
  const [discoveryParams, setDiscoveryParams] = useState<typeof DEFAULT_DISCOVERY_PARAMS>(() => {
    try {
      const saved = localStorage.getItem('discoveryParams')
      if (saved) return { ...DEFAULT_DISCOVERY_PARAMS, ...(JSON.parse(saved) as typeof DEFAULT_DISCOVERY_PARAMS) }
    } catch {}
    return DEFAULT_DISCOVERY_PARAMS
  })
  const [discoveryCvPath, setDiscoveryCvPath] = useState<string>(() => localStorage.getItem('discoveryCvPath') || '')
  const [discoveryApiBaseUrl, setDiscoveryApiBaseUrl] = useState<string>(
    () => localStorage.getItem('discoveryApiBaseUrl') || ''
  )
  const [discoveryVerbose, setDiscoveryVerbose] = useState<boolean>(() => localStorage.getItem('discoveryVerbose') === 'true')
  const [discoverySourceSelection, setDiscoverySourceSelection] = useState<Record<string, boolean>>(
    () => Object.fromEntries(DISCOVERY_SOURCES.map((source) => [source.key, true]))
  )
  const [discovering, setDiscovering] = useState(false)
  const [discoveryStatus, setDiscoveryStatus] = useState<DiscoveryStatus | null>(null)
  const [discoveryResult, setDiscoveryResult] = useState<DiscoveryRunResult | null>(null)
  const [cooldownSecsLeft, setCooldownSecsLeft] = useState(0)
  const [manualJobForm, setManualJobForm] = useState({ company: '', role: '', link: '', description: '' })
  const discoveryPollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => { localStorage.setItem('discoveryCvPath', discoveryCvPath) }, [discoveryCvPath])
  useEffect(() => { localStorage.setItem('discoveryApiBaseUrl', discoveryApiBaseUrl) }, [discoveryApiBaseUrl])
  useEffect(() => { localStorage.setItem('discoveryVerbose', discoveryVerbose ? 'true' : 'false') }, [discoveryVerbose])
  useEffect(() => { localStorage.setItem('discoveryParams', JSON.stringify(discoveryParams)) }, [discoveryParams])

  useEffect(() => {
    if (cooldownSecsLeft <= 0) return
    const t = setTimeout(() => setCooldownSecsLeft((s) => Math.max(0, s - 1)), 1000)
    return () => clearTimeout(t)
  }, [cooldownSecsLeft])

  useEffect(() => {
    if (!discovering) {
      if (discoveryPollRef.current !== null) {
        clearInterval(discoveryPollRef.current)
        discoveryPollRef.current = null
      }
      return
    }

    const poll = async () => {
      try {
        const status = await fetchDiscoveryStatus()
        setDiscoveryStatus(status)
        if (!status.in_flight) {
          setLoading(true)
          void onRunComplete()
        }
      } catch {
        // Swallow poll errors silently; triggerDiscovery error path handles failures
      }
    }

    void poll()
    discoveryPollRef.current = setInterval(() => void poll(), 5000)
    return () => {
      if (discoveryPollRef.current !== null) {
        clearInterval(discoveryPollRef.current)
        discoveryPollRef.current = null
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [discovering])

  const llmDryRunDiagnostics = useMemo<LlmDryRunDiagnostics | null>(() => {
    const output = discoveryResult?.stdout || ''
    if (!output.trim()) return null

    const parseLineValue = (key: string): string | null => {
      const line = output
        .split('\n')
        .map((part) => part.trim())
        .find((part) => part.startsWith(`- ${key}=`))
      if (!line) return null
      return line.slice(`- ${key}=`.length).trim()
    }

    const dryRunRaw = parseLineValue('llm_dry_run')
    if (!dryRunRaw) return null

    const toNumber = (value: string | null): number | null => {
      if (!value) return null
      const parsed = parseInt(value, 10)
      return Number.isNaN(parsed) ? null : parsed
    }

    return {
      dryRun: dryRunRaw.toLowerCase() === 'true',
      plannedCalls: toNumber(parseLineValue('llm_planned_calls')),
      attempted: toNumber(parseLineValue('llm_attempted')),
      adjusted: toNumber(parseLineValue('llm_adjusted')),
      usedInputChars: toNumber(parseLineValue('llm_used_input_chars')),
      warningsCount: toNumber(parseLineValue('llm_warnings')),
    }
  }, [discoveryResult])

  const triggerDiscovery = async () => {
    setDiscovering(true)
    setDiscoveryStatus(null)
    setError(null)
    try {
      const salaryMinUsd = discoveryParams.salary_min_usd.trim()
      const timezoneTokens = discoveryParams.timezones
        .split(',')
        .map((part) => part.trim())
        .filter(Boolean)
      const seniority = discoveryParams.seniority.trim() as '' | 'junior' | 'mid' | 'senior'
      const outputDir = discoveryParams.output_dir.trim()
      const llmModel = discoveryParams.llm_model.trim()
      const llmApiBaseUrl = discoveryParams.llm_api_base_url.trim()
      const selectedSources = DISCOVERY_SOURCES.map((source) => source.key).filter(
        (sourceKey) => discoverySourceSelection[sourceKey]
      )
      const result = await runDiscovery({
        limit: discoveryParams.limit,
        min_score: discoveryParams.min_score,
        max_age_days: discoveryParams.max_age_days,
        include_stretch: discoveryParams.include_stretch,
        profile: discoveryProfile,
        salary_min_usd: salaryMinUsd ? parseInt(salaryMinUsd, 10) || undefined : undefined,
        timezones: timezoneTokens.length > 0 ? timezoneTokens : undefined,
        seniority: seniority || undefined,
        use_outcome_priors: discoveryParams.use_outcome_priors,
        prior_lookback_days: discoveryParams.prior_lookback_days,
        source_prior_weight: discoveryParams.source_prior_weight,
        role_prior_weight: discoveryParams.role_prior_weight,
        use_llm_reranker: discoveryParams.use_llm_reranker,
        llm_top_n: discoveryParams.llm_top_n,
        llm_weight: discoveryParams.llm_weight,
        llm_model: llmModel || undefined,
        llm_api_base_url: llmApiBaseUrl || undefined,
        llm_dry_run: discoveryParams.llm_dry_run,
        llm_max_calls: discoveryParams.llm_max_calls,
        llm_max_input_chars: discoveryParams.llm_max_input_chars,
        llm_max_retries: discoveryParams.llm_max_retries,
        llm_retry_backoff_seconds: discoveryParams.llm_retry_backoff_seconds,
        llm_timeout_seconds: discoveryParams.llm_timeout_seconds,
        output_dir: outputDir || undefined,
        cv_path: discoveryCvPath.trim() || undefined,
        api_base_url: discoveryApiBaseUrl.trim() || undefined,
        verbose: discoveryVerbose,
        sources: selectedSources,
      })
      setDiscoveryResult(result)
      setLoading(true)
      await onRunComplete()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to run discovery')
    } finally {
      setDiscovering(false)
      setCooldownSecsLeft(30)
    }
  }

  return (
    <>
      <section className="card">
        <h2>Discovery</h2>
        <p className="subtitle small">Run job discovery or add jobs manually.</p>
        <div className="toolbar">
          <label className="toolbar-label" htmlFor="discovery-profile">
            Profile
          </label>
          <select
            id="discovery-profile"
            className="text-input select-input compact-input"
            value={discoveryProfile}
            onChange={(e) => setDiscoveryProfile(e.target.value as DiscoveryProfile)}
          >
            <option value="de">DE</option>
            <option value="swe">SWE</option>
            <option value="sre">SRE</option>
            <option value="other">Other</option>
          </select>
          <label className="toolbar-label" htmlFor="discovery-limit">
            Limit
          </label>
          <input
            id="discovery-limit"
            className="text-input compact-input"
            type="number"
            value={discoveryParams.limit}
            onChange={(e) => setDiscoveryParams({ ...discoveryParams, limit: parseInt(e.target.value) || 40 })}
            min="1"
          />
          <label className="toolbar-label" htmlFor="discovery-min-score">
            Min score
          </label>
          <input
            id="discovery-min-score"
            className="text-input compact-input"
            type="number"
            value={discoveryParams.min_score}
            onChange={(e) => setDiscoveryParams({ ...discoveryParams, min_score: parseInt(e.target.value) || 7 })}
            min="1"
          />
        </div>
        <p className="subtitle small" style={{ marginTop: '8px', marginBottom: '8px' }}>
          Score ranges: Strong {`>= ${SCORE_STRONG_MIN}`}, Medium {`${SCORE_MEDIUM_MIN}-${SCORE_STRONG_MIN - 1}`}, Stretch {`<= ${SCORE_MEDIUM_MIN - 1}`}
        </p>
        <div className="toolbar" style={{ marginTop: '8px' }}>
          <label className="toolbar-label" htmlFor="discovery-cv-path">
            CV path
          </label>
          <input
            id="discovery-cv-path"
            className="text-input"
            type="text"
            placeholder="applications/resumes/CV.tex"
            value={discoveryCvPath}
            onChange={(e) => setDiscoveryCvPath(e.target.value)}
            style={{ minWidth: '260px', flex: 1 }}
            title="CV path used for discovery scoring. Accepts workspace-relative or absolute paths."
          />
        </div>
        <p className="subtitle small" style={{ marginTop: '8px', marginBottom: '8px' }}>
          CV path is a per-run input. If empty, backend uses DISCOVERY_CV_PATH fallback from .env.
        </p>
        <details className="details-panel" style={{ marginTop: '8px' }}>
          <summary className="muted-mini">Advanced discovery params</summary>
          <div className="toolbar" style={{ marginTop: '8px' }}>
            <label className="toolbar-label" htmlFor="discovery-api-base-url">
              API base URL
            </label>
            <input
              id="discovery-api-base-url"
              className="text-input"
              type="text"
              placeholder="http://127.0.0.1:8000"
              value={discoveryApiBaseUrl}
              onChange={(e) => setDiscoveryApiBaseUrl(e.target.value)}
              style={{ minWidth: '240px', flex: 1 }}
              title="Optional override passed to discovery CLI --api-base-url."
            />
            <label className="toolbar-label" title="Enable verbose source diagnostics in discovery output.">
              <input
                type="checkbox"
                checked={discoveryVerbose}
                onChange={(e) => setDiscoveryVerbose(e.target.checked)}
                style={{ marginRight: '4px' }}
              />
              Verbose logs
            </label>
          </div>
          <div className="toolbar" style={{ marginTop: '8px' }}>
            <label className="toolbar-label" htmlFor="discovery-salary-min-usd">
              Min salary (USD)
            </label>
            <input
              id="discovery-salary-min-usd"
              className="text-input compact-input"
              type="number"
              min="0"
              placeholder="optional"
              value={discoveryParams.salary_min_usd}
              onChange={(e) => setDiscoveryParams({ ...discoveryParams, salary_min_usd: e.target.value })}
            />
            <label className="toolbar-label" htmlFor="discovery-seniority">
              Seniority
            </label>
            <select
              id="discovery-seniority"
              className="text-input select-input compact-input"
              value={discoveryParams.seniority}
              onChange={(e) => setDiscoveryParams({ ...discoveryParams, seniority: e.target.value })}
            >
              <option value="">Any</option>
              <option value="junior">Junior+</option>
              <option value="mid">Mid+</option>
              <option value="senior">Senior</option>
            </select>
          </div>
          <div className="toolbar" style={{ marginTop: '8px' }}>
            <label className="toolbar-label" htmlFor="discovery-timezones">
              Timezones
            </label>
            <input
              id="discovery-timezones"
              className="text-input"
              type="text"
              placeholder="UTC,CET,EMEA"
              value={discoveryParams.timezones}
              onChange={(e) => setDiscoveryParams({ ...discoveryParams, timezones: e.target.value })}
              style={{ minWidth: '200px', flex: 1 }}
            />
            <label className="toolbar-label" htmlFor="discovery-output-dir">
              Output dir
            </label>
            <input
              id="discovery-output-dir"
              className="text-input"
              type="text"
              placeholder="applications/tracker"
              value={discoveryParams.output_dir}
              onChange={(e) => setDiscoveryParams({ ...discoveryParams, output_dir: e.target.value })}
              style={{ minWidth: '200px', flex: 1 }}
            />
          </div>
          <div className="toolbar" style={{ marginTop: '8px' }}>
            <label className="toolbar-label" title="Re-rank by historical outcome of source and role family.">
              <input
                type="checkbox"
                checked={discoveryParams.use_outcome_priors}
                onChange={(e) => setDiscoveryParams({ ...discoveryParams, use_outcome_priors: e.target.checked })}
                style={{ marginRight: '4px' }}
              />
              Use outcome priors
            </label>
            <label className="toolbar-label" htmlFor="discovery-prior-lookback-days">
              Prior lookback
            </label>
            <input
              id="discovery-prior-lookback-days"
              className="text-input compact-input"
              type="number"
              min="1"
              value={discoveryParams.prior_lookback_days}
              onChange={(e) => setDiscoveryParams({ ...discoveryParams, prior_lookback_days: parseInt(e.target.value, 10) || 365 })}
              disabled={!discoveryParams.use_outcome_priors}
            />
            <label className="toolbar-label" htmlFor="discovery-source-prior-weight">
              Source weight
            </label>
            <input
              id="discovery-source-prior-weight"
              className="text-input compact-input"
              type="number"
              step="0.1"
              value={discoveryParams.source_prior_weight}
              onChange={(e) => setDiscoveryParams({ ...discoveryParams, source_prior_weight: parseFloat(e.target.value) || 1 })}
              disabled={!discoveryParams.use_outcome_priors}
            />
            <label className="toolbar-label" htmlFor="discovery-role-prior-weight">
              Role weight
            </label>
            <input
              id="discovery-role-prior-weight"
              className="text-input compact-input"
              type="number"
              step="0.1"
              value={discoveryParams.role_prior_weight}
              onChange={(e) => setDiscoveryParams({ ...discoveryParams, role_prior_weight: parseFloat(e.target.value) || 1 })}
              disabled={!discoveryParams.use_outcome_priors}
            />
          </div>
          <div className="toolbar" style={{ marginTop: '8px' }}>
            <label className="toolbar-label" title="Use LLM to conservatively adjust score for top candidates.">
              <input
                type="checkbox"
                checked={discoveryParams.use_llm_reranker}
                onChange={(e) => setDiscoveryParams({ ...discoveryParams, use_llm_reranker: e.target.checked })}
                style={{ marginRight: '4px' }}
              />
              Use LLM reranker
            </label>
            <label className="toolbar-label" htmlFor="discovery-llm-top-n">
              LLM top N
            </label>
            <input
              id="discovery-llm-top-n"
              className="text-input compact-input"
              type="number"
              min="1"
              value={discoveryParams.llm_top_n}
              onChange={(e) => setDiscoveryParams({ ...discoveryParams, llm_top_n: parseInt(e.target.value, 10) || 20 })}
              disabled={!discoveryParams.use_llm_reranker}
            />
            <label className="toolbar-label" htmlFor="discovery-llm-weight">
              LLM weight
            </label>
            <input
              id="discovery-llm-weight"
              className="text-input compact-input"
              type="number"
              step="0.1"
              min="0"
              value={discoveryParams.llm_weight}
              onChange={(e) => setDiscoveryParams({ ...discoveryParams, llm_weight: parseFloat(e.target.value) || 1 })}
              disabled={!discoveryParams.use_llm_reranker}
            />
            <label className="toolbar-label" title="Dry-run mode: show planning diagnostics and skip external API calls.">
              <input
                type="checkbox"
                checked={discoveryParams.llm_dry_run}
                onChange={(e) => setDiscoveryParams({ ...discoveryParams, llm_dry_run: e.target.checked })}
                style={{ marginRight: '4px' }}
                disabled={!discoveryParams.use_llm_reranker}
              />
              Dry-run explain
            </label>
          </div>
          <div className="toolbar" style={{ marginTop: '8px' }}>
            <label className="toolbar-label" htmlFor="discovery-llm-model">
              LLM model
            </label>
            <input
              id="discovery-llm-model"
              className="text-input"
              type="text"
              placeholder="gpt-4o-mini"
              value={discoveryParams.llm_model}
              onChange={(e) => setDiscoveryParams({ ...discoveryParams, llm_model: e.target.value })}
              style={{ minWidth: '180px', flex: 1 }}
              disabled={!discoveryParams.use_llm_reranker}
            />
            <label className="toolbar-label" htmlFor="discovery-llm-api-base-url">
              LLM API base URL
            </label>
            <input
              id="discovery-llm-api-base-url"
              className="text-input"
              type="text"
              placeholder="https://api.openai.com/v1"
              value={discoveryParams.llm_api_base_url}
              onChange={(e) => setDiscoveryParams({ ...discoveryParams, llm_api_base_url: e.target.value })}
              style={{ minWidth: '220px', flex: 1 }}
              disabled={!discoveryParams.use_llm_reranker}
            />
          </div>
          <div className="toolbar" style={{ marginTop: '8px' }}>
            <label className="toolbar-label" htmlFor="discovery-llm-max-calls">
              Max calls
            </label>
            <input
              id="discovery-llm-max-calls"
              className="text-input compact-input"
              type="number"
              min="1"
              value={discoveryParams.llm_max_calls}
              onChange={(e) => setDiscoveryParams({ ...discoveryParams, llm_max_calls: parseInt(e.target.value, 10) || 20 })}
              disabled={!discoveryParams.use_llm_reranker}
            />
            <label className="toolbar-label" htmlFor="discovery-llm-max-input-chars">
              Max input chars
            </label>
            <input
              id="discovery-llm-max-input-chars"
              className="text-input compact-input"
              type="number"
              min="1000"
              step="1000"
              value={discoveryParams.llm_max_input_chars}
              onChange={(e) => setDiscoveryParams({ ...discoveryParams, llm_max_input_chars: parseInt(e.target.value, 10) || 50000 })}
              disabled={!discoveryParams.use_llm_reranker}
            />
          </div>
          <div className="toolbar" style={{ marginTop: '8px' }}>
            <label className="toolbar-label" htmlFor="discovery-llm-max-retries">
              Max retries
            </label>
            <input
              id="discovery-llm-max-retries"
              className="text-input compact-input"
              type="number"
              min="0"
              value={discoveryParams.llm_max_retries}
              onChange={(e) => setDiscoveryParams({ ...discoveryParams, llm_max_retries: parseInt(e.target.value, 10) || 0 })}
              disabled={!discoveryParams.use_llm_reranker}
            />
            <label className="toolbar-label" htmlFor="discovery-llm-retry-backoff-seconds">
              Retry backoff (s)
            </label>
            <input
              id="discovery-llm-retry-backoff-seconds"
              className="text-input compact-input"
              type="number"
              step="0.1"
              min="0"
              value={discoveryParams.llm_retry_backoff_seconds}
              onChange={(e) => setDiscoveryParams({ ...discoveryParams, llm_retry_backoff_seconds: parseFloat(e.target.value) || 0 })}
              disabled={!discoveryParams.use_llm_reranker}
            />
            <label className="toolbar-label" htmlFor="discovery-llm-timeout-seconds">
              Timeout (s)
            </label>
            <input
              id="discovery-llm-timeout-seconds"
              className="text-input compact-input"
              type="number"
              min="5"
              value={discoveryParams.llm_timeout_seconds}
              onChange={(e) => setDiscoveryParams({ ...discoveryParams, llm_timeout_seconds: parseInt(e.target.value, 10) || 20 })}
              disabled={!discoveryParams.use_llm_reranker}
            />
          </div>
        </details>
        <div className="toolbar" style={{ marginTop: '8px' }}>
          <label className="toolbar-label" htmlFor="discovery-max-age">
            Max age (days)
          </label>
          <input
            id="discovery-max-age"
            className="text-input compact-input"
            type="number"
            value={discoveryParams.max_age_days}
            onChange={(e) => setDiscoveryParams({ ...discoveryParams, max_age_days: parseInt(e.target.value) || 45 })}
            min="1"
          />
          <label className="toolbar-label" title="Include lower-fit adjacent roles (Stretch) in shortlist results">
            <input
              type="checkbox"
              checked={discoveryParams.include_stretch}
              onChange={(e) => setDiscoveryParams({ ...discoveryParams, include_stretch: e.target.checked })}
              style={{ marginRight: '4px' }}
            />
            Include stretch
          </label>
          <button className="save-btn" disabled={discovering || cooldownSecsLeft > 0} onClick={() => void triggerDiscovery()}>
            {discovering ? 'Running...' : cooldownSecsLeft > 0 ? `Wait ${cooldownSecsLeft}s` : 'Run discovery'}
          </button>
        </div>
        {discovering && discoveryStatus?.in_flight && (
          <p className="discovery-status-line muted-mini">
            {discoveryStatus.elapsed_seconds !== null
              ? `Running… ${discoveryStatus.elapsed_seconds}s elapsed`
              : 'Starting…'}
          </p>
        )}
        <div className="details-panel" style={{ marginTop: '10px' }}>
          <strong className="muted-mini">Websites</strong>
          <div className="process-actions">
            {DISCOVERY_SOURCES.map((source) => (
              <label key={source.key} className="toolbar-label" style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                <input
                  type="checkbox"
                  checked={!!discoverySourceSelection[source.key]}
                  onChange={(e) =>
                    setDiscoverySourceSelection((prev) => ({
                      ...prev,
                      [source.key]: e.target.checked,
                    }))
                  }
                />
                {source.label}
              </label>
            ))}
          </div>
        </div>
        {llmDryRunDiagnostics && (
          <div className="dry-run-card">
            <strong>LLM {llmDryRunDiagnostics.dryRun ? 'Dry-run' : 'Rerank'} Report</strong>
            <div className="dry-run-grid">
              <span>Dry-run mode</span>
              <span>{llmDryRunDiagnostics.dryRun ? 'Yes' : 'No'}</span>
              <span>Planned calls</span>
              <span>{llmDryRunDiagnostics.plannedCalls ?? 'n/a'}</span>
              <span>Attempted calls</span>
              <span>{llmDryRunDiagnostics.attempted ?? 'n/a'}</span>
              <span>Adjusted rows</span>
              <span>{llmDryRunDiagnostics.adjusted ?? 'n/a'}</span>
              <span>Used input chars</span>
              <span>{llmDryRunDiagnostics.usedInputChars ?? 'n/a'}</span>
              <span>Warnings</span>
              <span>{llmDryRunDiagnostics.warningsCount ?? 'n/a'}</span>
            </div>
          </div>
        )}
        {discoveryResult && (
          <div className="result-banner">
            <strong>Discovery exit code:</strong> {discoveryResult.exit_code}
            {(discoveryResult.strict_count > 0 || discoveryResult.broad_count > 0) && (
              <p style={{ margin: '6px 0 0' }}>
                Strong/Medium: <strong>{discoveryResult.strict_count}</strong> &nbsp;|&nbsp;
                Broad: <strong>{discoveryResult.broad_count}</strong> &nbsp;|&nbsp;
                Synced: <strong>{discoveryResult.synced_count}</strong>
                {discoveryResult.failed_count > 0 && (
                  <span style={{ color: 'var(--color-warn, #c07000)' }}>
                    {' '}(⚠ {discoveryResult.failed_count} failed)
                  </span>
                )}
              </p>
            )}
            {discoveryResult.source_results.length > 0 && (
              <details style={{ marginTop: '8px' }}>
                <summary className="muted-mini">Per-source breakdown ({discoveryResult.source_results.length} sources)</summary>
                <table className="source-results-table" style={{ marginTop: '6px', borderCollapse: 'collapse', fontSize: '0.85em' }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: 'left', paddingRight: '16px' }}>Source</th>
                      <th style={{ textAlign: 'right', paddingRight: '16px' }}>Collected</th>
                      <th style={{ textAlign: 'left' }}>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {discoveryResult.source_results.map((sr) => (
                      <tr key={sr.key}>
                        <td style={{ paddingRight: '16px' }}>{sr.label}</td>
                        <td style={{ textAlign: 'right', paddingRight: '16px' }}>{sr.collected}</td>
                        <td style={{ color: sr.error ? 'var(--color-warn, #c07000)' : 'var(--color-ok, #2a8a2a)' }}>
                          {sr.error ? `⚠ ${sr.error.slice(0, 80)}` : '✓'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            )}
            {discoveryResult.stdout && <pre>{discoveryResult.stdout}</pre>}
            {discoveryResult.stderr && <pre>{discoveryResult.stderr}</pre>}
          </div>
        )}
      </section>
      <section className="card">
        <h2>Add Job Manually</h2>
        <p className="subtitle small">Create a new job entry without discovery.</p>
        <div className="toolbar">
          <input
            className="text-input"
            type="text"
            placeholder="Company"
            value={manualJobForm.company}
            onChange={(e) => setManualJobForm({ ...manualJobForm, company: e.target.value })}
          />
          <input
            className="text-input"
            type="text"
            placeholder="Role"
            value={manualJobForm.role}
            onChange={(e) => setManualJobForm({ ...manualJobForm, role: e.target.value })}
          />
          <input
            className="text-input"
            type="url"
            placeholder="Job link (optional)"
            value={manualJobForm.link}
            onChange={(e) => setManualJobForm({ ...manualJobForm, link: e.target.value })}
          />
        </div>
        <div style={{ marginTop: '8px' }}>
          <label className="muted-mini" style={{ display: 'block', marginBottom: '4px' }}>Job description or notes (optional)</label>
          <textarea
            className="notes-input"
            value={manualJobForm.description}
            onChange={(e) => setManualJobForm({ ...manualJobForm, description: e.target.value })}
            placeholder="Paste job description, key requirements, or any notes..."
            style={{ minHeight: '80px' }}
          />
          <button
            className="save-btn"
            onClick={async () => {
              if (manualJobForm.company.trim() && manualJobForm.role.trim()) {
                try {
                  setError(null)
                  setSuccessMessage(null)
                  await upsertApplication({
                    company: manualJobForm.company.trim(),
                    role: manualJobForm.role.trim(),
                    link: manualJobForm.link.trim() || undefined,
                    notes: manualJobForm.description,
                    status: 'To review',
                    match_profile: discoveryProfile,
                    source: 'manual',
                  })
                  setManualJobForm({ company: '', role: '', link: '', description: '' })
                  setLoading(true)
                  void onRunComplete()
                  setSuccessMessage('Job added successfully')
                } catch (e) {
                  setError(e instanceof Error ? e.message : 'Failed to add job')
                }
              } else {
                setError('Company and role are required')
              }
            }}
            style={{ marginTop: '8px' }}
          >
            Add job
          </button>
        </div>
      </section>
    </>
  )
}
