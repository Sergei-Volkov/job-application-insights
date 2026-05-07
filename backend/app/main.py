from collections import Counter
from contextlib import asynccontextmanager
import csv
from datetime import datetime
from pathlib import Path
import subprocess
import sys
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, func, text
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine
from .models import JobApplication
from .schemas import (
    DiscoveryRunRequest,
    DiscoveryRunResult,
    JobApplicationOut,
    JobApplicationUpdate,
    JobApplicationUpsert,
    SkillGapList,
    StatsOut,
    SyncResult,
    TrendList,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_columns(db)
        seed_from_csv_if_needed(db)
    yield


app = FastAPI(
    title="Job Application Insights API",
    version="0.3.0",
    summary="Track job applications, ingest discovered roles, and visualize your pipeline.",
    description=(
        "A DB-first API for a personal job search workflow. Use it to ingest jobs from a discovery "
        "worker, update application state from the UI, and analyze status, skill gaps, and trends."
    ),
    openapi_tags=[
        {"name": "system", "description": "Health and operational endpoints."},
        {"name": "applications", "description": "CRUD-style endpoints for tracked job applications."},
        {"name": "imports", "description": "Import or upsert jobs from external discovery flows."},
        {"name": "analytics", "description": "Aggregated views used by the dashboard."},
    ],
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def tracker_path() -> Path:
    return Path(settings.csv_path)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_from_project_root(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (project_root() / path).resolve()


def _to_int(value: str | None) -> int:
    try:
        return int((value or "0").strip())
    except ValueError:
        return 0


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


def ensure_columns(db: Session) -> None:
    # Tiny migration helper for SQLite so existing app.db files gain new columns.
    if not settings.database_url.startswith("sqlite"):
        return

    existing = {row[1] for row in db.execute(text("PRAGMA table_info(job_applications)")).fetchall()}
    wanted = {
        "resume_ref": "TEXT DEFAULT ''",
        "cover_letter_ref": "TEXT DEFAULT ''",
    }

    for column, sql_type in wanted.items():
        if column not in existing:
            db.execute(text(f"ALTER TABLE job_applications ADD COLUMN {column} {sql_type}"))
    db.commit()


def seed_from_csv_if_needed(db: Session) -> None:
    existing = db.query(func.count(JobApplication.id)).scalar() or 0
    if existing > 0:
        return

    path = tracker_path()
    if not path.exists():
        return

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            db.add(
                JobApplication(
                    selected=(row.get("selected") or "no"),
                    date_found=(row.get("date_found") or ""),
                    date_applied=(row.get("date_applied") or ""),
                    company=(row.get("company") or ""),
                    role=(row.get("role") or ""),
                    location=(row.get("location") or ""),
                    source=(row.get("source") or ""),
                    remote_type=(row.get("remote_type") or ""),
                    fit=(row.get("fit") or ""),
                    fit_score=_to_int(row.get("fit_score")),
                    link=(row.get("link") or ""),
                    status=(row.get("status") or ""),
                    next_step=(row.get("next_step") or ""),
                    follow_up_date=(row.get("follow_up_date") or ""),
                    resume_ref="",
                    cover_letter_ref="",
                    notes=(row.get("notes") or ""),
                )
            )
    db.commit()


def sync_from_csv(db: Session) -> dict[str, int]:
    path = tracker_path()
    if not path.exists():
        return {"added": 0, "updated": 0}

    added = 0
    updated = 0
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            link = (row.get("link") or "").strip()
            company = (row.get("company") or "").strip()
            role = (row.get("role") or "").strip()

            existing = find_existing_application(db, company=company, role=role, link=link)

            if existing is None:
                db.add(
                    JobApplication(
                        selected=(row.get("selected") or "no"),
                        date_found=(row.get("date_found") or ""),
                        date_applied=(row.get("date_applied") or ""),
                        company=company,
                        role=role,
                        location=(row.get("location") or ""),
                        source=(row.get("source") or ""),
                        remote_type=(row.get("remote_type") or ""),
                        fit=(row.get("fit") or ""),
                        fit_score=_to_int(row.get("fit_score")),
                        link=link,
                        status=(row.get("status") or ""),
                        next_step=(row.get("next_step") or ""),
                        follow_up_date=(row.get("follow_up_date") or ""),
                        resume_ref="",
                        cover_letter_ref="",
                        notes=(row.get("notes") or ""),
                    )
                )
                added += 1
                continue

            existing.selected = row.get("selected") or existing.selected or "no"
            existing.date_found = row.get("date_found") or existing.date_found or ""
            existing.date_applied = row.get("date_applied") or existing.date_applied or ""
            existing.company = company or existing.company
            existing.role = role or existing.role
            existing.location = row.get("location") or existing.location or ""
            existing.source = row.get("source") or existing.source or ""
            existing.remote_type = row.get("remote_type") or existing.remote_type or ""
            existing.fit = row.get("fit") or existing.fit or ""
            existing.fit_score = (
                _to_int(row.get("fit_score")) if row.get("fit_score", "").strip() else existing.fit_score
            )
            existing.link = link or existing.link
            existing.status = row.get("status") or existing.status or ""
            existing.next_step = row.get("next_step") or existing.next_step or ""
            existing.follow_up_date = row.get("follow_up_date") or existing.follow_up_date or ""
            existing.notes = row.get("notes") or existing.notes or ""
            updated += 1

    db.commit()
    return {"added": added, "updated": updated}


@app.get("/health", tags=["system"], summary="Check API health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
        query = query.filter(JobApplication.status.ilike(status))
    if min_fit_score is not None:
        query = query.filter(JobApplication.fit_score >= min_fit_score)

    return query.order_by(JobApplication.fit_score.desc(), JobApplication.id.asc()).offset(offset).limit(limit).all()


@app.post(
    "/applications/upsert",
    response_model=JobApplicationOut,
    tags=["imports", "applications"],
    summary="Create or update one application",
    description="Upserts one application by link, or by company + role when link is missing.",
)
def upsert_application(payload: JobApplicationUpsert, db: Session = Depends(get_db)) -> JobApplicationOut:
    record = find_existing_application(db, company=payload.company, role=payload.role, link=payload.link)

    if record is None:
        record = JobApplication(**payload.model_dump())
        db.add(record)
    else:
        for field, value in payload.model_dump().items():
            setattr(record, field, value)

    db.commit()
    db.refresh(record)
    return record


@app.patch(
    "/applications/{application_id}",
    response_model=JobApplicationOut,
    tags=["applications"],
    summary="Patch editable fields on one application",
)
def patch_application(
    application_id: int, payload: JobApplicationUpdate, db: Session = Depends(get_db)
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


@app.post(
    "/sync-from-csv",
    response_model=SyncResult,
    tags=["imports"],
    summary="Import or refresh rows from CSV",
)
def sync_from_csv_endpoint(db: Session = Depends(get_db)) -> SyncResult:
    return sync_from_csv(db)


@app.post(
    "/run-discovery",
    response_model=DiscoveryRunResult,
    tags=["imports"],
    summary="Trigger the external discovery script",
    description="Runs the existing job finder script and lets it upsert discovered roles back into this API.",
)
def run_discovery(payload: DiscoveryRunRequest) -> DiscoveryRunResult:
    if not settings.discovery_cv_path.strip():
        raise HTTPException(
            status_code=400,
            detail="DISCOVERY_CV_PATH is not set. Configure it in .env or environment before running discovery.",
        )

    script_path = resolve_from_project_root(settings.discovery_script_path)
    cv_path = resolve_from_project_root(settings.discovery_cv_path)

    if not script_path.exists():
        raise HTTPException(status_code=500, detail=f"Discovery script not found: {script_path}")
    if not cv_path.exists() or not cv_path.is_file():
        raise HTTPException(status_code=500, detail=f"Discovery CV not found: {cv_path}")

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
        settings.discovery_api_base_url,
    ]
    if payload.include_stretch:
        command.append("--include-stretch")

    try:
        completed = subprocess.run(
            command,
            cwd=str(script_path.parent.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail=f"Discovery run timed out after {exc.timeout} seconds") from exc

    return DiscoveryRunResult(
        exit_code=completed.returncode,
        command=command,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


@app.get(
    "/stats",
    response_model=StatsOut,
    tags=["analytics"],
    summary="Get top-level application metrics",
)
def stats(db: Session = Depends(get_db)) -> StatsOut:
    rows = db.query(JobApplication).all()
    total = len(rows)

    status_counter = Counter((r.status or "unknown").strip().lower() for r in rows)
    stage_counter = Counter((r.next_step or "unknown").strip().lower() for r in rows)

    return {
        "total_applications": total,
        "by_status": dict(status_counter),
        "by_stage": dict(stage_counter),
    }


@app.get(
    "/missing-skills",
    response_model=SkillGapList,
    tags=["analytics"],
    summary="Extract missing skills from notes",
)
def missing_skills(db: Session = Depends(get_db)) -> SkillGapList:
    marker = "missing or adjacent tools:"
    found: list[str] = []

    for row in db.query(JobApplication).all():
        text = (row.notes or "").strip()
        lower = text.lower()
        if marker not in lower:
            continue

        idx = lower.index(marker)
        raw = text[idx + len(marker) :]
        parts = [p.strip(" .") for p in raw.split(",") if p.strip()]
        found.extend(parts)

    if not found:
        found = [s.strip() for s in settings.default_missing_skills.split(",") if s.strip()]

    gap_counter = Counter(found)
    ordered = [{"skill": k, "count": v} for k, v in gap_counter.most_common()]
    return {"items": ordered}


@app.get(
    "/trend",
    response_model=TrendList,
    tags=["analytics"],
    summary="Aggregate application discovery by ISO week",
)
def trend(db: Session = Depends(get_db)) -> TrendList:
    week_counter: Counter = Counter()
    for row in db.query(JobApplication).all():
        date_str = (row.date_found or "").strip()
        if not date_str:
            continue
        try:
            week_counter[datetime.strptime(date_str, "%Y-%m-%d").strftime("%G-W%V")] += 1
        except ValueError:
            continue

    items = [{"week": w, "count": c} for w, c in sorted(week_counter.items())]
    return {"items": items}
