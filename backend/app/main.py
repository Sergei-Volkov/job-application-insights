from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, func, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .dependencies import get_db, require_write_access
from .database import SessionLocal, engine
from .init_db import init_db
from .models import JobApplication
from .routers.analytics import router as analytics_router
from .routers.system import router as system_router
from .schemas import (
    DiscoveryRunRequest,
    DiscoveryRunResult,
    GenerateDocumentsRequest,
    GenerateDocumentsResult,
    JobApplicationOut,
    JobApplicationUpdate,
    JobApplicationUpsert,
    SkillGapList,
    StatsOut,
    TrendList,
    WorkspaceFileReadResult,
    WorkspaceFileWriteRequest,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    inspector = inspect(engine)
    if not inspector.has_table(JobApplication.__tablename__):
        init_db()
    yield


app = FastAPI(
    title="Job Application Insights API",
    version="0.3.0",
    summary="Track job applications, ingest discovered roles, and visualize the application pipeline.",
    description=(
        "A DB-first API for a personal job search workflow. Use it to ingest jobs from a discovery "
        "worker, update application state from the UI, and analyze status, skill gaps, and trends."
    ),
    openapi_tags=[
        {"name": "system", "description": "Health and operational endpoints."},
        {"name": "applications", "description": "CRUD-style endpoints for tracked job applications."},
        {"name": "imports", "description": "Import or upsert jobs from external discovery flows."},
        {"name": "analytics", "description": "Aggregated views used by the dashboard."},
        {"name": "workspace", "description": "Generate and edit application documents in the workspace."},
    ],
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["GET", "POST", "PATCH", "PUT"],
    allow_headers=["Content-Type", "X-API-Key"],
)

app.include_router(system_router)
app.include_router(analytics_router)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def workspace_root() -> Path:
    return project_root().parent


def resolve_from_project_root(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (project_root() / path).resolve()


def resolve_from_workspace_root(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (workspace_root() / path).resolve()


def applications_root() -> Path:
    return resolve_from_workspace_root(settings.applications_root)


def resolve_from_applications_root(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path

    normalized = raw_path.strip().replace("\\", "/")
    root_norm = settings.applications_root.strip().replace("\\", "/").strip("/")
    if root_norm and (normalized == root_norm or normalized.startswith(root_norm + "/")):
        # Backward compatibility for existing workspace-relative values.
        return resolve_from_workspace_root(raw_path)

    return (applications_root() / path).resolve()


def templates_root() -> Path:
    return resolve_from_applications_root(settings.vacancies_template_dir)


def base_cv_template_path() -> Path:
    return resolve_from_applications_root(settings.base_cv_template_path)


def _is_within_path(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _safe_relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug[:80] or "item"


def _listing_fingerprint(values: list[str]) -> str:
    joined = "||".join((v or "").strip() for v in values)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _build_docs_directory(record: JobApplication) -> Path:
    vacancies_root = applications_root() / "vacancies"
    return vacancies_root / f"{_slugify(record.company)}_{_slugify(record.role)}"


def _render_cover_letter(template_text: str, record: JobApplication, author_name: str) -> str:
    text = template_text
    text = text.replace("[Role Title]", record.role or "Role")
    text = text.replace("[Company]", record.company or "Company")
    text = text.replace(
        "[specific reason tied to company/role]", f"the role focus in {record.company or 'the company'}"
    )
    text = text.replace("[Author Name]", author_name)
    text = text.replace("[Your Name]", author_name)
    return text


def _render_vacancy_notes(template_text: str, record: JobApplication) -> str:
    date_found = (record.date_found or "").strip() or _today_iso()
    source_url = (record.link or "").strip()
    source_url_md = f"[{source_url}]({source_url})" if source_url else "n/a"
    return (
        template_text.replace("## Company\n- ", f"## Company\n- {record.company or 'Unknown'}")
        .replace("## Role\n- ", f"## Role\n- {record.role or 'Unknown'}")
        .replace("## Source URL\n- ", f"## Source URL\n- {source_url_md}")
        .replace(
            "## Requirements (copied)\n- ",
            f"## Requirements (copied)\n- {record.notes or 'Copy key requirements from posting.'}",
        )
        .replace(
            "## Key signals to mirror in CV\n- ",
            f"## Key signals to mirror in CV\n- Match profile: {record.match_profile or 'de'}",
        )
        + f"\n\n## Metadata\n- Date found: {date_found}\n- Fit score: {record.fit_score}\n- Fit label: {record.fit or 'n/a'}\n"
    )


def _normalize_key(value: str | None) -> str:
    return (value or "").strip().lower()


def find_existing_application(db: Session, company: str, role: str, link: str) -> JobApplication | None:
    existing = None
    if link:
        existing = db.query(JobApplication).filter(JobApplication.link == link).first()
    if existing is not None:
        return existing

    return (
        db.query(JobApplication)
        .filter(
            and_(
                func.lower(JobApplication.company) == _normalize_key(company),
                func.lower(JobApplication.role) == _normalize_key(role),
            )
        )
        .first()
    )


@app.get(
    "/applications",
    response_model=list[JobApplicationOut],
    tags=["applications"],
    summary="List tracked job applications",
)
def list_applications(
    status: str | None = Query(default=None),
    min_fit_score: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[JobApplicationOut]:
    query = db.query(JobApplication)

    if status:
        normalized = status.strip().lower()
        if normalized:
            query = query.filter(func.lower(JobApplication.status) == normalized)
    if min_fit_score is not None:
        query = query.filter(JobApplication.fit_score >= min_fit_score)

    return query.order_by(JobApplication.fit_score.desc(), JobApplication.id.asc()).offset(offset).limit(limit).all()


@app.post(
    "/applications",
    response_model=JobApplicationOut,
    status_code=status.HTTP_201_CREATED,
    tags=["applications"],
    summary="Create one application",
    description="Creates a new application and rejects duplicates by link or by company + role.",
)
def create_application(
    payload: JobApplicationUpsert,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
) -> JobApplicationOut:
    existing = find_existing_application(db, company=payload.company, role=payload.role, link=payload.link)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Application already exists")

    payload_data = payload.model_dump()
    today = _today_iso()

    if not payload_data.get("first_seen_at"):
        payload_data["first_seen_at"] = today
    if not payload_data.get("last_seen_at"):
        payload_data["last_seen_at"] = today
    if not payload_data.get("listing_fingerprint"):
        payload_data["listing_fingerprint"] = _listing_fingerprint(
            [
                payload_data.get("company", ""),
                payload_data.get("role", ""),
                payload_data.get("link", ""),
                payload_data.get("source", ""),
                payload_data.get("fit", ""),
                str(payload_data.get("fit_score", "")),
                payload_data.get("notes", ""),
            ]
        )

    record = JobApplication(**payload_data)
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Application already exists")

    db.refresh(record)
    return record


@app.post(
    "/applications/upsert",
    response_model=JobApplicationOut,
    tags=["imports", "applications"],
    summary="Create or update one application",
    description="Upserts one application by link, or by company + role when link is missing.",
)
def upsert_application(
    payload: JobApplicationUpsert,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
) -> JobApplicationOut:
    payload_data = payload.model_dump()
    today = _today_iso()

    if not payload_data.get("last_seen_at"):
        payload_data["last_seen_at"] = today
    if not payload_data.get("listing_fingerprint"):
        payload_data["listing_fingerprint"] = _listing_fingerprint(
            [
                payload_data.get("company", ""),
                payload_data.get("role", ""),
                payload_data.get("link", ""),
                payload_data.get("source", ""),
                payload_data.get("fit", ""),
                str(payload_data.get("fit_score", "")),
                payload_data.get("notes", ""),
            ]
        )

    record = find_existing_application(db, company=payload.company, role=payload.role, link=payload.link)

    if record is None:
        if not payload_data.get("first_seen_at"):
            payload_data["first_seen_at"] = today
        record = JobApplication(**payload_data)
        db.add(record)
    else:
        previous_fingerprint = (record.listing_fingerprint or "").strip()
        incoming_fingerprint = (payload_data.get("listing_fingerprint") or "").strip()

        payload_data["first_seen_at"] = record.first_seen_at or payload_data.get("first_seen_at") or today

        if previous_fingerprint and incoming_fingerprint and previous_fingerprint != incoming_fingerprint:
            payload_data["change_note"] = f"Updated on {today}: listing details changed"
        elif not payload_data.get("change_note"):
            payload_data["change_note"] = record.change_note or ""

        for field, value in payload_data.items():
            setattr(record, field, value)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        record = find_existing_application(db, company=payload.company, role=payload.role, link=payload.link)
        if record is None:
            raise HTTPException(status_code=409, detail="Conflict while upserting application")

        previous_fingerprint = (record.listing_fingerprint or "").strip()
        incoming_fingerprint = (payload_data.get("listing_fingerprint") or "").strip()
        if previous_fingerprint and incoming_fingerprint and previous_fingerprint != incoming_fingerprint:
            payload_data["change_note"] = f"Updated on {today}: listing details changed"

        for field, value in payload_data.items():
            setattr(record, field, value)
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail="Failed to update existing application") from exc

    db.refresh(record)
    return record


@app.patch(
    "/applications/{application_id}",
    response_model=JobApplicationOut,
    tags=["applications"],
    summary="Patch editable fields on one application",
)
def patch_application(
    application_id: int,
    payload: JobApplicationUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
) -> JobApplicationOut:
    record = db.query(JobApplication).filter(JobApplication.id == application_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Application not found")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(record, field, value)

    db.commit()
    db.refresh(record)
    return record


def _resolve_workspace_file_path(raw_path: str) -> Path:
    path = resolve_from_workspace_root(raw_path)
    root = applications_root()
    if not _is_within_path(path, root):
        raise HTTPException(status_code=400, detail="Only files under applications/ are allowed")
    if path.suffix.lower() not in {".md", ".tex", ".txt", ".csv"}:
        raise HTTPException(status_code=400, detail="Unsupported file extension")
    return path


@app.post(
    "/applications/{application_id}/generate-documents",
    response_model=GenerateDocumentsResult,
    tags=["workspace", "applications"],
    summary="Generate tailored vacancy files for one application",
)
def generate_documents(
    application_id: int,
    payload: GenerateDocumentsRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
) -> GenerateDocumentsResult:
    record = db.query(JobApplication).filter(JobApplication.id == application_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Application not found")

    template_dir = templates_root()
    if not template_dir.exists() or not template_dir.is_dir():
        raise HTTPException(status_code=500, detail=f"Template directory not found: {template_dir}")

    vacancy_template = template_dir / "vacancy.md"
    cover_letter_template = template_dir / "cover_letter.md"
    notes_template = template_dir / "notes.md"
    cv_template = base_cv_template_path()

    for required in [vacancy_template, cover_letter_template, notes_template, cv_template]:
        if not required.exists() or not required.is_file():
            raise HTTPException(status_code=500, detail=f"Required template file not found: {required}")

    target_dir = _build_docs_directory(record)
    target_dir.mkdir(parents=True, exist_ok=True)

    vacancy_path = target_dir / "vacancy.md"
    cover_letter_path = target_dir / "cover_letter.md"
    notes_path = target_dir / "notes.md"
    cv_path = target_dir / "cv.tex"

    if not payload.overwrite:
        existing_files = [p for p in [vacancy_path, cover_letter_path, notes_path, cv_path] if p.exists()]
        if existing_files:
            names = ", ".join(p.name for p in existing_files)
            raise HTTPException(status_code=409, detail=f"Target files already exist: {names}. Set overwrite=true.")

    vacancy_text = _render_vacancy_notes(vacancy_template.read_text(encoding="utf-8"), record)
    author_name = (
        (payload.author_name.strip() if payload.author_name else None)
        or (payload.your_name.strip() if payload.your_name else None)
        or (settings.generated_document_author.strip() if settings.generated_document_author else None)
        or "Author Name"
    )
    cover_letter_text = _render_cover_letter(
        cover_letter_template.read_text(encoding="utf-8"),
        record,
        author_name,
    )
    notes_text = notes_template.read_text(encoding="utf-8")
    cv_text = cv_template.read_text(encoding="utf-8")

    vacancy_path.write_text(vacancy_text, encoding="utf-8")
    cover_letter_path.write_text(cover_letter_text, encoding="utf-8")
    notes_path.write_text(notes_text, encoding="utf-8")
    cv_path.write_text(cv_text, encoding="utf-8")

    workspace = workspace_root()
    record.resume_ref = _safe_relative_path(cv_path, workspace)
    record.cover_letter_ref = _safe_relative_path(cover_letter_path, workspace)
    db.commit()

    return GenerateDocumentsResult(
        vacancy_dir=_safe_relative_path(target_dir, workspace),
        vacancy_path=_safe_relative_path(vacancy_path, workspace),
        cv_path=_safe_relative_path(cv_path, workspace),
        cover_letter_path=_safe_relative_path(cover_letter_path, workspace),
        notes_path=_safe_relative_path(notes_path, workspace),
    )


@app.get(
    "/workspace-file",
    response_model=WorkspaceFileReadResult,
    tags=["workspace"],
    summary="Read one editable file under applications/",
)
def read_workspace_file(
    path: str = Query(..., min_length=1),
    _: None = Depends(require_write_access),
) -> WorkspaceFileReadResult:
    target = _resolve_workspace_file_path(path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return WorkspaceFileReadResult(
        path=_safe_relative_path(target, workspace_root()), content=target.read_text(encoding="utf-8")
    )


@app.put(
    "/workspace-file",
    response_model=WorkspaceFileReadResult,
    tags=["workspace"],
    summary="Write one editable file under applications/",
)
def write_workspace_file(
    payload: WorkspaceFileWriteRequest,
    _: None = Depends(require_write_access),
) -> WorkspaceFileReadResult:
    target = _resolve_workspace_file_path(payload.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload.content, encoding="utf-8")
    return WorkspaceFileReadResult(path=_safe_relative_path(target, workspace_root()), content=payload.content)


def _summarize_process_output(text: str, max_chars: int) -> str:
    text = text.strip()
    if not text:
        return ""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text

    marker = "\n\n... output truncated ...\n\n"
    if max_chars <= len(marker) + 2:
        return text[:max_chars]

    visible = max_chars - len(marker)
    head = visible // 2
    tail = visible - head
    return f"{text[:head]}{marker}{text[-tail:]}"


@app.post(
    "/run-discovery",
    response_model=DiscoveryRunResult,
    tags=["imports"],
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
        stderr = _summarize_process_output(completed.stderr, settings.discovery_log_max_chars)
        raise HTTPException(
            status_code=500,
            detail=f"Discovery script failed with exit code {completed.returncode}. stderr: {stderr}",
        )

    return DiscoveryRunResult(
        exit_code=completed.returncode,
        command=command,
        stdout=_summarize_process_output(completed.stdout, settings.discovery_log_max_chars),
        stderr=_summarize_process_output(completed.stderr, settings.discovery_log_max_chars),
    )


