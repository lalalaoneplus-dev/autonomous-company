from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from .audit import record_audit
from .models import DemandEvidence, DemandNegotiation, DeliverableProof, Opportunity
from .receipts import verify_trusted_receipt
from .schemas import (
    DeliverableProofCreate,
    NegotiationAgreementRequest,
    NegotiationCreate,
    NegotiationDraftRequest,
    NegotiationMessage,
)


NEGOTIATION_STATES = {
    "DEMAND_DISCOVERED",
    "OUTREACH_DRAFTED",
    "NEGOTIATING",
    "COUNTERPARTY_AGREED",
    "OWNER_GO_NO_GO",
    "BUILDING",
    "OWNER_DELIVERY_DECISION",
    "DECLINED",
    "EXPIRED",
}


def _verify_message(message: NegotiationMessage) -> dict:
    expected = hashlib.sha256(message.content.encode("utf-8")).hexdigest()
    if message.content_hash.lower() != expected:
        raise ValueError("message content hash does not match content")
    return message.model_dump(mode="json")


def _two_way(messages: list[dict]) -> bool:
    senders = {message.get("sender") for message in messages}
    return len(messages) >= 2 and senders == {"owner", "counterparty"}


def _expired(value: datetime | None) -> bool:
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= datetime.now(timezone.utc)


def create_negotiation(db: Session, data: NegotiationCreate, actor: str = "Sales Agent") -> DemandNegotiation:
    if db.get(Opportunity, data.opportunity_id) is None:
        raise KeyError("opportunity not found")
    messages = [_verify_message(message) for message in data.messages]
    if data.counterparty_agreed:
        raise ValueError("counterparty agreement is derived only by the receipt-backed agreement gate")
    senders = {message.get("sender") for message in messages}
    initial_state = "DEMAND_DISCOVERED"
    if messages:
        initial_state = "OUTREACH_DRAFTED" if senders == {"owner"} else "NEGOTIATING"
    negotiation = DemandNegotiation(
        opportunity_id=data.opportunity_id,
        mode=data.mode,
        state=initial_state,
        counterparty_identity=data.counterparty_identity,
        requested_product=data.requested_product,
        scope=data.scope,
        acceptance_criteria=data.acceptance_criteria,
        agreed_price_cents=data.agreed_price_cents,
        agreed_currency=data.agreed_currency,
        expires_at=data.expires_at,
        counterparty_agreed=False,
        messages=messages,
        remote_ids=[message["remote_id"] for message in messages],
        content_hashes=[message["content_hash"] for message in messages],
    )
    db.add(negotiation)
    db.flush()
    record_audit(db, "negotiation_imported", actor, "No outbound message was sent.", {"negotiation_id": negotiation.id, "mode": data.mode})
    return negotiation


def draft_outreach(db: Session, negotiation: DemandNegotiation, data: NegotiationDraftRequest) -> DemandNegotiation:
    """Store an owner-reviewable proposal; this never sends a message."""

    if negotiation.state != "DEMAND_DISCOVERED":
        raise ValueError(f"cannot draft outreach from {negotiation.state}")
    message = _verify_message(data.message)
    if data.message.sender != "owner":
        raise ValueError("outreach draft must be authored by owner-controlled sales agent")
    negotiation.messages = [*(negotiation.messages or []), message]
    negotiation.remote_ids = [item["remote_id"] for item in negotiation.messages]
    negotiation.content_hashes = [item["content_hash"] for item in negotiation.messages]
    negotiation.state = "OUTREACH_DRAFTED"
    record_audit(db, "outreach_drafted", "Sales Agent", "Draft stored; no outbound message was sent.", {"negotiation_id": negotiation.id})
    db.flush()
    return negotiation


def begin_negotiating(db: Session, negotiation: DemandNegotiation) -> DemandNegotiation:
    if negotiation.state != "OUTREACH_DRAFTED":
        raise ValueError(f"cannot begin negotiation from {negotiation.state}")
    negotiation.state = "NEGOTIATING"
    record_audit(db, "negotiation_started", "Sales Agent", "Negotiation workspace opened; outbound contact remains policy-gated.", {"negotiation_id": negotiation.id})
    db.flush()
    return negotiation


def mark_agreement(db: Session, negotiation: DemandNegotiation, data: NegotiationAgreementRequest) -> DemandNegotiation:
    if negotiation.state not in {"NEGOTIATING", "OUTREACH_DRAFTED"}:
        raise ValueError(f"cannot agree from {negotiation.state}")
    message = _verify_message(data.message)
    if data.message.sender != "counterparty":
        raise ValueError("agreement evidence must be an explicit counterparty response")
    if not data.counterparty_agreed:
        raise ValueError("agreement acknowledgement is required after receipt validation")
    if not negotiation.requested_product.strip():
        raise ValueError("agreement requires a requested product or service")
    if not data.scope.strip() or not data.acceptance_criteria.strip():
        raise ValueError("agreement requires explicit scope and acceptance criteria")
    if data.agreed_price_cents <= 0:
        raise ValueError("agreement requires a positive paper price")
    expires_at = data.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise ValueError("agreement expiry must be in the future")
    opportunity = db.get(Opportunity, negotiation.opportunity_id)
    evidence = db.get(DemandEvidence, opportunity.demand_evidence_id) if opportunity and opportunity.demand_evidence_id else None
    if evidence is None or evidence.verification_status != "operator_attested_source_receipt" or not evidence.verification_receipt:
        raise ValueError("counterparty agreement requires an operator-attested demand-source receipt")
    if evidence.buyer_identity != negotiation.counterparty_identity:
        raise ValueError("counterparty identity does not match the imported demand evidence")
    verify_trusted_receipt(data.external_receipt)
    receipt = data.external_receipt.model_dump(mode="json")
    receipt_captured_at = data.external_receipt.captured_at
    if receipt_captured_at.tzinfo is None:
        receipt_captured_at = receipt_captured_at.replace(tzinfo=timezone.utc)
    message_sent_at = data.message.sent_at
    if message_sent_at.tzinfo is None:
        message_sent_at = message_sent_at.replace(tzinfo=timezone.utc)
    if receipt_captured_at < message_sent_at - timedelta(minutes=5) or receipt_captured_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("negotiation receipt timestamp is inconsistent with the counterparty message")
    if data.external_receipt.source_http_status >= 400:
        raise ValueError("negotiation receipt source must be reachable")
    if str(receipt["source_url"]).rstrip("/") != evidence.source_url.rstrip("/"):
        raise ValueError("negotiation receipt source does not match demand evidence")
    if str(receipt["content_hash"]).lower() != message["content_hash"].lower():
        raise ValueError("negotiation receipt content hash does not match counterparty message")
    if receipt["remote_id"] != message["remote_id"]:
        raise ValueError("negotiation receipt remote id does not match counterparty message")
    if receipt["counterparty_identity"] != negotiation.counterparty_identity:
        raise ValueError("negotiation receipt counterparty does not match the imported identity")
    messages = [*(negotiation.messages or []), message]
    if not data.counterparty_agreed or not _two_way(messages):
        raise ValueError("counterparty agreement requires explicit two-way evidence")
    negotiation.messages = messages
    negotiation.remote_ids = [item["remote_id"] for item in messages]
    negotiation.content_hashes = [item["content_hash"] for item in messages]
    negotiation.scope = data.scope
    negotiation.acceptance_criteria = data.acceptance_criteria
    negotiation.agreed_price_cents = data.agreed_price_cents
    negotiation.agreed_currency = data.agreed_currency
    negotiation.expires_at = data.expires_at
    negotiation.counterparty_agreed = True
    negotiation.external_receipt = receipt
    negotiation.state = "COUNTERPARTY_AGREED"
    record_audit(db, "counterparty_agreed", "Verification Agent", "Trusted-adapter agreement receipt verified; no delivery or payment occurred.", {"negotiation_id": negotiation.id, "receipt_id": receipt["receipt_id"]})
    db.flush()
    return negotiation


def owner_go_no_go(db: Session, negotiation: DemandNegotiation, go: bool) -> DemandNegotiation:
    if negotiation.state != "COUNTERPARTY_AGREED":
        raise ValueError("owner decision requires counterparty agreement")
    if go and _expired(negotiation.expires_at):
        raise ValueError("owner cannot approve an expired agreement")
    negotiation.owner_go = go
    negotiation.state = "OWNER_GO_NO_GO" if go else "DECLINED"
    record_audit(db, "owner_go_no_go", "owner", "owner approved bounded build" if go else "owner declined build", {"negotiation_id": negotiation.id, "go": go})
    db.flush()
    return negotiation


def begin_build(db: Session, negotiation: DemandNegotiation) -> DemandNegotiation:
    if negotiation.state != "OWNER_GO_NO_GO" or not negotiation.owner_go:
        raise ValueError("build requires owner go after counterparty agreement")
    if _expired(negotiation.expires_at):
        raise ValueError("build cannot start after agreement expiry")
    negotiation.state = "BUILDING"
    record_audit(db, "build_started", "Product/Builder Agent", "Owner-approved build gate passed", {"negotiation_id": negotiation.id})
    db.flush()
    return negotiation


def owner_delivery_decision(db: Session, negotiation: DemandNegotiation, decision: str) -> DemandNegotiation:
    if negotiation.state != "BUILDING":
        raise ValueError("delivery decision requires an owner-approved build")
    if decision == "REAL":
        raise ValueError("real delivery is disabled in this credential-free MVP; choose PAPER")
    negotiation.owner_delivery_decision = decision
    negotiation.state = "OWNER_DELIVERY_DECISION"
    record_audit(db, "owner_delivery_decision", "owner", decision, {"negotiation_id": negotiation.id})
    db.flush()
    return negotiation


def create_deliverable_proof(
    db: Session,
    negotiation: DemandNegotiation,
    experiment_id: str,
    data: DeliverableProofCreate,
    *,
    allow_demo: bool = False,
) -> DeliverableProof:
    if negotiation.state != "OWNER_DELIVERY_DECISION" or negotiation.owner_delivery_decision != "PAPER":
        raise ValueError("paper proof requires the owner delivery decision gate")
    if negotiation.mode == "demo-only" and not allow_demo:
        raise ValueError("synthetic demo negotiations cannot create a real deliverable proof")
    proof = DeliverableProof(
        experiment_id=experiment_id,
        artifact_manifest={**data.artifact_manifest, "delivery": "hypothetical", "external_submission": False},
        buyer_response="UNVERIFIED",
        acceptance="SIMULATED",
        settlement="PAPER",
    )
    db.add(proof)
    db.flush()
    return proof


def create_demo_negotiation(db: Session, opportunity: Opportunity) -> DemandNegotiation:
    """Synthetic UI fixture; it is never treated as real demand or real acceptance."""
    negotiation = DemandNegotiation(
        opportunity_id=opportunity.id,
        mode="demo-only",
        state="DEMAND_DISCOVERED",
        counterparty_identity="demo-counterparty-unverified",
        requested_product="Research/automation asset (synthetic UI fixture)",
        scope="Demo only; no real buyer contact or delivery.",
        acceptance_criteria="No acceptance; synthetic UI fixture only.",
        counterparty_agreed=False,
        owner_go=False,
        messages=[],
        remote_ids=[],
        content_hashes=[],
        external_receipt={},
    )
    db.add(negotiation)
    db.flush()
    record_audit(db, "demo_negotiation_fixture", "system", "Synthetic UI/testing state; not real demand or acceptance.", {"negotiation_id": negotiation.id})
    return negotiation
