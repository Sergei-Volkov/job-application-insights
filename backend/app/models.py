from sqlalchemy import Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class JobApplication(Base):
    __tablename__ = "job_applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    selected: Mapped[str] = mapped_column(String(10), default="no")
    date_found: Mapped[str] = mapped_column(String(32), default="")
    date_applied: Mapped[str] = mapped_column(String(32), default="")
    company: Mapped[str] = mapped_column(String(255), default="")
    role: Mapped[str] = mapped_column(String(255), default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(255), default="")
    remote_type: Mapped[str] = mapped_column(String(255), default="")
    fit: Mapped[str] = mapped_column(String(64), default="")
    fit_score: Mapped[int] = mapped_column(Integer, default=0)
    link: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(128), default="")
    next_step: Mapped[str] = mapped_column(Text, default="")
    follow_up_date: Mapped[str] = mapped_column(String(32), default="")
    resume_ref: Mapped[str] = mapped_column(Text, default="")
    cover_letter_ref: Mapped[str] = mapped_column(Text, default="")
    match_profile: Mapped[str] = mapped_column(String(32), default="")
    first_seen_at: Mapped[str] = mapped_column(String(32), default="")
    last_seen_at: Mapped[str] = mapped_column(String(32), default="")
    listing_fingerprint: Mapped[str] = mapped_column(Text, default="")
    change_note: Mapped[str] = mapped_column(Text, default="")
    score_breakdown: Mapped[dict | None] = mapped_column(JSON, nullable=True, default=None)
    notes: Mapped[str] = mapped_column(Text, default="")
