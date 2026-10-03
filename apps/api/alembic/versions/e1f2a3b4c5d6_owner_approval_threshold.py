"""persist the owner-controlled financial approval threshold

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_state",
        sa.Column(
            "approval_threshold_cents",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("250"),
        ),
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("system_state", recreate="always") as batch_op:
            batch_op.drop_column("approval_threshold_cents")
        return
    op.drop_column("system_state", "approval_threshold_cents")
