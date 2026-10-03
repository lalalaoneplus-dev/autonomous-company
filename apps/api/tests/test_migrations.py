import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from alembic import command
from alembic.config import Config
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.config import settings


API_ROOT = Path(__file__).parents[1]


def test_ed30_postgresql_adds_fk_columns_without_batch_rebuild(monkeypatch):
    migration_path = API_ROOT / "alembic" / "versions" / "ed30d52c5375_demand_evidence_and_delivery_gates.py"
    spec = importlib.util.spec_from_file_location("migration_ed30d52c5375", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    added: list[tuple[str, str]] = []
    foreign_keys: list[tuple[str, str, str]] = []

    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
    )
    monkeypatch.setattr(migration.op, "create_table", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(migration.op, "f", lambda name: name)
    monkeypatch.setattr(migration.op, "create_index", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        migration.op,
        "add_column",
        lambda table, column: added.append((table, column.name)),
    )
    monkeypatch.setattr(
        migration.op,
        "create_foreign_key",
        lambda name, table, referred_table, _local_cols, _remote_cols: foreign_keys.append(
            (name, table, referred_table)
        ),
    )

    def unexpected_batch(*_args, **_kwargs):
        raise AssertionError("PostgreSQL migration must not rebuild referenced tables")

    monkeypatch.setattr(migration.op, "batch_alter_table", unexpected_batch)

    migration.upgrade()

    assert added == [
        ("experiments", "negotiation_id"),
        ("opportunities", "demand_evidence_id"),
    ]
    assert foreign_keys == [
        ("fk_experiments_negotiation_id", "experiments", "demand_negotiations"),
        ("fk_opportunities_demand_evidence_id", "opportunities", "demand_evidence"),
    ]


def test_b6_postgresql_uses_native_model_usage_and_paper_gate_alters(monkeypatch):
    migration_path = API_ROOT / "alembic" / "versions" / "b6e7f8a9c012_policy_budget_and_allowlist_gates.py"
    spec = importlib.util.spec_from_file_location("migration_b6e7f8a9c012", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    added: list[tuple[str, str]] = []
    foreign_keys: list[tuple[str, str, str]] = []
    altered_defaults: list[tuple[str, str, str | None]] = []
    dropped: list[tuple[str, str]] = []
    dropped_foreign_keys: list[tuple[str, str, str]] = []

    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
    )
    monkeypatch.setattr(migration.op, "f", lambda name: name)
    monkeypatch.setattr(
        migration.op,
        "add_column",
        lambda table, column: added.append((table, column.name)),
    )
    monkeypatch.setattr(migration.op, "create_index", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(migration.op, "execute", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        migration.op,
        "create_foreign_key",
        lambda name, table, referred_table, _local_cols, _remote_cols: foreign_keys.append(
            (name, table, referred_table)
        ),
    )
    monkeypatch.setattr(
        migration.op,
        "alter_column",
        lambda table, column, **kwargs: altered_defaults.append(
            (
                table,
                column,
                str(kwargs["server_default"]) if kwargs["server_default"] is not None else None,
            )
        ),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_constraint",
        lambda name, table, type_: dropped_foreign_keys.append((name, table, type_)),
    )
    monkeypatch.setattr(migration.op, "drop_column", lambda table, column: dropped.append((table, column)))
    monkeypatch.setattr(migration.op, "drop_index", lambda *_args, **_kwargs: None)

    def unexpected_batch(*_args, **_kwargs):
        raise AssertionError("PostgreSQL b6 migration must use native ALTER operations")

    monkeypatch.setattr(migration.op, "batch_alter_table", unexpected_batch)

    migration.upgrade()
    migration.downgrade()

    assert ("model_usage", "project_id") in added
    assert ("fk_model_usage_project_id", "model_usage", "projects") in foreign_keys
    assert altered_defaults[-4:] == [
        ("program_scopes", "paper_outcome", "false"),
        ("bug_bounty_findings", "paper_outcome", "false"),
        ("program_scopes", "paper_outcome", "false"),
        ("bug_bounty_findings", "paper_outcome", None),
    ]
    assert ("fk_model_usage_project_id", "model_usage", "foreignkey") in dropped_foreign_keys
    assert {table for table, _column in dropped} >= {"model_usage", "policy_decisions", "system_state"}


def test_7bc_paper_outcome_default_compiles_as_postgresql_false(monkeypatch):
    migration_path = API_ROOT / "alembic" / "versions" / "7bc41cc25c11_record_paper_bounty_payment_evidence.py"
    spec = importlib.util.spec_from_file_location("migration_7bc41cc25c11", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    captured: list[tuple[str, object]] = []
    monkeypatch.setattr(migration.op, "add_column", lambda table, column: captured.append((table, column)))

    migration.upgrade()

    paper_column = next(column for table, column in captured if table == "program_scopes" and column.name == "paper_outcome")
    assert str(paper_column.server_default.arg.compile(dialect=postgresql.dialect())) == "false"


def test_9d_execution_enabled_default_compiles_as_postgresql_false(monkeypatch):
    migration_path = API_ROOT / "alembic" / "versions" / "9d0f0e3b4a11_security_gate_receipts.py"
    spec = importlib.util.spec_from_file_location("migration_9d", migration_path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    captured: list[tuple[str, object]] = []

    class FakeBatch:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def add_column(self, column):
            captured.append(("batch", column))

        def alter_column(self, *_args, **_kwargs):
            return None

        def create_foreign_key(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(migration.op, "add_column", lambda table, column: captured.append((table, column)))
    monkeypatch.setattr(migration.op, "batch_alter_table", lambda *_args, **_kwargs: FakeBatch())
    monkeypatch.setattr(migration.op, "execute", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")),
    )

    migration.upgrade()

    execution_column = next(column for _table, column in captured if column.name == "execution_enabled")
    assert str(execution_column.server_default.arg.compile(dialect=postgresql.dialect())) == "false"
    assert isinstance(execution_column.server_default.arg, sa.sql.elements.False_)


def test_policy_migration_populates_valid_json_for_existing_state(tmp_path, monkeypatch):
    database = tmp_path / "legacy.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{database}")
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    command.upgrade(config, "9d0f0e3b4a11")
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO system_state (
                id, objective, strategy, owner_goal, autonomy_level,
                real_money_enabled, frozen, cycle_count,
                global_spend_limit_cents, per_transaction_limit_cents,
                daily_spend_limit_cents, model_cost_limit_cents,
                global_spend_cents, daily_spend_cents, model_cost_cents,
                goal_reserve_cents, updated_at
            ) VALUES (1, 'objective', 'strategy', 'goal', 0, 0, 0, 0,
                      50000, 500, 5000, 1000, 0, 0, 0, 0,
                      '2026-08-19 00:00:00')
            """
        )
    command.upgrade(config, "head")
    with sqlite3.connect(database) as connection:
        raw = connection.execute("SELECT rate_limits FROM system_state WHERE id = 1").fetchone()[0]
    assert json.loads(raw) == {"*": {"max_requests": 60, "window_seconds": 60}}
