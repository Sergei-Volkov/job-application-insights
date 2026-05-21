from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine


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
    }

    for column, sql_type in wanted.items():
        if column not in existing:
            db.execute(text(f"ALTER TABLE job_applications ADD COLUMN {column} {sql_type}"))

    db.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_job_applications_link_nonempty "
            "ON job_applications(link) WHERE link <> ''"
        )
    )
    db.commit()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_columns(db)


if __name__ == "__main__":
    init_db()
    print("Database schema initialized.")
