from __future__ import annotations

import hashlib
from datetime import datetime, timezone, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.adapters import FiatPaymentAdapter
from app.approvals import approval_status, decide_approval, list_approvals
from app.bounty import BugBountyAgent, create_finding, create_program_scope, transition_finding, transition_program, validate_bounty_action
from app.db import configure_database
from app.main import app
from app.models import (
    AgentState,
    ApprovalEvent,
    AuditEvent,
    Experiment,
    LedgerTransaction,
    Opportunity,
    Postmortem,
    DemandNegotiation,
    DemandEvidence,
    ModelUsage,
    SecurityEvent,
    SystemState,
)
from app.broker import tool_broker
from app.config import settings
from app.policy import policy_engine
from app.queue import DirectQueue
from app.receipts import sign_trusted_receipt
from app.runtime import run_cycle
from app.schemas import (
    ActionRequest,
    ApprovalDecisionRequest,
    BugBountyFindingCreate,
    BugBountyFindingTransitionRequest,
    DeliverableProofCreate,
    ExternalStateReceipt,
    ExperimentCreate,
    NegotiationAgreementRequest,
    NegotiationCreate,
    NegotiationMessage,
    NegotiationReceipt,
    ProgramScopeCreate,
    ProgramScopeTransitionRequest,
)
from app.experiments import create_experiment, transition
from app.negotiations import create_deliverable_proof, create_demo_negotiation, create_negotiation, mark_agreement, owner_delivery_decision, owner_go_no_go
from app.seed import seed_demo
from app.treasury import account_balance, ensure_account, ensure_paper_treasury, record_expense, record_revenue, reserve_profit
from app.opportunities import portfolio_snapshot


def test_application_startup_requires_migrations(tmp_path):
    engine = configure_database(f"sqlite:///{tmp_path / 'unmigrated.db'}")
    with TestClient(app):
        pass
    assert inspect(engine).get_table_names() == []


def test_sqlite_enforces_foreign_keys(db):
    assert db.connection().exec_driver_sql("PRAGMA foreign_keys").scalar() == 1

    db.add(
        Opportunity(
            title="orphan foreign key",
            category="research",
            hypothesis="an invalid demand reference must be rejected",
            demand_evidence_id="missing-demand-evidence",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    assert db.query(Opportunity).filter(Opportunity.title == "orphan foreign key").count() == 0


def test_seeded_goal_backward_cycle_is_business_model_neutral(db):
    state = seed_demo(db)
    cycle = run_cycle(db, demo=True)
    db.commit()
    assert state.autonomy_level == 3
    assert state.real_money_enabled is False
    assert db.query(Opportunity).count() >= 5
    assert cycle.status == "awaiting_owner_selection"
    assert db.query(Experiment).count() == 0
    assert state.goal_reserve_cents == 0
    assert db.query(Postmortem).count() == 0
    assert cycle.tool_calls <= 16


def test_policy_denies_large_transfer_and_unknown_action(db):
    seed_demo(db)
    result = policy_engine.evaluate(
        db,
        ActionRequest(action_type="transfer", amount_cents=50_000, autonomy_required=3, external=True),
    )
    unknown = policy_engine.evaluate(db, ActionRequest(action_type="invented.action"))
    assert result.decision == "DENY"
    assert "transaction" in result.reason
    assert unknown.decision == "DENY"
    assert "fail-closed" in unknown.reason


def test_policy_enforces_configured_category_counterparty_and_domain_controls(db):
    seed_demo(db)
    state = db.get(SystemState, 1)
    assert state
    state.category_limits_cents = {"research": 10}
    state.counterparty_denylist = ["blocked-agent"]
    state.domain_allowlist = ["approved.example"]

    category = policy_engine.evaluate(
        db,
        ActionRequest(action_type="research.search", category="research", amount_cents=11),
    )
    counterparty = policy_engine.evaluate(
        db,
        ActionRequest(action_type="communicate", category="research", counterparty="blocked-agent", external=True),
    )
    domain = policy_engine.evaluate(
        db,
        ActionRequest(action_type="research.fetch", category="research", counterparty="good-agent", domain="unapproved.example"),
    )
    assert category.decision == "DENY"
    assert "category" in category.reason
    assert counterparty.decision == "DENY"
    assert "counterparty" in counterparty.reason
    assert domain.decision == "DENY"
    assert "domain" in domain.reason


def test_policy_enforces_model_api_budgets_and_records_usage(db):
    seed_demo(db)
    state = db.get(SystemState, 1)
    assert state
    state.model_cost_limit_cents = 10
    state.api_cost_limit_cents = 5
    allowed = policy_engine.evaluate(
        db,
        ActionRequest(
            action_type="simulation.research",
            simulation=True,
            model_name="mock-model",
            model_cost_cents=4,
            api_cost_cents=2,
            input_tokens=12,
            output_tokens=8,
        ),
    )
    assert allowed.decision == "ALLOW"
    assert state.model_cost_cents == 4
    assert state.api_cost_cents == 2
    usage = db.query(ModelUsage).one()
    assert usage.model_name == "mock-model"
    assert usage.estimated_cost_cents == 6
    model_over = policy_engine.evaluate(
        db,
        ActionRequest(action_type="simulation.research", simulation=True, model_cost_cents=7),
    )
    api_over = policy_engine.evaluate(
        db,
        ActionRequest(action_type="simulation.research", simulation=True, api_cost_cents=4),
    )
    assert model_over.decision == "DENY"
    assert "model cost" in model_over.reason
    assert api_over.decision == "DENY"
    assert "API cost" in api_over.reason


def test_policy_rate_limit_is_persisted_and_fail_closed(db):
    seed_demo(db)
    state = db.get(SystemState, 1)
    assert state
    state.rate_limits = {"research.search": {"max_requests": 1, "window_seconds": 600}}
    request = ActionRequest(action_type="research.search")
    first = policy_engine.evaluate(db, request)
    second = policy_engine.evaluate(db, request)
    assert first.decision == "ALLOW"
    assert second.decision == "DENY"
    assert "rate limit" in second.reason


def test_policy_malformed_limits_fail_closed_without_raising(db):
    seed_demo(db)
    state = db.get(SystemState, 1)
    assert state
    state.category_limits_cents = {"research": "not-a-number"}  # type: ignore[dict-item]
    category = policy_engine.evaluate(db, ActionRequest(action_type="research.search", category="research"))
    state.category_limits_cents = {}
    state.rate_limits = {"research.search": "not-a-window"}  # type: ignore[dict-item]
    rate = policy_engine.evaluate(db, ActionRequest(action_type="research.search"))
    assert category.decision == "DENY"
    assert "configuration" in category.reason
    assert rate.decision == "DENY"
    assert "rate limit" in rate.reason


def test_policy_requires_approval_and_history_is_append_only(db):
    seed_demo(db)
    result = policy_engine.evaluate(db, ActionRequest(action_type="publish", external=True, autonomy_required=2))
    assert result.decision == "REQUIRE_APPROVAL"
    assert result.approval_id
    assert approval_status(db, result.approval_id) == "PENDING"
    decide_approval(db, result.approval_id, "APPROVE", "owner")
    assert approval_status(db, result.approval_id) == "APPROVE"
    assert db.query(ApprovalEvent).filter(ApprovalEvent.approval_id == result.approval_id).count() == 2
    with pytest.raises(ValueError):
        decide_approval(db, result.approval_id, "DENY", "owner")


def test_overview_counts_pending_approvals(db):
    seed_demo(db)
    result = policy_engine.evaluate(db, ActionRequest(action_type="publish", external=True, autonomy_required=2))
    assert result.approval_id
    db.commit()
    configure_database(db.get_bind().url.render_as_string(hide_password=False))

    with TestClient(app) as client:
        response = client.get("/api/overview", headers={"X-Owner-Token": "test-owner"})

    assert response.status_code == 200
    assert response.json()["pending_approvals"] == 1


def test_approved_action_executes_once_and_cannot_be_replayed(db):
    seed_demo(db)
    experiment = Experiment(
        title="approval replay fixture",
        hypothesis="one owner approval permits one simulated expense",
        status="RUNNING",
        max_spend_cents=500,
    )
    db.add(experiment)
    db.flush()
    request = ActionRequest(
        action_type="simulation.expense",
        requesting_agent="CEO Agent",
        simulation=True,
        amount_cents=300,
        experiment_id=experiment.id,
    )
    pending = tool_broker.call(db, request)
    assert pending.executed is False
    assert pending.policy.decision == "REQUIRE_APPROVAL"
    decide_approval(db, pending.policy.approval_id, "APPROVE", "owner")

    approved_request = request.model_copy(update={"approval_id": pending.policy.approval_id})
    executed = tool_broker.call(db, approved_request)
    replay = tool_broker.call(db, approved_request)

    assert executed.executed is True
    assert approval_status(db, pending.policy.approval_id) == "CONSUMED"
    assert replay.executed is False
    assert replay.policy.decision == "DENY"
    assert experiment.expenses_cents == 300


@pytest.mark.parametrize(
    "phrase",
    ["wash trading", "fake bidding", "self-dealing", "self purchase", "artificial trading volume", "fraudulent identity", "impersonated counterparty", "deceptive financial representation", "fake scarcity", "spam", "unlicensed asset", "prohibited content", "out-of-scope", "DoS", "credential theft"],
)
def test_prohibited_commerce_is_denied_and_freezes(db, phrase):
    seed_demo(db)
    result = policy_engine.evaluate(
        db,
        ActionRequest(action_type="marketplace.request", requesting_agent="Sales Agent", payload={"description": phrase}),
    )
    state = db.get(SystemState, 1)
    assert result.decision == "DENY"
    assert state and state.frozen is True
    assert db.query(SecurityEvent).count() == 1


def test_freeze_blocks_cycles_and_financial_tools(db):
    seed_demo(db)
    state = db.get(SystemState, 1)
    assert state
    state.frozen = True
    state.freeze_reason = "test"
    result = policy_engine.evaluate(db, ActionRequest(action_type="simulation.revenue", amount_cents=1, simulation=True))
    cycle = run_cycle(db)
    assert result.decision == "DENY"
    assert cycle.status == "frozen"


def test_ledger_is_double_entry_and_reserve_is_atomic(db):
    ensure_paper_treasury(db, 1_000_000)
    treasury = ensure_account(db, "treasury")
    expense = ensure_account(db, "expense")
    revenue = ensure_account(db, "revenue")
    record_expense(db, 200, "test expense", agent="test")
    record_revenue(db, 600, "test revenue", agent="test")
    reserve_profit(db, 400, agent="test")
    rows = db.query(LedgerTransaction).all()
    assert all(row.debit_account_id != row.credit_account_id for row in rows)
    assert all(row.amount_cents > 0 and row.currency == "CAD" for row in rows)
    assert {row.debit_account_id for row in rows} | {row.credit_account_id for row in rows} >= {treasury.id, expense.id, revenue.id}
    assert account_balance(db, treasury) == 1_000_000
    assert account_balance(db, expense) == 200
    assert account_balance(db, revenue) == -600


def test_direct_queue_is_bounded_manual_path():
    queue = DirectQueue()
    queue.enqueue("demo", {"value": 2})
    assert queue.run_next({"demo": lambda payload: payload["value"] * 2}) == 4
    with pytest.raises(KeyError):
        queue.enqueue("unknown", {})
        queue.run_next({})


def test_inert_real_adapter_never_executes():
    with pytest.raises(RuntimeError):
        FiatPaymentAdapter().execute(amount_cents=1)


def test_real_demand_negotiation_and_delivery_gates(db):
    seed_demo(db)
    state = db.get(SystemState, 1)
    assert state
    state.autonomy_level = 4
    opportunity = db.query(Opportunity).first()
    assert opportunity
    evidence = DemandEvidence(
        source_url="https://real.example/jobs/42",
        source_platform="public-agent-network",
        buyer_identity="verified-agent-42",
        captured_at=datetime.now(timezone.utc),
        status_checked_at=datetime.now(timezone.utc),
        quoted_need="Please quote a bounded licensed research asset.",
        stated_budget_cents=600,
        stated_currency="CAD",
        content_hash="b" * 64,
        external_content_untrusted=True,
        verification_status="operator_attested_source_receipt",
        verification_receipt={"receipt_id": "source-receipt-1", "source_url": "https://real.example/jobs/42", "content_hash": "b" * 64},
        source_verified_at=datetime.now(timezone.utc),
    )
    db.add(evidence)
    db.flush()
    opportunity.demand_evidence_id = evidence.id
    with pytest.raises(ValueError):
        create_experiment(db, ExperimentCreate(title="blocked", hypothesis="blocked", opportunity_id=opportunity.id))

    def message(sender: str, remote_id: str, content: str) -> NegotiationMessage:
        return NegotiationMessage(
            sender=sender,
            remote_id=remote_id,
            sent_at=datetime.now(timezone.utc),
            content=content,
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
        )

    negotiation = create_negotiation(
        db,
        NegotiationCreate(
            opportunity_id=opportunity.id,
            counterparty_identity="verified-agent-42",
            requested_product="licensed research asset",
            messages=[message("counterparty", "remote-1", "Please quote a bounded licensed research asset.")],
        ),
    )
    with pytest.raises(ValueError):
        mark_agreement(
            db,
            negotiation,
            NegotiationAgreementRequest(
                counterparty_agreed=True,
                scope="bounded",
                acceptance_criteria="manifest",
                agreed_price_cents=600,
                agreed_currency="CAD",
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                message=message("owner", "remote-2", "Offer subject to owner approval."),
            ),
        )
    negotiation.messages = [
        message("counterparty", "remote-1", "Please quote a bounded licensed research asset.").model_dump(mode="json"),
        message("owner", "remote-2", "Offer subject to owner approval.").model_dump(mode="json"),
    ]
    negotiation.state = "NEGOTIATING"
    receipt = {
        "receipt_id": "negotiation-receipt-1",
        "remote_id": "remote-3",
        "source_url": "https://real.example/jobs/42",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_http_status": 200,
        "content_hash": hashlib.sha256(b"Agreed, subject to final confirmation.").hexdigest(),
        "counterparty_identity": "verified-agent-42",
        "verification_method": "trusted_adapter_hmac_v1",
    }
    receipt_model = NegotiationReceipt.model_validate({**receipt, "signature": "0" * 64})
    receipt["signature"] = sign_trusted_receipt(receipt_model, settings.trusted_receipt_hmac_secret)
    forged_request = NegotiationAgreementRequest(
        counterparty_agreed=True,
        scope="bounded",
        acceptance_criteria="manifest",
        agreed_price_cents=600,
        agreed_currency="CAD",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        message=message("counterparty", "remote-3", "Agreed, subject to final confirmation."),
        external_receipt={**receipt, "signature": "0" * 64},
    )
    with pytest.raises(ValueError, match="signature is invalid"):
        mark_agreement(db, negotiation, forged_request)
    mark_agreement(
        db,
        negotiation,
        NegotiationAgreementRequest(
            counterparty_agreed=True,
            scope="bounded",
            acceptance_criteria="manifest",
            agreed_price_cents=600,
            agreed_currency="CAD",
            expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            message=message("counterparty", "remote-3", "Agreed, subject to final confirmation."),
            external_receipt=receipt,
        ),
    )
    negotiation.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(ValueError, match="expired"):
        owner_go_no_go(db, negotiation, True)
    negotiation.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    owner_go_no_go(db, negotiation, True)
    original_stream = opportunity.stream_type
    opportunity.stream_type = "bug_bounty"
    with pytest.raises(ValueError, match="5% allocation cap"):
        create_experiment(
            db,
            ExperimentCreate(
                title="over-cap bounty",
                hypothesis="must remain bounded",
                opportunity_id=opportunity.id,
                negotiation_id=negotiation.id,
                stream_type="bug_bounty",
                max_loss_cents=50_001,
            ),
        )
    opportunity.stream_type = original_stream
    concentrated = Experiment(
        title="existing platform risk",
        hypothesis="fixture",
        opportunity_id=opportunity.id,
        stream_type=opportunity.stream_type,
        status="RUNNING",
        max_loss_cents=190_000,
    )
    db.add(concentrated)
    db.flush()
    with pytest.raises(ValueError, match="concentration"):
        create_experiment(
            db,
            ExperimentCreate(
                title="over-concentrated experiment",
                hypothesis="must be blocked",
                opportunity_id=opportunity.id,
                negotiation_id=negotiation.id,
                max_loss_cents=20_001,
            ),
        )
    db.delete(concentrated)
    db.flush()
    experiment = create_experiment(
        db,
        ExperimentCreate(
            title="approved asset experiment",
            hypothesis="deliver a bounded asset",
            opportunity_id=opportunity.id,
            negotiation_id=negotiation.id,
            max_loss_cents=200,
            max_spend_cents=200,
        ),
    )
    with pytest.raises(ValueError, match="only one experiment"):
        create_experiment(
            db,
            ExperimentCreate(
                title="duplicate agreement experiment",
                hypothesis="must be blocked",
                opportunity_id=opportunity.id,
                negotiation_id=negotiation.id,
            ),
        )
    with pytest.raises(ValueError):
        create_deliverable_proof(db, negotiation, experiment.id, DeliverableProofCreate())
    owner_delivery_decision(db, negotiation, "PAPER")
    proof = create_deliverable_proof(db, negotiation, experiment.id, DeliverableProofCreate())
    assert proof.buyer_response == "UNVERIFIED"
    assert proof.acceptance == "SIMULATED"
    assert proof.settlement == "PAPER"
    transition(db, experiment, "REVIEW")
    transition(db, experiment, "APPROVED")
    transition(db, experiment, "RUNNING")
    negotiation.agreed_currency = "USD"
    cross_currency = tool_broker.call(db, ActionRequest(action_type="simulation.revenue", requesting_agent="Sales Agent", simulation=True, amount_cents=600, experiment_id=experiment.id))
    assert cross_currency.executed is False
    assert "conversion provenance" in cross_currency.output["error"]
    negotiation.agreed_currency = "CAD"
    wrong_amount = tool_broker.call(db, ActionRequest(action_type="simulation.revenue", requesting_agent="Sales Agent", simulation=True, amount_cents=599, experiment_id=experiment.id))
    assert wrong_amount.executed is False
    paid = tool_broker.call(db, ActionRequest(action_type="simulation.revenue", requesting_agent="Sales Agent", simulation=True, amount_cents=600, experiment_id=experiment.id))
    assert paid.executed is True
    duplicate = tool_broker.call(db, ActionRequest(action_type="simulation.revenue", requesting_agent="Sales Agent", simulation=True, amount_cents=600, experiment_id=experiment.id))
    assert duplicate.executed is False
    assert duplicate.output["error"] == "paper settlement is already recorded"


def test_synthetic_demo_cannot_qualify_outside_explicit_demo_route(db):
    seed_demo(db)
    opportunity = db.query(Opportunity).first()
    assert opportunity
    demo_negotiation = create_demo_negotiation(db, opportunity)
    with pytest.raises(ValueError, match="synthetic demo"):
        create_experiment(
            db,
            ExperimentCreate(title="not allowed", hypothesis="not allowed", opportunity_id=opportunity.id, negotiation_id=demo_negotiation.id),
        )
    cycle = run_cycle(db)
    assert cycle.status == "blocked"
    assert "demo fixtures" in cycle.rationale


def test_api_owner_controls_and_demo_cycle(db):
    configure_database(db.get_bind().url.render_as_string(hide_password=False))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.patch("/api/settings", json={"autonomy_level": 2}).status_code == 403
        owner_headers = {"X-Owner-Token": "test-owner"}
        assert client.get("/api/overview").status_code == 403
        seed_response = client.post("/api/demo/seed", headers=owner_headers)
        assert seed_response.status_code == 200
        cycle_response = client.post("/api/demo/cycle", headers=owner_headers)
        assert cycle_response.status_code == 200
        assert cycle_response.json()["status"] == "awaiting_owner_selection"
        scheduled = client.post("/api/ceo/schedule", headers=owner_headers)
        assert scheduled.status_code == 200
        assert scheduled.json()["executed"] is True
        assert scheduled.json()["cycle"]["status"] == "blocked"
        experiment = Experiment(title="manual transition gate", hypothesis="manual transitions cannot start work", status="APPROVED")
        db.add(experiment)
        db.commit()
        direct_start = client.post(
            f"/api/experiments/{experiment.id}/transition",
            headers=owner_headers,
            json={"target": "RUNNING"},
        )
        assert direct_start.status_code == 409
        db.refresh(experiment)
        assert experiment.status == "APPROVED"
        manual_stop = client.post(
            f"/api/experiments/{experiment.id}/transition",
            headers=owner_headers,
            json={"target": "TERMINATED"},
        )
        assert manual_stop.status_code == 200
        latest_transition = db.query(AuditEvent).filter_by(event_type="experiment_transition").order_by(AuditEvent.created_at.desc()).first()
        assert latest_transition and latest_transition.actor == "owner"
        assert client.post("/api/ceo/schedule?recurring=true", headers=owner_headers).status_code == 400
        freeze_response = client.post(
            "/api/security/freeze",
            headers=owner_headers,
            json={"reason": "test freeze"},
        )
        assert freeze_response.status_code == 200
        assert client.post("/api/ceo/cycle", headers=owner_headers).json()["status"] == "frozen"
        assert client.patch(
            "/api/settings",
            headers=owner_headers,
            json={"real_money_enabled": True},
        ).status_code == 400


def test_owner_controls_fail_closed_without_explicit_configuration(db, monkeypatch):
    configure_database(db.get_bind().url.render_as_string(hide_password=False))
    monkeypatch.setattr(settings, "owner_token", None)
    with TestClient(app) as client:
        headers = {"X-Owner-Token": "test-owner"}
        assert client.get("/api/overview", headers=headers).status_code == 403
        assert client.get("/api/security", headers=headers).status_code == 403
        assert client.post("/api/demo/seed", headers=headers).status_code == 403


def test_imported_demand_stays_unverified_until_receipt_and_then_can_be_linked(db):
    configure_database(db.get_bind().url.render_as_string(hide_password=False))
    headers = {"X-Owner-Token": "test-owner"}
    captured_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "source_url": "https://public.example/jobs/42",
        "source_platform": "public-agent-network",
        "buyer_identity": "agent-counterparty-42",
        "captured_at": captured_at,
        "status_checked_at": captured_at,
        "quoted_need": "A bounded licensed research asset.",
        "stated_budget_cents": 600,
        "stated_currency": "CAD",
        "content_hash": "c" * 64,
        "verified_snapshot": True,
    }
    with TestClient(app) as client:
        imported = client.post("/api/demand-evidence", headers=headers, json=payload)
        assert imported.status_code == 200
        evidence = imported.json()
        assert evidence["verification_status"] == "imported_unverified"
        assert evidence["verification_receipt"] == {}
        blocked = client.post(
            "/api/opportunities",
            headers=headers,
            json={
                "title": "Unverified opportunity",
                "category": "agent service",
                "hypothesis": "must remain blocked",
                "source": "public-demand-import",
                "demand_evidence_id": evidence["id"],
            },
        )
        assert blocked.status_code == 400
        bad_receipt = client.post(
            f"/api/demand-evidence/{evidence['id']}/verification-receipt",
            headers=headers,
            json={
                "receipt_id": "receipt-bad",
                "source_url": payload["source_url"],
                "observed_at": captured_at,
                "source_http_status": 200,
                "content_hash": "d" * 64,
                "verification_method": "imported snapshot",
            },
        )
        assert bad_receipt.status_code == 400
        verified = client.post(
            f"/api/demand-evidence/{evidence['id']}/verification-receipt",
            headers=headers,
            json={
                "receipt_id": "receipt-good",
                "source_url": payload["source_url"],
                "observed_at": captured_at,
                "source_http_status": 200,
                "content_hash": payload["content_hash"],
                "verification_method": "owner-imported source receipt",
            },
        )
        assert verified.status_code == 200
        assert verified.json()["verification_status"] == "operator_attested_source_receipt"
        linked = client.post(
            "/api/opportunities",
            headers=headers,
            json={
                "title": "Receipt-backed opportunity",
                "category": "agent service",
                "hypothesis": "can now enter the gated pipeline",
                "source": "public-demand-import",
                "demand_evidence_id": evidence["id"],
            },
        )
        assert linked.status_code == 200


def test_broker_permissions_and_revenue_prerequisites_are_fail_closed(db):
    seed_demo(db)
    state = db.get(SystemState, 1)
    assert state
    state.autonomy_level = 4
    assert db.query(AgentState).filter(AgentState.role == "Research Agent").one()
    experiment = Experiment(
        title="gated revenue fixture",
        hypothesis="revenue must stay behind delivery evidence",
        status="DRAFT",
        max_spend_cents=100,
    )
    db.add(experiment)
    db.flush()
    opening_transactions = db.query(LedgerTransaction).count()
    unauthorized = tool_broker.call(
        db,
        ActionRequest(
            action_type="simulation.expense",
            requesting_agent="Research Agent",
            simulation=True,
            amount_cents=1,
            experiment_id=experiment.id,
        ),
    )
    assert unauthorized.executed is False
    assert unauthorized.policy.decision == "DENY"
    assert "not permitted" in unauthorized.policy.reason
    not_simulation = tool_broker.call(
        db,
        ActionRequest(
            action_type="simulation.revenue",
            requesting_agent="Sales Agent",
            amount_cents=1,
            experiment_id=experiment.id,
        ),
    )
    assert not_simulation.executed is False
    assert not_simulation.policy.decision == "DENY"
    revenue = tool_broker.call(
        db,
        ActionRequest(
            action_type="simulation.revenue",
            requesting_agent="Sales Agent",
            simulation=True,
            amount_cents=1,
            experiment_id=experiment.id,
        ),
    )
    assert revenue.executed is False
    assert revenue.output["error"] == "experiment must be RUNNING before revenue"
    assert db.query(LedgerTransaction).count() == opening_transactions


def test_projects_without_gated_negotiation_are_non_executable(db):
    configure_database(db.get_bind().url.render_as_string(hide_password=False))
    with TestClient(app) as client:
        response = client.post(
            "/api/projects",
            headers={"X-Owner-Token": "test-owner"},
            json={"name": "Ungated concept", "concept": "draft only"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["negotiation_id"] is None
        assert body["execution_enabled"] is False


def test_bounty_scope_verification_requires_complete_rules(db):
    program = create_program_scope(
        db,
        ProgramScopeCreate(
            program_url="https://example.test/security",
            assets_in_scope=["api.example.test"],
            content_hash="e" * 64,
        ),
    )
    with pytest.raises(ValueError, match="safe harbor"):
        transition_program(db, program, ProgramScopeTransitionRequest(target="SCOPE_VERIFIED"))


def test_hard_deny_security_event_survives_http_error_rollback(db, monkeypatch):
    monkeypatch.setattr(settings, "bug_bounty_external_actions_enabled", True)
    db.add(SystemState(id=1))
    db.flush()
    program = _program(db)
    transition_program(db, program, ProgramScopeTransitionRequest(target="SCOPE_VERIFIED"))
    transition_program(
        db,
        program,
        ProgramScopeTransitionRequest(target="OWNER_TARGET_AUTHORIZATION", assets=["api.example.test"], owner_approved=True),
    )
    transition_program(db, program, ProgramScopeTransitionRequest(target="PASSIVE_TRIAGE"))
    transition_program(db, program, ProgramScopeTransitionRequest(target="TEST_PLAN_REVIEW", owner_approved=True))
    transition_program(
        db,
        program,
        ProgramScopeTransitionRequest(target="ACTIVE_TESTING", assets=["api.example.test"], owner_approved=True),
    )
    db.commit()
    configure_database(db.get_bind().url.render_as_string(hide_password=False))
    with TestClient(app) as client:
        response = client.post(
            f"/api/bug-bounty/programs/{program.id}/findings",
            headers={"X-Owner-Token": "test-owner"},
            json={
                "title": "unsafe fixture",
                "description": "PII exfiltration must be denied",
                "asset": "api.example.test",
            },
        )
        assert response.status_code == 400
    db.expire_all()
    assert db.query(SecurityEvent).count() == 1
    state = db.get(SystemState, 1)
    assert state and state.frozen is True


def _program(db):
    return create_program_scope(
        db,
        ProgramScopeCreate(
            program_url="https://example.test/security",
            assets_in_scope=["api.example.test"],
            assets_out_of_scope=["admin.example.test"],
            safe_harbor="No destructive testing.",
            rules=["Use the test account only."],
            rate_limits={"requests_per_minute": 10},
            test_plan="Passive observation first; exact host only; no load or destructive actions.",
            test_account_requirements="owner-provided test account",
            required_headers=["X-Test-Account"],
            payout_tiers=[{"severity": "low", "max_cents": 500}],
            disclosure_policy="Coordinate disclosure with program owner.",
            content_hash="a" * 64,
        ),
    )


def _external_state_receipt(subject_id: str, event_type: str) -> dict:
    receipt = {
        "receipt_id": f"receipt-{event_type.lower()}",
        "source_url": "https://bounty.example.test/report/42",
        "remote_id": f"remote-{event_type.lower()}",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": hashlib.sha256(f"{subject_id}:{event_type}".encode()).hexdigest(),
        "subject_id": subject_id,
        "event_type": event_type,
        "verification_method": "trusted_adapter_hmac_v1",
    }
    receipt_model = ExternalStateReceipt.model_validate({**receipt, "signature": "0" * 64})
    receipt["signature"] = sign_trusted_receipt(receipt_model, settings.trusted_receipt_hmac_secret)
    return receipt


@pytest.mark.parametrize(
    "phrase",
    ["out-of-scope target", "destructive request", "PII exfiltration", "phishing", "social engineering", "denial of service", "load testing", "credential theft", "threat actor"],
)
def test_bug_bounty_hard_denies_unsafe_actions(db, phrase):
    program = _program(db)
    with pytest.raises(ValueError):
        validate_bounty_action(db, program, "active_testing", asset="api.example.test", detail={"request": phrase})
    assert program.status == "PROGRAM_DISCOVERED"
    assert db.query(SecurityEvent).count() == 1
    assert db.get(SystemState, 1).frozen is True


def test_bug_bounty_denies_out_of_scope_asset_even_in_passive_triage(db):
    program = _program(db)
    with pytest.raises(ValueError, match="outside"):
        validate_bounty_action(db, program, "passive_triage", asset="admin.example.test")


def test_bug_bounty_passive_scope_and_owner_gates_never_book_paper_revenue(db, monkeypatch):
    monkeypatch.setattr(settings, "bug_bounty_external_actions_enabled", True)
    program = _program(db)
    agent = BugBountyAgent()
    assert agent.passive_by_default is True
    assert program.paper_outcome is False
    with pytest.raises(ValueError):
        agent.validate_action(db, program, "active_testing", asset="api.example.test")

    transition_program(db, program, ProgramScopeTransitionRequest(target="SCOPE_VERIFIED"))
    with pytest.raises(ValueError):
        transition_program(db, program, ProgramScopeTransitionRequest(target="OWNER_TARGET_AUTHORIZATION"))
    transition_program(
        db,
        program,
        ProgramScopeTransitionRequest(target="OWNER_TARGET_AUTHORIZATION", assets=["api.example.test"], owner_approved=True),
    )
    transition_program(db, program, ProgramScopeTransitionRequest(target="PASSIVE_TRIAGE"))
    transition_program(db, program, ProgramScopeTransitionRequest(target="TEST_PLAN_REVIEW", owner_approved=True))
    transition_program(db, program, ProgramScopeTransitionRequest(target="ACTIVE_TESTING", assets=["api.example.test"], owner_approved=True))
    agent.validate_action(db, program, "active_testing", asset="api.example.test")

    finding = create_finding(
        db,
        program,
        BugBountyFindingCreate(
            title="Bounded informational finding",
            description="A passive observation with reproducible evidence.",
            asset="api.example.test",
            evidence={"request_id": "fixture-1"},
        ),
    )
    transition_finding(db, finding, BugBountyFindingTransitionRequest(target="DUPLICATE_CHECK"))
    transition_finding(db, finding, BugBountyFindingTransitionRequest(target="REPORT_DRAFT"))
    with pytest.raises(ValueError):
        transition_finding(db, finding, BugBountyFindingTransitionRequest(target="OWNER_SUBMISSION_APPROVAL"))
    transition_finding(db, finding, BugBountyFindingTransitionRequest(target="OWNER_SUBMISSION_APPROVAL", owner_approved=True))
    with pytest.raises(ValueError):
        transition_finding(db, finding, BugBountyFindingTransitionRequest(target="SUBMITTED"))
    with pytest.raises(ValueError, match="trusted external-state receipt"):
        transition_finding(db, finding, BugBountyFindingTransitionRequest(target="SUBMITTED", owner_approved=True))
    transition_finding(
        db,
        finding,
        BugBountyFindingTransitionRequest(
            target="SUBMITTED",
            owner_approved=True,
            external_receipt=_external_state_receipt(finding.id, "BUG_BOUNTY_SUBMITTED"),
        ),
    )
    transition_finding(
        db,
        finding,
        BugBountyFindingTransitionRequest(
            target="TRIAGED",
            external_receipt=_external_state_receipt(finding.id, "BUG_BOUNTY_TRIAGED"),
        ),
    )
    transition_finding(
        db,
        finding,
        BugBountyFindingTransitionRequest(
            target="ACCEPTED",
            external_receipt=_external_state_receipt(finding.id, "BUG_BOUNTY_ACCEPTED"),
        ),
    )
    assert finding.paper_outcome is False
    with pytest.raises(ValueError):
        transition_finding(db, finding, BugBountyFindingTransitionRequest(target="PAID", owner_approved=True))
    with pytest.raises(ValueError, match="PAPER_ONLY"):
        transition_finding(
            db,
            finding,
            BugBountyFindingTransitionRequest(
                target="PAID",
                owner_approved=True,
                payment_evidence={"status": "PAID", "amount_cents": 500},
            ),
        )
    before = db.query(LedgerTransaction).count()
    transition_finding(
        db,
        finding,
        BugBountyFindingTransitionRequest(target="PAID", owner_approved=True, payment_evidence={"status": "PAPER_ONLY", "amount_cents": 500}),
    )
    assert finding.paper_outcome is True
    assert finding.payment_evidence["status"] == "PAPER_ONLY"
    assert db.query(LedgerTransaction).count() == before
    with pytest.raises(ValueError):
        transition_finding(db, finding, BugBountyFindingTransitionRequest(target="DISCLOSURE_APPROVAL", owner_approved=True))
    transition_finding(db, finding, BugBountyFindingTransitionRequest(target="DISCLOSURE_APPROVAL", owner_approved=True, public_disclosure_approved=True))


def test_portfolio_is_stream_keyed_and_paper_only(db):
    seed_demo(db)
    snapshot = portfolio_snapshot(db)
    assert set(snapshot["streams"]) >= {"agent_services", "digital_assets", "public_tasks", "affiliate_content", "bug_bounty"}
    assert snapshot["caps_bps"]["stream_committed_risk"] == 3500
    assert snapshot["caps_bps"]["reserve_unallocated"] == 2500
    assert all(stream["committed_risk_cents"] == 0 for stream in snapshot["streams"].values())
    assert sum(stream["pipeline_downside_cents"] for stream in snapshot["streams"].values()) > 0
    assert snapshot["metrics_are_paper_only"] is True
    assert snapshot["real_money_enabled"] is False
