"""make the paper treasury opening transaction idempotent

Revision ID: d0e1f2a3b4c5
Revises: c7d8e9f0a123
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c7d8e9f0a123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    opening_count = op.get_bind().execute(
        sa.text(
            "SELECT COUNT(*) FROM ledger_transactions "
            "WHERE external_reference = :external_reference"
        ),
        {"external_reference": "paper-opening"},
    ).scalar_one()
    if opening_count > 1:
        raise RuntimeError(
            "Duplicate paper-opening ledger records detected; reconcile "
            "ledger_transactions rows with external_reference='paper-opening' "
            "before applying d0e1f2a3b4c5. Ledger history was not modified."
        )
    op.create_index(
        "uq_ledger_transactions_paper_opening",
        "ledger_transactions",
        ["external_reference"],
        unique=True,
        sqlite_where=sa.text("external_reference = 'paper-opening'"),
        postgresql_where=sa.text("external_reference = 'paper-opening'"),
    )


def downgrade() -> None:
    op.drop_index("uq_ledger_transactions_paper_opening", table_name="ledger_transactions")
