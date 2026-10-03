"""persist deterministic policy budgets, allowlists, and rate-limit keys

Revision ID: b6e7f8a9c012
Revises: 9d0f0e3b4a11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6e7f8a9c012"
down_revision: Union[str, Sequence[str], None] = "9d0f0e3b4a11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _paper_outcome_from_evidence(table: str) -> None:
    # JSON extraction differs between SQLite and PostgreSQL.  Existing rows
    # are conservatively false unless they carry the explicit paper-only
    # payment marker; no inferred payout becomes revenue.
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        status = "json_extract(payment_evidence, '$.status') = 'PAPER_ONLY'"
    else:
        status = "payment_evidence->>'status' = 'PAPER_ONLY'"
    op.execute(
        sa.text(
            f"UPDATE {table} SET paper_outcome = CASE WHEN {status} THEN TRUE ELSE FALSE END"
        )
    )


def _set_paper_outcome_default(table: str, default: sa.sql.elements.TextClause | None) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table, recreate="always") as batch_op:
            batch_op.alter_column(
                "paper_outcome",
                server_default=default,
                existing_type=sa.Boolean(),
                existing_nullable=False,
            )
        return

    op.alter_column(
        table,
        "paper_outcome",
        server_default=default,
        existing_type=sa.Boolean(),
        existing_nullable=False,
    )


def _add_model_usage_columns() -> None:
    columns = (
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("model_cost_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("api_cost_cents", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("model_usage", recreate="always") as batch_op:
            for column in columns:
                batch_op.add_column(column)
            batch_op.create_foreign_key(
                "fk_model_usage_project_id",
                "projects",
                ["project_id"],
                ["id"],
            )
        return

    for column in columns:
        op.add_column("model_usage", column)
    op.create_foreign_key(
        "fk_model_usage_project_id",
        "model_usage",
        "projects",
        ["project_id"],
        ["id"],
    )


def _drop_model_usage_columns() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("model_usage", recreate="always") as batch_op:
            batch_op.drop_constraint("fk_model_usage_project_id", type_="foreignkey")
            for column in ("api_cost_cents", "model_cost_cents", "project_id", "model_name"):
                batch_op.drop_column(column)
        return

    op.drop_constraint("fk_model_usage_project_id", "model_usage", type_="foreignkey")
    for column in ("api_cost_cents", "model_cost_cents", "project_id", "model_name"):
        op.drop_column("model_usage", column)


def _drop_columns(table: str, columns: tuple[str, ...]) -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table(table, recreate="always") as batch_op:
            for column in columns:
                batch_op.drop_column(column)
        return

    for column in columns:
        op.drop_column(table, column)


def upgrade() -> None:
    op.add_column("system_state", sa.Column("api_cost_limit_cents", sa.Integer(), nullable=False, server_default=sa.text("1000")))
    op.add_column("system_state", sa.Column("api_cost_cents", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("system_state", sa.Column("category_allowlist", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("system_state", sa.Column("category_denylist", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("system_state", sa.Column("category_limits_cents", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
    op.add_column("system_state", sa.Column("counterparty_allowlist", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("system_state", sa.Column("counterparty_denylist", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("system_state", sa.Column("domain_allowlist", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column("system_state", sa.Column("domain_denylist", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    op.add_column(
        "system_state",
        sa.Column(
            "rate_limits",
            sa.JSON(),
            nullable=False,
            # Spaces after ':' prevent SQLAlchemy TextClause from treating
            # JSON number values as bind parameters in SQLite DDL.
            server_default=sa.text("'{\"*\": {\"max_requests\": 60, \"window_seconds\": 60}}'"),
        ),
    )
    op.add_column("policy_decisions", sa.Column("rate_limit_key", sa.String(length=120), nullable=True))
    op.create_index(op.f("ix_policy_decisions_rate_limit_key"), "policy_decisions", ["rate_limit_key"], unique=False)
    _add_model_usage_columns()

    _paper_outcome_from_evidence("program_scopes")
    _paper_outcome_from_evidence("bug_bounty_findings")
    _set_paper_outcome_default("program_scopes", sa.text("false"))
    _set_paper_outcome_default("bug_bounty_findings", sa.text("false"))


def downgrade() -> None:
    _set_paper_outcome_default("program_scopes", sa.text("false"))
    _set_paper_outcome_default("bug_bounty_findings", None)
    _drop_model_usage_columns()
    op.drop_index(op.f("ix_policy_decisions_rate_limit_key"), table_name="policy_decisions")
    _drop_columns("policy_decisions", ("rate_limit_key",))
    _drop_columns(
        "system_state",
        (
            "rate_limits",
            "domain_denylist",
            "domain_allowlist",
            "counterparty_denylist",
            "counterparty_allowlist",
            "category_limits_cents",
            "category_denylist",
            "category_allowlist",
            "api_cost_cents",
            "api_cost_limit_cents",
        ),
    )
