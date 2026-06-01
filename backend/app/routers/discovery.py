import concurrent.futures
import importlib
import ipaddress
import logging
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException

from ..config import settings
from ..dependencies import require_write_access
from ..pathing import is_within_path, project_root, resolve_from_project_root, resolve_from_workspace_root, workspace_root
from ..schemas import DiscoveryRunRequest, DiscoveryRunResponse, DiscoveryStatusOut, SourceRunResult

logger = logging.getLogger(__name__)
router = APIRouter(tags=["imports"])

# Guard endpoint load and prevent accidental duplicate runs from rapid UI retries.
DISCOVERY_MIN_INTERVAL_SECONDS = 30.0
# Hard wall-clock ceiling for a single pipeline run.  If the run hangs (e.g. a
# job-board source or LLM API stops responding), the slot is released after this
# many seconds so subsequent requests are not blocked permanently.
DISCOVERY_MAX_WALL_SECONDS = 15 * 60  # 15 minutes
class _DiscoveryGuard:
    """Encapsulates single-flight state and rate-limiting for the discovery endpoint."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.in_flight = False
        self.last_started_monotonic: float = 0.0

    def claim(self) -> None:
        now = time.monotonic()
        with self.lock:
            if self.in_flight:
                raise HTTPException(status_code=429, detail="Discovery run already in progress")
            elapsed = now - self.last_started_monotonic
            if self.last_started_monotonic > 0 and elapsed < DISCOVERY_MIN_INTERVAL_SECONDS:
                retry_after = max(1, int(DISCOVERY_MIN_INTERVAL_SECONDS - elapsed))
                raise HTTPException(
                    status_code=429,
                    detail=f"Discovery runs are rate-limited. Retry in ~{retry_after}s.",
                )
            self.in_flight = True
            self.last_started_monotonic = now

    def release(self) -> None:
        with self.lock:
            self.in_flight = False

    def reset(self) -> None:
        """Test-only helper to keep discovery endpoint tests isolated."""
        with self.lock:
            self.in_flight = False
            self.last_started_monotonic = 0.0


_guard = _DiscoveryGuard()


def _claim_discovery_slot() -> None:
    _guard.claim()


def _release_discovery_slot() -> None:
    _guard.release()


def _reset_discovery_run_guard() -> None:
    """Test-only helper to keep discovery endpoint tests isolated."""
    _guard.reset()


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


def _resolve_cv_path(payload: DiscoveryRunRequest) -> Path:
    requested_cv_path = (payload.cv_path or "").strip()
    if requested_cv_path:
        cv_path = resolve_from_workspace_root(requested_cv_path)
        if not is_within_path(cv_path, workspace_root()):
            raise HTTPException(
                status_code=400,
                detail="cv_path must be within the workspace root",
            )
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
    return cv_path


def _check_api_base_url_ssrf(url: str) -> None:
    """Reject private/reserved IP literals in api_base_url to prevent SSRF.

    Only IP-literal hostnames are validated; hostname resolution would require
    a DNS round-trip and is not performed here.  127.x.x.x (loopback) is
    explicitly allowed because it is the legitimate default backend address.
    """
    try:
        hostname = urlparse(url).hostname or ""
        try:
            ip = ipaddress.ip_address(hostname)
        except ValueError:
            return  # Not an IP literal — cannot validate without DNS resolution.
        if ip.is_loopback:
            return  # 127.0.0.1/::1 are the legitimate defaults.
        if ip.is_link_local or ip.is_private or ip.is_reserved:
            raise HTTPException(
                status_code=400,
                detail="api_base_url must not target a private or reserved address",
            )
    except HTTPException:
        raise
    except Exception:  # pragma: no cover
        pass  # Best-effort; do not block on unexpected parse errors.


def _resolve_api_base_url(payload: DiscoveryRunRequest) -> str:
    api_base_url = (payload.api_base_url or settings.discovery_api_base_url or "").strip()
    if not api_base_url:
        raise HTTPException(status_code=400, detail="api_base_url is missing")
    if not (api_base_url.startswith("http://") or api_base_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="api_base_url must start with http:// or https://")
    _check_api_base_url_ssrf(api_base_url)
    return api_base_url


def _validate_llm_api_base_url(payload: DiscoveryRunRequest) -> str | None:
    """Return validated llm_api_base_url, applying SSRF check on IP literals."""
    url = payload.llm_api_base_url  # scheme already validated by Pydantic
    if url:
        _check_api_base_url_ssrf(url)
    return url


def _resolve_output_dir(payload: DiscoveryRunRequest) -> Path | None:
    """Resolve and validate output_dir, ensuring it stays within the workspace root."""
    raw = (payload.output_dir or "").strip()
    if not raw:
        return None
    candidate = resolve_from_workspace_root(raw)
    if not is_within_path(candidate, workspace_root()):
        raise HTTPException(
            status_code=400,
            detail="output_dir must be within the workspace root",
        )
    return candidate  # pragma: no cover


def _run_discovery_module(
    payload: DiscoveryRunRequest,
    cv_path: Path,
    profile: str,
    seniority: str,
    api_base_url: str,
) -> DiscoveryRunResponse:
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
        llm_api_base_url=_validate_llm_api_base_url(payload),
        llm_dry_run=payload.llm_dry_run,
        llm_max_calls=payload.llm_max_calls,
        llm_max_input_chars=payload.llm_max_input_chars,
        llm_max_retries=payload.llm_max_retries,
        llm_retry_backoff_seconds=payload.llm_retry_backoff_seconds,
        llm_timeout_seconds=payload.llm_timeout_seconds,
        api_base_url=api_base_url,
        api_write_key=settings.write_api_key,
        output_dir=_resolve_output_dir(payload),
    )
    run_warnings = None
    # Wrap the runner so the guard slot is released from inside the thread.
    # This covers both the normal path and the timeout path: when a 504 fires
    # the executor thread keeps running in the background, and only releases
    # the slot when it actually finishes — preventing a second run from racing
    # against a still-in-progress pipeline.
    slot_released_by_thread = threading.Event()

    def _runner_with_slot_release() -> tuple[object, object]:
        try:
            return runner(options)
        finally:
            slot_released_by_thread.set()
            _release_discovery_slot()

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(_runner_with_slot_release)
        try:
            run_result, run_warnings = future.result(timeout=DISCOVERY_MAX_WALL_SECONDS)
        except concurrent.futures.TimeoutError:
            raise HTTPException(
                status_code=504,
                detail=(
                    f"Discovery timed out after {DISCOVERY_MAX_WALL_SECONDS}s. "
                    "The pipeline may still be completing in the background."
                ),
            )
    finally:
        executor.shutdown(wait=False)
        if not slot_released_by_thread.is_set():
            pass  # background thread will release when done

    assert run_warnings is not None, "Discovery pipeline must return a warnings object"

    logger.info(
        "discovery run complete: strict=%d broad=%d synced=%d failed=%d warnings=%d",
        len(run_result.strict_matches),
        len(run_result.broad_matches),
        run_result.synced_count,
        len(run_result.failed_rows),
        len(run_warnings.messages),
    )

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

        source_results = [
            SourceRunResult(key=sr.key, label=sr.label, collected=sr.collected, error=sr.error or "")
            for sr in run_result.collection_report.sources
        ]
        return DiscoveryRunResponse(
            exit_code=0,
            command=["module:job_discovery_engine.run_discovery_pipeline"],
            stdout=_sanitize_for_public_logs("\n".join(stdout_lines)),
            stderr="",
            source_results=source_results,
            strict_count=len(run_result.strict_matches),
            broad_count=len(run_result.broad_matches),
            synced_count=run_result.synced_count,
            failed_count=len(run_result.failed_rows),
        )

    source_results = [
        SourceRunResult(key=sr.key, label=sr.label, collected=sr.collected, error=sr.error or "")
        for sr in run_result.collection_report.sources
    ]
    return DiscoveryRunResponse(
        exit_code=0,
        command=[],
        stdout="Discovery completed successfully. Enable verbose=true to inspect execution logs.",
        stderr="",
        source_results=source_results,
        strict_count=len(run_result.strict_matches),
        broad_count=len(run_result.broad_matches),
        synced_count=run_result.synced_count,
        failed_count=len(run_result.failed_rows),
    )


@router.get(
    "/discovery/status",
    response_model=DiscoveryStatusOut,
    summary="Poll discovery run status",
    description="Returns whether a discovery run is currently in flight and how many seconds it has been running.",
    tags=["imports"],
)
def get_discovery_status() -> DiscoveryStatusOut:
    now = time.monotonic()
    with _guard.lock:
        in_flight = _guard.in_flight
        last_started = _guard.last_started_monotonic

    elapsed = (now - last_started) if last_started > 0 and in_flight else None
    cooldown_remaining: float | None = None
    if not in_flight and last_started > 0:
        remaining = DISCOVERY_MIN_INTERVAL_SECONDS - (now - last_started)
        if remaining > 0:
            cooldown_remaining = round(remaining, 1)

    return DiscoveryStatusOut(
        in_flight=in_flight,
        elapsed_seconds=round(elapsed, 1) if elapsed is not None else None,
        cooldown_seconds_remaining=cooldown_remaining,
    )


@router.post(
    "/run-discovery",
    response_model=DiscoveryRunResponse,
    summary="Run discovery pipeline",
    description="Runs discovery through the installed job_discovery_engine package and upserts shortlisted roles.",
)
def run_discovery(payload: DiscoveryRunRequest, _: None = Depends(require_write_access)) -> DiscoveryRunResponse:
    cv_path = _resolve_cv_path(payload)
    profile = (payload.profile or settings.discovery_default_profile or "de").strip().lower()
    seniority = (payload.seniority or "").strip().lower()
    api_base_url = _resolve_api_base_url(payload)

    logger.info(
        "discovery run requested: profile=%s cv=%s limit=%d min_score=%d sources=%s",
        profile,
        _sanitize_for_public_logs(str(cv_path)),
        payload.limit,
        payload.min_score,
        ",".join(payload.sources) if payload.sources else "all",
    )

    _claim_discovery_slot()
    try:
        return _run_discovery_module(payload, cv_path, profile, seniority, api_base_url)
    except HTTPException as exc:
        if exc.status_code == 504:
            logger.warning("discovery timed out after %ds", DISCOVERY_MAX_WALL_SECONDS)
        else:
            logger.warning("discovery aborted: HTTP %d", exc.status_code)
            _release_discovery_slot()
        raise
    except Exception:  # pragma: no cover
        logger.exception("discovery run failed with unexpected error")
        _release_discovery_slot()
        raise
