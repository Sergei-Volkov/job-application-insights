"""Backfill score_breakdown from change_note for legacy rows

Rows inserted before score_breakdown became a first-class JSON column may
have their score data stored only in change_note as a JSON string.
This migration copies valid JSON from change_note into score_breakdown
for any row where score_breakdown is currently NULL.

After this migration the display fallback in _to_job_application_out
(``record.score_breakdown or record.change_note``) is no longer needed
and has been removed from the application code.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-01

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, change_note FROM job_applications "
            "WHERE score_breakdown IS NULL AND change_note IS NOT NULL AND change_note != ''"
        )
    ).fetchall()

    for row_id, change_note in rows:
        if not change_note:
            continue
        try:
            parsed = json.loads(change_note)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        conn.execute(
            sa.text(
                "UPDATE job_applications SET score_breakdown = :val WHERE id = :id"
            ),
            {"val": json.dumps(parsed), "id": row_id},
        )


def downgrade() -> None:
    # Backfill is non-destructive; no action needed on downgrade.
    pass
