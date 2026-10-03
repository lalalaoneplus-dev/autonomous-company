"""persist the singleton recurring CEO schedule generation fence

Revision ID: c7d8e9f0a123
Revises: b6e7f8a9c012
"""

from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "c7d8e9f0a123"
down_revision: Union[str, Sequence[str], None] = "b6e7f8a9c012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ceo_schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("generation", sa.String(length=36), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("remaining_runs", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("interval_seconds", sa.Integer(), nullable=False, server_default=sa.text("3600")),
        sa.Column("running", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("run_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generation"),
    )
    op.execute(
        sa.text(
            "INSERT INTO ceo_schedules "
            "(id, generation, active, remaining_runs, interval_seconds, running, created_at, updated_at) "
            "VALUES (1, :generation, FALSE, 0, 3600, FALSE, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ).bindparams(generation=str(uuid4()))
    )


def downgrade() -> None:
    op.drop_table("ceo_schedules")
