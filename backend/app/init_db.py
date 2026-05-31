import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine
from . import models as _models  # noqa: F401 — registers ORM classes on Base.metadata


def ensure_columns(db: Session) -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    existing = {row[1] for row in db.execute(text("PRAGMA table_info(job_applications)")).fetchall()}
    wanted = {
        "resume_ref": "TEXT DEFAULT ''",
        "cover_letter_ref": "TEXT DEFAULT ''",
        "match_profile": "TEXT DEFAULT ''",
        "first_seen_at": "TEXT DEFAULT ''",
        "last_seen_at": "TEXT DEFAULT ''",
        "listing_fingerprint": "TEXT DEFAULT ''",
        "change_note": "TEXT DEFAULT ''",
        "score_breakdown": "TEXT DEFAULT ''",
    }

    # Validate column names and SQL types against compile-time allowlists before
    # interpolating into the ALTER TABLE statement.  Both values are static dicts
    # defined above, but this guard prevents the unsafe pattern from silently
    # surviving if the dict is ever made dynamic.
    _safe_col = re.compile(r"^[a-z][a-z0-9_]*$")
    _safe_type = re.compile(r"^[A-Z]+(\s+DEFAULT\s+'[^']*')?$")

    for column, sql_type in wanted.items():
        if not _safe_col.match(column):
            raise ValueError(f"Unsafe column name rejected: {column!r}")
        if not _safe_type.match(sql_type):
            raise ValueError(f"Unsafe SQL type rejected: {sql_type!r}")
        if column not in existing:
            db.execute(text(f"ALTER TABLE job_applications ADD COLUMN {column} {sql_type}"))

    db.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_job_applications_link_nonempty "
            "ON job_applications(link) WHERE link <> ''"
        )
    )
    # Query-pattern indexes
    db.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_job_applications_status "
        "ON job_applications(lower(status))"
    ))
    db.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_job_applications_company_role "
        "ON job_applications(lower(company), lower(role))"
    ))
    db.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_job_applications_fit_score "
        "ON job_applications(fit_score DESC, id ASC)"
    ))
    db.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_job_applications_date_found "
        "ON job_applications(date_found)"
    ))
    db.commit()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_columns(db)


if __name__ == "__main__":
    init_db()
    print("Database schema initialized.")
