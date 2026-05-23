import threading
import time
import importlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ..config import settings
from ..dependencies import require_write_access
from ..pathing import project_root, resolve_from_project_root, resolve_from_workspace_root, workspace_root
from ..schemas import DiscoveryRunRequest, DiscoveryRunResult

router = APIRouter(tags=["imports"])

DISCOVERY_MIN_INTERVAL_SECONDS = 30.0
_discovery_guard_lock = threading.Lock()
_discovery_in_flight = False
_discovery_last_started_monotonic = 0.0


def _claim_discovery_slot() -> None:
    global _discovery_in_flight, _discovery_last_started_monotonic

    now = time.monotonic()
    with _discovery_guard_lock:
        if _discovery_in_flight:
            raise HTTPException(status_code=429, detail="Discovery run already in progress")

        elapsed = now - _discovery_last_started_monotonic
        if _discovery_last_started_monotonic > 0 and elapsed < DISCOVERY_MIN_INTERVAL_SECONDS:
            retry_after = max(1, int(DISCOVERY_MIN_INTERVAL_SECONDS - elapsed))
            raise HTTPException(
                status_code=429,
                detail=f"Discovery runs are rate-limited. Retry in ~{retry_after}s.",
            )

        _discovery_in_flight = True
        _discovery_last_started_monotonic = now


def _release_discovery_slot() -> None:
    global _discovery_in_flight
    with _discovery_guard_lock:
        _discovery_in_flight = False


def _reset_discovery_run_guard() -> None:
    """Test-only helper to keep discovery endpoint tests isolated."""
    global _discovery_in_flight, _discovery_last_started_monotonic
    with _discovery_guard_lock:
        _discovery_in_flight = False
        _discovery_last_started_monotonic = 0.0


def _sanitize_for_public_logs(text: str) -> str:
    redacted = text
    replacements = [
        (str(workspace_root()), "<workspace>"),
        (str(project_root()), "<app>"),
        (str(Path.home()), "<home>"),
    ]
    for raw, token in replacements:
        if raw:
            redacted = redacted.replace(raw, token)
    return redacted


def _run_discovery_module(
    payload: DiscoveryRunRequest,
    cv_path: Path,
    profile: str,
    seniority: str,
    api_base_url: str,
) -> DiscoveryRunResult:
    try:
        api_module = importlib.import_module("job_discovery_engine.api")
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Discovery module package not found. "
                "Install backend requirements to provide job_discovery_engine."
            ),
        ) from exc

    options_cls = getattr(api_module, "DiscoveryRunOptions")
    runner = getattr(api_module, "run_discovery_pipeline")

    selected_sources: list[str] | None = None
    if payload.sources:
        selected_sources = [src.strip().lower() for src in payload.sources if src and src.strip()]

    options = options_cls(
        cv_path=cv_path,
        limit=payload.limit,
        min_score=payload.min_score,
        max_age_days=payload.max_age_days,
        include_stretch=payload.include_stretch,
        profile=profile,
        sources=selected_sources,
        salary_min_usd=payload.salary_min_usd,
        timezones=payload.timezones,
        seniority=seniority or None,
        use_outcome_priors=payload.use_outcome_priors,
        prior_lookback_days=payload.prior_lookback_days,
        source_prior_weight=payload.source_prior_weight,
        role_prior_weight=payload.role_prior_weight,
        use_llm_reranker=payload.use_llm_reranker,
        llm_top_n=payload.llm_top_n,
        llm_weight=payload.llm_weight,
        llm_model=(payload.llm_model or "").strip() or None,
        llm_api_base_url=(payload.llm_api_base_url or "").strip() or None,
        llm_dry_run=payload.llm_dry_run,
        llm_max_calls=payload.llm_max_calls,
        llm_max_input_chars=payload.llm_max_input_chars,
        llm_max_retries=payload.llm_max_retries,
        llm_retry_backoff_seconds=payload.llm_retry_backoff_seconds,
        llm_timeout_seconds=payload.llm_timeout_seconds,
        api_base_url=api_base_url,
        api_write_key=settings.write_api_key,
        output_dir=resolve_from_workspace_root(payload.output_dir.strip()) if (payload.output_dir or "").strip() else None,
    )
    run_result, run_warnings = runner(options)

    if payload.verbose:
        stdout_lines = [
            f"- strict_matches={len(run_result.strict_matches)}",
            f"- broad_matches={len(run_result.broad_matches)}",
            f"- synced_count={run_result.synced_count}",
            f"- failed_rows={len(run_result.failed_rows)}",
            f"- llm_dry_run={run_result.llm_report.dry_run}",
            f"- llm_planned_calls={run_result.llm_report.planned_calls}",
            f"- llm_attempted={run_result.llm_report.attempted}",
            f"- llm_adjusted={run_result.llm_report.adjusted}",
            f"- llm_used_input_chars={run_result.llm_report.used_input_chars}",
        ]
        if run_warnings.messages:
            stdout_lines.append(f"- warnings={len(run_warnings.messages)}")
            stdout_lines.extend(run_warnings.messages[:5])

        return DiscoveryRunResult(
            exit_code=0,
            command=["module:job_discovery_engine.run_discovery_pipeline"],
            stdout=_sanitize_for_public_logs("\n".join(stdout_lines)),
            stderr="",
        )

    return DiscoveryRunResult(
        exit_code=0,
        command=[],
        stdout="Discovery completed successfully. Enable verbose=true to inspect execution logs.",
        stderr="",
    )


@router.post(
    "/run-discovery",
    response_model=DiscoveryRunResult,
    summary="Trigger the external discovery script",
    description="Runs the existing job finder script and lets it upsert discovered roles back into this API.",
)
def run_discovery(payload: DiscoveryRunRequest, _: None = Depends(require_write_access)) -> DiscoveryRunResult:
    requested_cv_path = (payload.cv_path or "").strip()
    if requested_cv_path:
        cv_path = resolve_from_workspace_root(requested_cv_path)
    elif settings.discovery_cv_path.strip():
        cv_path = resolve_from_project_root(settings.discovery_cv_path)
    else:
        raise HTTPException(
            status_code=400,
            detail=(
                "CV path is missing. Provide cv_path in the /run-discovery request "
                "or set DISCOVERY_CV_PATH in .env as a backend fallback."
            ),
        )

    if not cv_path.exists() or not cv_path.is_file():
        raise HTTPException(
            status_code=400,
            detail=(
                f"Discovery CV not found: {cv_path}. "
                "Use an absolute path or a workspace-relative path like applications/resumes/CV.tex"
            ),
        )

    profile = (payload.profile or settings.discovery_default_profile or "de").strip().lower()
    if profile not in {"de", "swe", "other"}:
        raise HTTPException(status_code=400, detail="profile must be one of: de, swe, other")

    seniority = (payload.seniority or "").strip().lower()
    if seniority and seniority not in {"junior", "mid", "senior"}:
        raise HTTPException(status_code=400, detail="seniority must be one of: junior, mid, senior")

    api_base_url = (payload.api_base_url or settings.discovery_api_base_url or "").strip()
    if not api_base_url:
        raise HTTPException(status_code=400, detail="api_base_url is missing")
    if not (api_base_url.startswith("http://") or api_base_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="api_base_url must start with http:// or https://")

    _claim_discovery_slot()
    try:
        return _run_discovery_module(payload, cv_path, profile, seniority, api_base_url)
    finally:
        _release_discovery_slot()
