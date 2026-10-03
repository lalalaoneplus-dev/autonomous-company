import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models import DemandEvidence, DemandNegotiation, Experiment, Opportunity, Project
from app.receipts import sign_trusted_receipt
from app.runtime import run_cycle
from app.schemas import NegotiationMessage, NegotiationReceipt
from app.seed import seed_demo


def _gated_negotiation(db, *, state: str = "OWNER_GO_NO_GO") -> DemandNegotiation:
    seed_demo(db)
    opportunity = db.query(Opportunity).first()
    assert opportunity
    source_url = "https://market.example.test/jobs/revalidation"
    buyer_identity = "revalidation-buyer"
    evidence_hash = hashlib.sha256(b"operator-attested snapshot").hexdigest()
    evidence = DemandEvidence(
        source_url=source_url,
        source_platform="public-agent-network",
        buyer_identity=buyer_identity,
        captured_at=datetime.now(timezone.utc),
        status_checked_at=datetime.now(timezone.utc),
        quoted_need="A bounded artifact.",
        content_hash=evidence_hash,
        external_content_untrusted=True,
        verification_status="operator_attested_source_receipt",
        verification_receipt={"receipt_id": "source-receipt", "source_url": source_url, "content_hash": evidence_hash},
        source_verified_at=datetime.now(timezone.utc),
    )
    db.add(evidence)
    db.flush()
    opportunity.demand_evidence_id = evidence.id

    content = "Agreed to the bounded artifact."
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    owner_message = NegotiationMessage(
        sender="owner",
        remote_id="owner-proposal",
        sent_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        content="Offer subject to owner approval.",
        content_hash=hashlib.sha256(b"Offer subject to owner approval.").hexdigest(),
    )
    counterparty_message = NegotiationMessage(
        sender="counterparty",
        remote_id="counterparty-agreement",
        sent_at=datetime.now(timezone.utc),
        content=content,
        content_hash=content_hash,
    )
    receipt = {
        "receipt_id": "agreement-receipt",
        "remote_id": counterparty_message.remote_id,
        "source_url": source_url,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "source_http_status": 200,
        "content_hash": content_hash,
        "counterparty_identity": buyer_identity,
        "verification_method": "trusted_adapter_hmac_v1",
    }
    receipt_model = NegotiationReceipt.model_validate({**receipt, "signature": "0" * 64})
    receipt["signature"] = sign_trusted_receipt(receipt_model, settings.trusted_receipt_hmac_secret)
    negotiation = DemandNegotiation(
        opportunity_id=opportunity.id,
        mode="imported",
        state=state,
        counterparty_identity=buyer_identity,
        requested_product="bounded artifact",
        scope="bounded",
        acceptance_criteria="manifest",
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
    return negotiation


@pytest.mark.parametrize("tamper", ["legacy", "receipt", "message", "evidence"])
def test_api_experiment_creation_revalidates_locked_agreement(db, tamper):
    negotiation = _gated_negotiation(db)
    opportunity = db.get(Opportunity, negotiation.opportunity_id)
    assert opportunity and opportunity.demand_evidence_id
    evidence = db.get(DemandEvidence, opportunity.demand_evidence_id)
    assert evidence
    if tamper == "legacy":
        negotiation.external_receipt = {}
    elif tamper == "receipt":
        negotiation.external_receipt = {**negotiation.external_receipt, "signature": "0" * 64}
    elif tamper == "message":
        messages = list(negotiation.messages)
        messages[-1] = {**messages[-1], "content": "A different agreement."}
        negotiation.messages = messages
    else:
        evidence.source_url = "https://market.example.test/jobs/other"
    db.commit()

    with TestClient(app) as client:
        response = client.post(
            "/api/experiments",
            headers={"X-Owner-Token": "test-owner"},
            json={
                "title": "must remain blocked",
                "hypothesis": "invalid agreement cannot authorize work",
                "opportunity_id": opportunity.id,
                "negotiation_id": negotiation.id,
            },
        )

    assert response.status_code == 400
    db.expire_all()
    assert db.query(DemandNegotiation).filter_by(id=negotiation.id).one().state == "OWNER_GO_NO_GO"
    assert db.query(Experiment).count() == 0


def test_api_project_link_revalidates_legacy_building_agreement(db):
    negotiation = _gated_negotiation(db, state="BUILDING")
    negotiation.external_receipt = {}
    db.commit()
    before = db.query(Project).count()

    with TestClient(app) as client:
        response = client.post(
            "/api/projects",
            headers={"X-Owner-Token": "test-owner"},
            json={"name": "must remain a draft", "concept": "invalid gate", "negotiation_id": negotiation.id},
        )

    assert response.status_code == 400
    db.expire_all()
    assert db.query(Project).count() == before
    assert db.query(DemandNegotiation).filter_by(id=negotiation.id).one().state == "BUILDING"


def test_api_experiment_uses_negotiation_opportunity_when_omitted_and_rejects_wrong_id(db):
    negotiation = _gated_negotiation(db)
    db.commit()
    with TestClient(app) as client:
        created = client.post(
            "/api/experiments",
            headers={"X-Owner-Token": "test-owner"},
            json={
                "title": "normalized opportunity",
                "hypothesis": "the negotiation owns the demand opportunity",
                "negotiation_id": negotiation.id,
                "max_loss_cents": 300,
                "max_spend_cents": 200,
            },
        )
    assert created.status_code == 200
    db.expire_all()
    experiment = db.query(Experiment).one()
    assert experiment.opportunity_id == negotiation.opportunity_id

    second = _gated_negotiation(db)
    wrong_opportunity = db.query(Opportunity).filter(Opportunity.id != second.opportunity_id).first()
    assert wrong_opportunity
    db.commit()
    with TestClient(app) as client:
        rejected = client.post(
            "/api/experiments",
            headers={"X-Owner-Token": "test-owner"},
            json={
                "title": "wrong opportunity",
                "hypothesis": "must remain blocked",
                "opportunity_id": wrong_opportunity.id,
                "negotiation_id": second.id,
            },
        )
    assert rejected.status_code == 400
    db.expire_all()
    assert db.query(Experiment).count() == 1


def test_api_experiment_rejects_spend_above_declared_loss(db):
    negotiation = _gated_negotiation(db)
    db.commit()
    with TestClient(app) as client:
        response = client.post(
            "/api/experiments",
            headers={"X-Owner-Token": "test-owner"},
            json={
                "title": "uncovered spend",
                "hypothesis": "spend cannot exceed bounded loss",
                "negotiation_id": negotiation.id,
                "max_loss_cents": 0,
                "max_spend_cents": 1,
            },
        )
    assert response.status_code == 400
    db.expire_all()
    assert db.query(Experiment).count() == 0
    assert db.query(DemandNegotiation).filter_by(id=negotiation.id).one().state == "OWNER_GO_NO_GO"


def test_api_experiment_rejects_non_inr_without_conversion_provenance(db):
    negotiation = _gated_negotiation(db)
    negotiation.agreed_currency = "USD"
    db.commit()
    with TestClient(app) as client:
        response = client.post(
            "/api/experiments",
            headers={"X-Owner-Token": "test-owner"},
            json={
                "title": "unconverted agreement",
                "hypothesis": "non-CAD accounting must remain blocked",
                "negotiation_id": negotiation.id,
            },
        )
    assert response.status_code == 400
    db.expire_all()
    assert db.query(Experiment).count() == 0
    assert db.query(DemandNegotiation).filter_by(id=negotiation.id).one().state == "OWNER_GO_NO_GO"


def test_owner_termination_is_not_revived_by_next_sqlite_cycle(db):
    negotiation = _gated_negotiation(db, state="BUILDING")
    experiment = Experiment(
        title="owner stop wins",
        hypothesis="a stopped experiment cannot resume from a stale cycle read",
        opportunity_id=negotiation.opportunity_id,
        negotiation_id=negotiation.id,
        status="APPROVED",
    )
    db.add(experiment)
    db.commit()

    with TestClient(app) as client:
        stopped = client.post(
            f"/api/experiments/{experiment.id}/transition",
            headers={"X-Owner-Token": "test-owner"},
            json={"target": "TERMINATED"},
        )
    assert stopped.status_code == 200

    db.expire_all()
    cycle = run_cycle(db)
    db.expire_all()
    assert cycle.status != "experiment_started"
    assert db.query(Experiment).filter_by(id=experiment.id).one().status == "TERMINATED"
