import re
from collections import Counter
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..dependencies import get_db
from ..models import JobApplication
from ..schemas import SkillGapList, StatsOut, TrendList

router = APIRouter(tags=["analytics"])


@router.get(
    "/stats",
    response_model=StatsOut,
    summary="Get top-level application metrics",
)
def stats(db: Session = Depends(get_db)) -> StatsOut:
    total = db.query(func.count(JobApplication.id)).scalar() or 0

    status_rows = (
        db.query(
            func.lower(func.coalesce(JobApplication.status, "unknown")).label("status"),
            func.count(JobApplication.id).label("count"),
        )
        .group_by(func.lower(func.coalesce(JobApplication.status, "unknown")))
        .all()
    )
    by_status = {row.status.strip(): row.count for row in status_rows}

    stage_rows = (
        db.query(
            func.lower(func.coalesce(JobApplication.next_step, "unknown")).label("next_step"),
            func.count(JobApplication.id).label("count"),
        )
        .group_by(func.lower(func.coalesce(JobApplication.next_step, "unknown")))
        .all()
    )
    by_stage = {row.next_step.strip(): row.count for row in stage_rows}

    return {
        "total_applications": total,
        "by_status": by_status,
        "by_stage": by_stage,
    }


@router.get(
    "/missing-skills",
    response_model=SkillGapList,
    summary="Extract missing skills from notes",
)
def missing_skills(db: Session = Depends(get_db)) -> SkillGapList:
    marker = r"missing or adjacent tools:"
    found: list[str] = []

    for (notes,) in db.query(JobApplication.notes).all():
        text = (notes or "").strip()
        m = re.search(marker, text, re.IGNORECASE)
        if not m:
            continue

        raw = text[m.end():]
        # Stop at the next recognised section header (line starting with a capital word
        # followed by a colon) so we don't slurp unrelated content.
        section_end = re.search(r"\n[A-Z]", raw)
        if section_end:
            raw = raw[: section_end.start()]
        parts = [p.strip(" .") for p in raw.split(",") if p.strip()]
        found.extend(parts)

    if not found:
        found = [s.strip() for s in settings.default_missing_skills.split(",") if s.strip()]

    gap_counter = Counter(found)
    ordered = [{"skill": k, "count": v} for k, v in gap_counter.most_common()]
    return {"items": ordered}


@router.get(
    "/trend",
    response_model=TrendList,
    summary="Aggregate application discovery by ISO week",
)
def trend(db: Session = Depends(get_db)) -> TrendList:
    week_counter: Counter = Counter()
    for (date_str,) in db.query(JobApplication.date_found).filter(JobApplication.date_found != "").all():
        date_str = (date_str or "").strip()
        if not date_str:
            continue
        try:
            week_counter[datetime.strptime(date_str, "%Y-%m-%d").strftime("%G-W%V")] += 1
        except ValueError:
            continue

    items = [{"week": w, "count": c} for w, c in sorted(week_counter.items())]
    return {"items": items}
