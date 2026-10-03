from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.orm import Session as SQLAlchemySession

from app.config import settings
from app.models import LedgerTransaction
from app import treasury as treasury_module
from app.treasury import ensure_account, ensure_paper_treasury


API_ROOT = Path(__file__).parents[1]


def _migration_config(database: Path) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    return config


def _insert_legacy_openings(database: Path, count: int) -> None:
    with sqlite3.connect(database) as connection:
        connection.executemany(
            "INSERT INTO ledger_accounts "
            "(id, name, kind, currency, created_at) VALUES (?, ?, ?, ?, ?)",
            [("treasury", "Paper Treasury", "asset", "CAD", "2026-08-19 00:00:00"),
             ("equity", "Opening Equity", "equity", "CAD", "2026-08-19 00:00:00")],
        )
        connection.executemany(
            "INSERT INTO ledger_transactions "
            "(id, currency, amount_cents, debit_account_id, credit_account_id, "
            "experiment_id, agent, external_reference, description, policy_decision_id, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (f"opening-{index}", "CAD", 1_000_000, "treasury", "equity", None, "seed", "paper-opening", "opening", None, "settled", "2026-08-19 00:00:00")
                for index in range(count)
            ],
        )


def test_d0_rejects_legacy_duplicate_openings_before_index_ddl(tmp_path, monkeypatch):
    database = tmp_path / "duplicate-openings.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{database}")
    config = _migration_config(database)
    command.upgrade(config, "c7d8e9f0a123")
    _insert_legacy_openings(database, 2)

    with pytest.raises(RuntimeError, match="Duplicate paper-opening ledger records detected"):
        command.upgrade(config, "d0e1f2a3b4c5")

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' "
            "AND name = 'uq_ledger_transactions_paper_opening'"
        ).fetchone()[0] == 0


def test_d0_accepts_a_single_legacy_opening(tmp_path, monkeypatch):
    database = tmp_path / "single-opening.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{database}")
    config = _migration_config(database)
    command.upgrade(config, "c7d8e9f0a123")
    _insert_legacy_openings(database, 1)

    command.upgrade(config, "d0e1f2a3b4c5")

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' "
            "AND name = 'uq_ledger_transactions_paper_opening'"
        ).fetchone()[0] == 1


def test_paper_opening_is_unique_and_repeated_ensure_is_idempotent(db):
    ensure_paper_treasury(db, 1_000_000)
    ensure_paper_treasury(db, 2_000_000)

    openings = db.query(LedgerTransaction).filter_by(external_reference="paper-opening").all()
    assert len(openings) == 1
    assert openings[0].amount_cents == 1_000_000
    assert "uq_ledger_transactions_paper_opening" in {
        index["name"] for index in inspect(db.get_bind()).get_indexes("ledger_transactions")
    }


def test_expected_opening_race_integrity_error_keeps_session_usable(db, monkeypatch):
    treasury = ensure_account(db, "treasury")
    equity = ensure_account(db, "equity")
    for key in ("revenue", "expense", "reserve"):
        ensure_account(db, key)
    db.commit()
    original = treasury_module.record_transaction
    raced = False

    def duplicate_opening(session, *args, **kwargs):
        nonlocal raced
        if kwargs.get("external_reference") == "paper-opening" and not raced:
            with SQLAlchemySession(bind=session.get_bind()) as contender:
                original(contender, *args, **kwargs)
                contender.commit()
            raced = True
        return original(session, *args, **kwargs)

    monkeypatch.setattr("app.treasury.record_transaction", duplicate_opening)
    ensure_paper_treasury(db, 2_000_000)
    assert db.query(LedgerTransaction).filter_by(external_reference="paper-opening").count() == 1
    assert treasury.id and equity.id and raced
    db.flush()
