import hashlib
from datetime import datetime, timedelta, timezone

import pytest

import app.runtime as runtime
from app.approvals import approval_status, decide_approval
from app.config import settings
from app.models import ApprovalRequest, DemandEvidence, DemandNegotiation, Experiment, Opportunity, SystemState
from app.schemas import NegotiationMessage
from app.queue import RedisQueue
from app.receipts import sign_trusted_receipt
from app.schemas import NegotiationReceipt
from app.seed import seed_demo


def _signed_runtime_receipt() -> dict:
    receipt = {
        "receipt_id": "active-runtime-receipt",
        "remote_id": "active-remote-1",
        "source_url": "https://market.example.test/jobs/active-1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_http_status": 200,
        "content_hash": hashlib.sha256(b"active-agreement").hexdigest(),
        "counterparty_identity": "active-buyer-agent",
        "verification_method": "trusted_adapter_hmac_v1",
    }
    receipt_model = NegotiationReceipt.model_validate({**receipt, "signature": "0" * 64})
    receipt["signature"] = sign_trusted_receipt(receipt_model, settings.trusted_receipt_hmac_secret)
    return receipt


def _attach_runtime_evidence(db, opportunity, source_url: str, buyer_identity: str) -> None:
    content_hash = hashlib.sha256(b"operator-attested demand snapshot").hexdigest()
    evidence = DemandEvidence(
        source_url=source_url,
        source_platform="public-agent-network",
        buyer_identity=buyer_identity,
        captured_at=datetime.now(timezone.utc),
        status_checked_at=datetime.now(timezone.utc),
        quoted_need="A bounded licensed artifact.",
        content_hash=content_hash,
        external_content_untrusted=True,
        verification_status="operator_attested_source_receipt",
        verification_receipt={"receipt_id": "source-receipt", "source_url": source_url, "content_hash": content_hash},
        source_verified_at=datetime.now(timezone.utc),
    )
    db.add(evidence)
    db.flush()
    opportunity.demand_evidence_id = evidence.id


def test_cycle_stops_at_tool_call_limit(db, monkeypatch):
    seed_demo(db)
    monkeypatch.setattr(runtime, "MAX_TOOL_CALLS", 2)

    cycle = runtime.run_cycle(db, demo=True)

    assert cycle.status == "circuit_breaker"
    assert cycle.tool_calls == 2


def test_redis_queue_declares_a_bounded_repeat_without_connecting():
    class FakeQueue:
        kwargs = {}

        def enqueue(self, *args, **kwargs):
            self.kwargs = kwargs
            return type("Queued", (), {"id": "job-1"})()

    queue = object.__new__(RedisQueue)
    queue.queue = FakeQueue()
    queue.retry = object()

    result = queue.enqueue("ceo_cycle", {"demo": False}, repeat_seconds=60, repeat_times=3)

    assert result["repeat_seconds"] == 60
    assert result["repeat_times"] == 3
    assert queue.queue.kwargs["repeat"].times == 3
    assert queue.queue.kwargs["repeat"].intervals == [60]


def test_redis_queue_rejects_unfenced_delayed_ceo_cycle_before_enqueue():
    class FakeQueue:
        def __init__(self):
            self.calls = 0

        def enqueue_in(self, *args, **kwargs):
            self.calls += 1

    queue = object.__new__(RedisQueue)
    queue.queue = FakeQueue()
    with pytest.raises(ValueError, match="recurring schedule generation"):
        queue.enqueue("ceo_cycle", {"demo": False}, delay_seconds=1)
    assert queue.queue.calls == 0


def test_owner_go_resumes_through_one_time_run_approval(db):
    seed_demo(db)
    state = db.get(SystemState, 1)
    opportunity = db.query(Opportunity).first()
    assert state and opportunity
    state.autonomy_level = 0
    agreement_content = "Agreed to the bounded licensed artifact; manifest matches scope."
    agreement_hash = hashlib.sha256(agreement_content.encode()).hexdigest()
    receipt = {
        "receipt_id": "trusted-runtime-receipt",
        "remote_id": "remote-agreement-1",
        "source_url": "https://market.example.test/jobs/1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_http_status": 200,
        "content_hash": agreement_hash,
        "counterparty_identity": "buyer-agent-1",
        "verification_method": "trusted_adapter_hmac_v1",
    }
    receipt_model = NegotiationReceipt.model_validate({**receipt, "signature": "0" * 64})
    receipt["signature"] = sign_trusted_receipt(receipt_model, settings.trusted_receipt_hmac_secret)
    _attach_runtime_evidence(db, opportunity, receipt["source_url"], "buyer-agent-1")
    owner_message = NegotiationMessage(
        sender="owner",
        remote_id="owner-proposal-1",
        sent_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        content="Offer subject to final confirmation and owner approval.",
        content_hash=hashlib.sha256(b"Offer subject to final confirmation and owner approval.").hexdigest(),
    )
    counterparty_message = NegotiationMessage(
        sender="counterparty",
        remote_id=receipt["remote_id"],
        sent_at=datetime.now(timezone.utc),
        content=agreement_content,
        content_hash=agreement_hash,
    )
    negotiation = DemandNegotiation(
        opportunity_id=opportunity.id,
        mode="imported",
        state="OWNER_GO_NO_GO",
        counterparty_identity="buyer-agent-1",
        requested_product="bounded licensed artifact",
        acceptance_criteria="manifest matches scope",
        agreed_price_cents=500,
        agreed_currency="CAD",
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        counterparty_agreed=True,
        owner_go=True,
        messages=[owner_message.model_dump(mode="json"), counterparty_message.model_dump(mode="json")],
        remote_ids=[owner_message.remote_id, counterparty_message.remote_id],
        content_hashes=[owner_message.content_hash, counterparty_message.content_hash],
        external_receipt=receipt,
    )
    db.add(negotiation)
    db.flush()

    first = runtime.run_cycle(db)
    assert first.status == "awaiting_approval"
    assert db.query(Experiment).count() == 0
    assert negotiation.state == "OWNER_GO_NO_GO"
    create_approval = db.query(ApprovalRequest).filter_by(action_type="experiment.create").one()
    decide_approval(db, create_approval.id, "APPROVE", "owner")

    second = runtime.run_cycle(db)
    experiment = db.query(Experiment).one()
    approval = db.query(ApprovalRequest).filter_by(action_type="experiment.run").one()

    assert second.status == "awaiting_approval"
    assert experiment.status == "APPROVED"
    decide_approval(db, approval.id, "APPROVE", "owner")

    third = runtime.run_cycle(db)

    assert third.status == "experiment_started"
    assert experiment.status == "RUNNING"
    assert approval_status(db, create_approval.id) == "CONSUMED"
    assert approval_status(db, approval.id) == "CONSUMED"


@pytest.mark.parametrize("failure", ["missing", "tampered", "expired", "wrong_state", "missing_two_way"])
def test_active_experiment_rechecks_negotiation_receipt_before_monitoring(db, failure):
    seed_demo(db)
    opportunity = db.query(Opportunity).first()
    assert opportunity
    negotiation = None
    negotiation_id = None
    if failure != "missing":
        receipt = _signed_runtime_receipt()
        _attach_runtime_evidence(db, opportunity, receipt["source_url"], receipt["counterparty_identity"])
        if failure == "tampered":
            receipt["signature"] = "0" * 64
        agreement_content = "active-agreement"
        owner_message = NegotiationMessage(
            sender="owner",
            remote_id="active-owner-1",
            sent_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            content="Offer subject to final confirmation.",
            content_hash=hashlib.sha256(b"Offer subject to final confirmation.").hexdigest(),
        )
        counterparty_message = NegotiationMessage(
            sender="counterparty",
            remote_id=receipt["remote_id"],
            sent_at=datetime.now(timezone.utc),
            content=agreement_content,
            content_hash=receipt["content_hash"],
        )
        negotiation = DemandNegotiation(
            opportunity_id=opportunity.id,
            mode="imported",
            state="OWNER_GO_NO_GO" if failure == "wrong_state" else "BUILDING",
            counterparty_identity="active-buyer-agent",
            requested_product="bounded artifact",
            acceptance_criteria="manifest matches scope",
            agreed_price_cents=500,
            agreed_currency="CAD",
            expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1) if failure == "expired" else datetime.now(timezone.utc) + timedelta(days=1)),
            counterparty_agreed=True,
            owner_go=True,
            messages=[] if failure == "missing_two_way" else [owner_message.model_dump(mode="json"), counterparty_message.model_dump(mode="json")],
            remote_ids=[] if failure == "missing_two_way" else [owner_message.remote_id, counterparty_message.remote_id],
            content_hashes=[] if failure == "missing_two_way" else [owner_message.content_hash, counterparty_message.content_hash],
            external_receipt=receipt,
        )
        db.add(negotiation)
        db.flush()
        negotiation_id = negotiation.id
    experiment = Experiment(
        opportunity_id=opportunity.id,
        negotiation_id=negotiation_id,
        title="active receipt gate",
        hypothesis="invalid runtime evidence is blocked",
        status="PAUSED",
        max_spend_cents=0,
    )
    db.add(experiment)
    db.flush()

    cycle = runtime.run_cycle(db)

    assert cycle.status == "blocked"
    assert "receipt" in cycle.rationale.lower()
    assert experiment.status == "PAUSED"
