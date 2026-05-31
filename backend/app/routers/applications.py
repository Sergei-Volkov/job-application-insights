import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..dependencies import get_db, require_write_access
from ..helpers import today_iso
from ..models import JobApplication
from ..schemas import JobApplicationOut, JobApplicationUpdate, JobApplicationUpsert, ScoreBreakdownOut

router = APIRouter(tags=["applications"])


def _normalize_key(value: str | None) -> str:
    return (value or "").strip().lower()


def _listing_fingerprint(values: list[str]) -> str:
    joined = "||".join((v or "").strip() for v in values)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _parse_score_breakdown(raw: dict | str | None) -> ScoreBreakdownOut | None:
    """Convert a score_breakdown value (dict from JSON column, or legacy str) into ScoreBreakdownOut."""
    if raw is None:
        return None
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None
        try:
            parsed: object = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        payload: dict = parsed  # type: ignore[assignment]
    elif isinstance(raw, dict):
        payload = raw
    else:
        return None

    return ScoreBreakdownOut(
        score=payload.get("score") if isinstance(payload.get("score"), int) else None,
        fit=str(payload.get("fit") or "").strip(),
        matched_keywords=[str(part).strip() for part in payload.get("matched_keywords", []) if str(part).strip()]
        if isinstance(payload.get("matched_keywords"), list)
        else [],
        missing_skills=[str(part).strip() for part in payload.get("missing_skills", []) if str(part).strip()]
        if isinstance(payload.get("missing_skills"), list)
        else [],
        fit_notes=str(payload.get("fit_notes") or "").strip(),
    )


def _is_scoring_json(text: str) -> bool:
    """Return True if text is a JSON dict that looks like a scoring blob."""
    raw = (text or "").strip()
    if not raw or not raw.startswith("{"):
        return False
    try:
        parsed = json.loads(raw)
        return isinstance(parsed, dict) and "score" in parsed
    except (json.JSONDecodeError, TypeError):
        return False


def _normalize_score_breakdown(value: str | dict | None) -> dict | None:
    """Parse a JSON string to dict; return dict as-is; return None for empty/invalid."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _to_job_application_out(record: JobApplication) -> JobApplicationOut:
    return JobApplicationOut(
        id=record.id,
        selected=record.selected,
        date_found=record.date_found,
        date_applied=record.date_applied,
        company=record.company,
        role=record.role,
        location=record.location,
        source=record.source,
        remote_type=record.remote_type,
        fit=record.fit,
        fit_score=record.fit_score,
        link=record.link,
        status=record.status,
        next_step=record.next_step,
        follow_up_date=record.follow_up_date,
        resume_ref=record.resume_ref,
        cover_letter_ref=record.cover_letter_ref,
        match_profile=record.match_profile,
        first_seen_at=record.first_seen_at,
        last_seen_at=record.last_seen_at,
        listing_fingerprint=record.listing_fingerprint,
        change_note=record.change_note,
        notes=record.notes,
        score_breakdown=_parse_score_breakdown(record.score_breakdown or record.change_note),  # type: ignore[arg-type]
    )


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
    source: str | None = Query(default=None),
    min_fit_score: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=100_000),
    db: Session = Depends(get_db),
) -> list[JobApplicationOut]:
    query = db.query(JobApplication)

    if status:
        normalized = status.strip().lower()
        if normalized:
            query = query.filter(func.lower(JobApplication.status) == normalized)
    if source:
        normalized_source = source.strip().lower()
        if normalized_source:
            query = query.filter(func.lower(JobApplication.source) == normalized_source)
    if min_fit_score is not None:
        query = query.filter(JobApplication.fit_score >= min_fit_score)

    rows = query.order_by(JobApplication.fit_score.desc(), JobApplication.id.asc()).offset(offset).limit(limit).all()
    return [_to_job_application_out(row) for row in rows]


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
    today = today_iso()

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

    # Extract scoring JSON from change_note into dedicated column (backward compat only;
    # new engine sends score_breakdown directly so only copy when not already provided)
    if not payload_data.get("score_breakdown") and _is_scoring_json(payload_data.get("change_note", "")):
        payload_data["score_breakdown"] = payload_data["change_note"]

    # Normalize to dict before storing (JSON column; incoming value is a JSON string from the engine)
    payload_data["score_breakdown"] = _normalize_score_breakdown(payload_data.get("score_breakdown"))

    record = JobApplication(**payload_data)
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Application already exists")

    db.refresh(record)
    return _to_job_application_out(record)


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
    today = today_iso()

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

    # Extract scoring JSON into dedicated column so it survives change_note overwrite
    # (backward compat: new engine sends score_breakdown directly)
    if not payload_data.get("score_breakdown") and _is_scoring_json(payload_data.get("change_note", "")):
        payload_data["score_breakdown"] = payload_data["change_note"]

    # Normalize incoming JSON string to dict before any DB write
    payload_data["score_breakdown"] = _normalize_score_breakdown(payload_data.get("score_breakdown"))

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

        # Preserve existing score_breakdown if incoming upsert has none
        if payload_data.get("score_breakdown") is None:
            payload_data["score_breakdown"] = record.score_breakdown

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
        elif not payload_data.get("change_note"):
            payload_data["change_note"] = record.change_note or ""

        # Preserve existing score_breakdown if incoming has none (mirrors main upsert path)
        if payload_data.get("score_breakdown") is None:
            payload_data["score_breakdown"] = record.score_breakdown

        for field, value in payload_data.items():
            setattr(record, field, value)
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail="Failed to update existing application") from exc

    db.refresh(record)
    return _to_job_application_out(record)


@router.delete(
    "/applications/{application_id}",
    status_code=204,
    summary="Delete one application",
    description="Permanently removes a tracked application. This action cannot be undone.",
)
def delete_application(
    application_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_write_access),
) -> None:
    record = db.query(JobApplication).filter(JobApplication.id == application_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Application not found")
    db.delete(record)
    db.commit()


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

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflict while updating application") from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update application") from exc

    db.refresh(record)
    return _to_job_application_out(record)
