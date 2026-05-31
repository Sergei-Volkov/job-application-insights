"""Convert score_breakdown column to JSON type

Empty-string values are nullified so the JSON type's auto-deserialization
never encounters a bare empty string (which would raise json.JSONDecodeError).
SQLite maps JSON to TEXT at the DDL level, so no storage format changes;
only SQLAlchemy's automatic serialize/deserialize behaviour is gained.
PostgreSQL gets a native JSON column via batch_alter_table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullify empty score_breakdown values so json.loads never sees bare ''.
    op.execute(
        "UPDATE job_applications "
        "SET score_breakdown = NULL "
        "WHERE score_breakdown IS NULL OR TRIM(score_breakdown) = ''"
    )
    with op.batch_alter_table('job_applications', schema=None) as batch_op:
        batch_op.alter_column(
            'score_breakdown',
            existing_type=sa.Text(),
            type_=sa.JSON(),
            nullable=True,
            server_default=None,
            existing_server_default=sa.text("''"),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table('job_applications', schema=None) as batch_op:
        batch_op.alter_column(
            'score_breakdown',
            existing_type=sa.JSON(),
            type_=sa.Text(),
            nullable=False,
            server_default=sa.text("''"),
            existing_server_default=None,
            existing_nullable=True,
        )
    op.execute(
        "UPDATE job_applications SET score_breakdown = '' WHERE score_breakdown IS NULL"
    )
