from datetime import datetime
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..dependencies import get_db, require_write_access
from ..models import JobApplication
from ..schemas import JobApplicationOut, JobApplicationUpdate, JobApplicationUpsert

router = APIRouter(tags=["applications"])


def _normalize_key(value: str | None) -> str:
    return (value or "").strip().lower()


def _listing_fingerprint(values: list[str]) -> str:
    joined = "||".join((v or "").strip() for v in values)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


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


@router.get(
    "/applications",
    response_model=list[JobApplicationOut],
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


@router.post(
    "/applications",
    response_model=JobApplicationOut,
    status_code=status.HTTP_201_CREATED,
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


@router.post(
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


@router.patch(
    "/applications/{application_id}",
    response_model=JobApplicationOut,
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
