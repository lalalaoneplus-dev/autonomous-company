"""persist receipt-backed security gates and non-executable project links

Revision ID: 9d0f0e3b4a11
Revises: 7bc41cc25c11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9d0f0e3b4a11"
down_revision: Union[str, Sequence[str], None] = "7bc41cc25c11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _alter_demand_evidence_status(target_type: sa.types.TypeEngine) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("demand_evidence", recreate="always") as batch_op:
            batch_op.alter_column(
                "verification_status",
                existing_type=sa.String(length=30),
                type_=target_type,
            )
        return

    op.alter_column(
        "demand_evidence",
        "verification_status",
        existing_type=sa.String(length=30),
        type_=target_type,
    )


def _add_project_gate_columns() -> None:
    columns = (
        sa.Column("negotiation_id", sa.String(length=36), nullable=True),
        sa.Column("execution_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("projects", recreate="always") as batch_op:
            for column in columns:
                batch_op.add_column(column)
            batch_op.create_foreign_key(
                "fk_projects_negotiation_id",
                "demand_negotiations",
                ["negotiation_id"],
                ["id"],
            )
        return

    for column in columns:
        op.add_column("projects", column)
    op.create_foreign_key(
        "fk_projects_negotiation_id",
        "projects",
        "demand_negotiations",
        ["negotiation_id"],
        ["id"],
    )


def _drop_project_gate_columns() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("projects", recreate="always") as batch_op:
            batch_op.drop_constraint("fk_projects_negotiation_id", type_="foreignkey")
            batch_op.drop_column("execution_enabled")
            batch_op.drop_column("negotiation_id")
        return

    op.drop_constraint("fk_projects_negotiation_id", "projects", type_="foreignkey")
    op.drop_column("projects", "execution_enabled")
    op.drop_column("projects", "negotiation_id")


def upgrade() -> None:
    # These defaults keep existing imported rows honest and usable.  They do
    # not turn legacy rows into verified evidence or executable work.
    op.add_column(
        "demand_evidence",
        sa.Column("verification_receipt", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column("demand_evidence", sa.Column("source_verified_at", sa.DateTime(timezone=True), nullable=True))
    _alter_demand_evidence_status(sa.String(length=40))
    op.execute(
        sa.text(
            "UPDATE demand_evidence SET verification_status = 'legacy_unverified' "
            "WHERE verification_status != 'imported_unverified'"
        )
    )
    op.add_column(
        "demand_negotiations",
        sa.Column("external_receipt", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "program_scopes",
        sa.Column("test_plan", sa.Text(), nullable=False, server_default=sa.text("''")),
    )
    _add_project_gate_columns()


def downgrade() -> None:
    _drop_project_gate_columns()
    op.drop_column("program_scopes", "test_plan")
    op.drop_column("demand_negotiations", "external_receipt")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("demand_evidence", recreate="always") as batch_op:
            batch_op.alter_column(
                "verification_status",
                existing_type=sa.String(length=40),
                type_=sa.String(length=30),
            )
    else:
        op.alter_column(
            "demand_evidence",
            "verification_status",
            existing_type=sa.String(length=40),
            type_=sa.String(length=30),
        )
    op.drop_column("demand_evidence", "source_verified_at")
    op.drop_column("demand_evidence", "verification_receipt")
