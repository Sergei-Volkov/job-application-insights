"""Initial schema baseline

Revision ID: 0001
Revises:
Create Date: 2026-05-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'job_applications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('selected', sa.String(length=10), server_default=sa.text("'no'"), nullable=False),
        sa.Column('date_found', sa.String(length=32), server_default=sa.text("''"), nullable=False),
        sa.Column('date_applied', sa.String(length=32), server_default=sa.text("''"), nullable=False),
        sa.Column('company', sa.String(length=255), server_default=sa.text("''"), nullable=False),
        sa.Column('role', sa.String(length=255), server_default=sa.text("''"), nullable=False),
        sa.Column('location', sa.String(length=255), server_default=sa.text("''"), nullable=False),
        sa.Column('source', sa.String(length=255), server_default=sa.text("''"), nullable=False),
        sa.Column('remote_type', sa.String(length=255), server_default=sa.text("''"), nullable=False),
        sa.Column('fit', sa.String(length=64), server_default=sa.text("''"), nullable=False),
        sa.Column('fit_score', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('link', sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column('status', sa.String(length=128), server_default=sa.text("''"), nullable=False),
        sa.Column('next_step', sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column('follow_up_date', sa.String(length=32), server_default=sa.text("''"), nullable=False),
        sa.Column('resume_ref', sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column('cover_letter_ref', sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column('match_profile', sa.String(length=32), server_default=sa.text("''"), nullable=False),
        sa.Column('first_seen_at', sa.String(length=32), server_default=sa.text("''"), nullable=False),
        sa.Column('last_seen_at', sa.String(length=32), server_default=sa.text("''"), nullable=False),
        sa.Column('listing_fingerprint', sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column('change_note', sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column('score_breakdown', sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column('notes', sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_job_applications_id'), 'job_applications', ['id'], unique=False)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_job_applications_link_nonempty "
        "ON job_applications(link) WHERE link <> ''"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_applications_status "
        "ON job_applications(lower(status))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_applications_company_role "
        "ON job_applications(lower(company), lower(role))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_applications_fit_score "
        "ON job_applications(fit_score DESC, id ASC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_job_applications_date_found "
        "ON job_applications(date_found)"
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_job_applications_id'), table_name='job_applications')
    op.drop_table('job_applications')
