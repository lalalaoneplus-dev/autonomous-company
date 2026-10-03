from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit import record_audit
from .config import settings
from .models import LedgerAccount, LedgerTransaction, SystemState


ACCOUNT_NAMES = {
    "treasury": ("Paper Treasury", "asset"),
    "equity": ("Opening Equity", "equity"),
    "revenue": ("Simulated Revenue", "income"),
    "expense": ("Experiment Expenses", "expense"),
    "reserve": ("Equipment Goal Reserve", "asset"),
}


def ensure_account(db: Session, key: str) -> LedgerAccount:
    name, kind = ACCOUNT_NAMES[key]
    account = db.scalars(select(LedgerAccount).where(LedgerAccount.name == name)).first()
    if account is None:
        account = LedgerAccount(name=name, kind=kind)
        db.add(account)
        db.flush()
    return account


def ensure_paper_treasury(db: Session, amount_cents: int | None = None) -> None:
    treasury = ensure_account(db, "treasury")
    equity = ensure_account(db, "equity")
    ensure_account(db, "revenue")
    ensure_account(db, "expense")
    ensure_account(db, "reserve")
    opening = db.scalars(
        select(LedgerTransaction).where(
            LedgerTransaction.debit_account_id == treasury.id,
            LedgerTransaction.credit_account_id == equity.id,
            LedgerTransaction.external_reference == "paper-opening",
        )
    ).first()
    if opening is None:
        try:
            # The partial unique index makes this check-and-insert durable. A
            # concurrent winner may still race the read, so isolate the
            # expected uniqueness error in a savepoint and reuse its row.
            with db.begin_nested():
                record_transaction(
                    db,
                    amount_cents if amount_cents is not None else settings.paper_treasury_cents,
                    treasury,
                    equity,
                    "Paper treasury opening balance",
                    agent="seed",
                    external_reference="paper-opening",
                )
        except IntegrityError:
            opening = db.scalars(
                select(LedgerTransaction).where(
                    LedgerTransaction.external_reference == "paper-opening",
                    LedgerTransaction.debit_account_id == treasury.id,
                    LedgerTransaction.credit_account_id == equity.id,
                )
            ).first()
            if opening is None:
                raise


def record_transaction(
    db: Session,
    amount_cents: int,
    debit: LedgerAccount,
    credit: LedgerAccount,
    description: str,
    *,
    agent: str,
    experiment_id: str | None = None,
    policy_decision_id: str | None = None,
    external_reference: str | None = None,
) -> LedgerTransaction:
    if amount_cents <= 0:
        raise ValueError("ledger amount must be positive")
    if debit.id == credit.id:
        raise ValueError("double-entry accounts must differ")
    if debit.currency != credit.currency:
        raise ValueError("ledger currencies must match")
    transaction = LedgerTransaction(
        amount_cents=amount_cents,
        currency=debit.currency,
        debit_account_id=debit.id,
        credit_account_id=credit.id,
        description=description,
        agent=agent,
        experiment_id=experiment_id,
        policy_decision_id=policy_decision_id,
        external_reference=external_reference,
    )
    db.add(transaction)
    db.flush()
    record_audit(
        db,
        "transaction_settled",
        agent,
        description,
        {"transaction_id": transaction.id, "amount_cents": amount_cents, "debit": debit.name, "credit": credit.name},
    )
    return transaction


def account_balance(db: Session, account: LedgerAccount) -> int:
    transactions = db.scalars(
        select(LedgerTransaction).where(
            LedgerTransaction.status == "settled",
            (LedgerTransaction.debit_account_id == account.id) | (LedgerTransaction.credit_account_id == account.id),
        )
    )
    return sum(
        transaction.amount_cents if transaction.debit_account_id == account.id else -transaction.amount_cents
        for transaction in transactions
    )


def paper_balance(db: Session) -> int:
    return account_balance(db, ensure_account(db, "treasury"))


def _locked_state(db: Session) -> SystemState | None:
    return db.scalars(
        select(SystemState).where(SystemState.id == 1).with_for_update()
    ).first()


def record_expense(
    db: Session,
    amount_cents: int,
    description: str,
    *,
    agent: str,
    experiment_id: str | None = None,
    policy_decision_id: str | None = None,
) -> LedgerTransaction:
    ensure_paper_treasury(db)
    expense = ensure_account(db, "expense")
    treasury = ensure_account(db, "treasury")
    transaction = record_transaction(
        db,
        amount_cents,
        expense,
        treasury,
        description,
        agent=agent,
        experiment_id=experiment_id,
        policy_decision_id=policy_decision_id,
    )
    state = _locked_state(db)
    if state:
        state.global_spend_cents += amount_cents
        state.daily_spend_cents += amount_cents
    return transaction


def record_revenue(
    db: Session,
    amount_cents: int,
    description: str,
    *,
    agent: str,
    experiment_id: str | None = None,
    policy_decision_id: str | None = None,
) -> LedgerTransaction:
    ensure_paper_treasury(db)
    treasury = ensure_account(db, "treasury")
    revenue = ensure_account(db, "revenue")
    return record_transaction(
        db,
        amount_cents,
        treasury,
        revenue,
        description,
        agent=agent,
        experiment_id=experiment_id,
        policy_decision_id=policy_decision_id,
    )


def reserve_profit(db: Session, amount_cents: int, *, agent: str, experiment_id: str | None = None) -> LedgerTransaction:
    if amount_cents <= 0:
        raise ValueError("reserve amount must be positive")
    treasury = ensure_account(db, "treasury")
    reserve = ensure_account(db, "reserve")
    transaction = record_transaction(
        db,
        amount_cents,
        reserve,
        treasury,
        "Retained surplus toward equipment goal",
        agent=agent,
        experiment_id=experiment_id,
    )
    state = _locked_state(db)
    if state:
        state.goal_reserve_cents += amount_cents
    return transaction


def treasury_snapshot(db: Session) -> dict[str, int | bool]:
    ensure_paper_treasury(db)
    state = db.get(SystemState, 1)
    revenue = ensure_account(db, "revenue")
    expense = ensure_account(db, "expense")
    return {
        "balance_cents": paper_balance(db),
        "revenue_cents": -account_balance(db, revenue),
        "expenses_cents": account_balance(db, expense),
        "profit_cents": -account_balance(db, revenue) - account_balance(db, expense),
        "frozen": bool(state and state.frozen),
        "real_money_enabled": bool(state and state.real_money_enabled),
    }
