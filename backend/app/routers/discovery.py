import os
import subprocess
import sys

from fastapi import APIRouter, Depends, HTTPException

from ..config import settings
from ..dependencies import require_write_access
from ..helpers import summarize_process_output
from ..pathing import resolve_from_project_root, resolve_from_workspace_root
from ..schemas import DiscoveryRunRequest, DiscoveryRunResult

router = APIRouter(tags=["imports"])


@router.post(
    "/run-discovery",
    response_model=DiscoveryRunResult,
    summary="Trigger the external discovery script",
    description="Runs the existing job finder script and lets it upsert discovered roles back into this API.",
)
def run_discovery(payload: DiscoveryRunRequest, _: None = Depends(require_write_access)) -> DiscoveryRunResult:
    script_path = resolve_from_project_root(settings.discovery_script_path)

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

    if not script_path.exists():
        raise HTTPException(status_code=500, detail=f"Discovery script not found: {script_path}")
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

    api_base_url = (payload.api_base_url or settings.discovery_api_base_url or "").strip()
    if not api_base_url:
        raise HTTPException(status_code=400, detail="api_base_url is missing")
    if not (api_base_url.startswith("http://") or api_base_url.startswith("https://")):
        raise HTTPException(status_code=400, detail="api_base_url must start with http:// or https://")

    command = [
        sys.executable,
        str(script_path),
        "--cv-path",
        str(cv_path),
        "--limit",
        str(payload.limit),
        "--min-score",
        str(payload.min_score),
        "--max-age-days",
        str(payload.max_age_days),
        "--api-base-url",
        api_base_url,
        "--profile",
        profile,
    ]
    if payload.include_stretch:
        command.append("--include-stretch")
    if payload.verbose:
        command.append("--verbose")
    if payload.sources:
        selected_sources = [src.strip().lower() for src in payload.sources if src and src.strip()]
        if selected_sources:
            command.extend(["--sources", ",".join(selected_sources)])

    try:
        subprocess_env = {**os.environ}
        if settings.write_api_key:
            subprocess_env["JOB_SEARCH_WRITE_API_KEY"] = settings.write_api_key
        completed = subprocess.run(
            command,
            cwd=str(script_path.parent.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            env=subprocess_env,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail=f"Discovery run timed out after {exc.timeout} seconds") from exc

    if completed.returncode != 0:
        stderr = summarize_process_output(completed.stderr, settings.discovery_log_max_chars)
        raise HTTPException(
            status_code=500,
            detail=f"Discovery script failed with exit code {completed.returncode}. stderr: {stderr}",
        )

    return DiscoveryRunResult(
        exit_code=completed.returncode,
        command=command,
        stdout=summarize_process_output(completed.stdout, settings.discovery_log_max_chars),
        stderr=summarize_process_output(completed.stderr, settings.discovery_log_max_chars),
    )
