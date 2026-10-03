from __future__ import annotations

from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .agents import build_model, ensure_agents
from .approvals import consume_approval, matching_approved_id
from .audit import record_audit
from .broker import tool_broker
from .experiments import create_experiment, transition as transition_experiment
from .models import Cycle, DemandEvidence, DemandNegotiation, Experiment, Opportunity, SystemState, utcnow
from .negotiations import _two_way, _verify_message
from .opportunities import upsert_opportunities
from .policy import policy_engine
from .receipts import verify_trusted_receipt
from .schemas import ActionRequest, ExperimentCreate, NegotiationMessage, NegotiationReceipt
from .treasury import ensure_paper_treasury


MAX_CYCLES = 100
MAX_TURNS = 8
MAX_TOOL_CALLS = 16
MAX_MODEL_COST_CENTS = 100
MAX_WALL_SECONDS = 30
ACTIVE_NEGOTIATION_STATES = {"BUILDING", "OWNER_DELIVERY_DECISION"}


def _blocked_cycle(db: Session, state: SystemState, cycle: Cycle, rationale: str) -> Cycle:
    cycle.status = "blocked"
    cycle.rationale = rationale
    cycle.finished_at = utcnow()
    state.cycle_count += 1
    record_audit(db, "ceo_cycle_blocked", "CEO Agent", rationale, {"cycle_id": cycle.id})
    db.flush()
    return cycle


def _validate_runtime_negotiation(db: Session, negotiation: DemandNegotiation, allowed_states: set[str]) -> None:
    if negotiation.state not in allowed_states:
        raise ValueError("negotiation is not in a qualifying runtime state")
    if not negotiation.owner_go or not negotiation.counterparty_agreed:
        raise ValueError("negotiation does not retain owner go and counterparty agreement")
    if negotiation.expires_at is None:
        raise ValueError("negotiation agreement has no expiry")
    expiry = negotiation.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if expiry <= now:
        raise ValueError("negotiation agreement has expired")
    receipt = NegotiationReceipt.model_validate(negotiation.external_receipt)
    verify_trusted_receipt(receipt)
    messages = [_verify_message(NegotiationMessage.model_validate(item)) for item in (negotiation.messages or [])]
    if not _two_way(messages):
        raise ValueError("runtime work requires valid two-way negotiation evidence")
    counterparty_message = next((item for item in reversed(messages) if item["sender"] == "counterparty"), None)
    if counterparty_message is None:
        raise ValueError("runtime work requires a counterparty message")
    if receipt.remote_id != counterparty_message["remote_id"]:
        raise ValueError("trusted negotiation receipt remote id does not match the counterparty message")
    if receipt.content_hash != counterparty_message["content_hash"]:
        raise ValueError("trusted negotiation receipt content hash does not match the counterparty message")
    captured_at = receipt.captured_at
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    if captured_at > now + timedelta(minutes=5) or captured_at > expiry:
        raise ValueError("trusted negotiation receipt is not current")
    if receipt.source_http_status >= 400:
        raise ValueError("trusted negotiation receipt source is not reachable")
    if receipt.counterparty_identity != negotiation.counterparty_identity:
        raise ValueError("trusted negotiation receipt counterparty does not match")
    opportunity = db.get(Opportunity, negotiation.opportunity_id)
    evidence = db.get(DemandEvidence, opportunity.demand_evidence_id) if opportunity and opportunity.demand_evidence_id else None
    if evidence is None or evidence.verification_status != "operator_attested_source_receipt" or not evidence.verification_receipt:
        raise ValueError("runtime work requires an operator-attested demand-source receipt")
    if evidence.source_verified_at is None:
        raise ValueError("runtime work requires a dated operator-attested demand-source receipt")
    if str(receipt.source_url).rstrip("/") != evidence.source_url.rstrip("/"):
        raise ValueError("trusted negotiation receipt source does not match demand evidence")
    if receipt.counterparty_identity != evidence.buyer_identity:
        raise ValueError("trusted negotiation receipt counterparty does not match demand evidence")


def ensure_state(db: Session) -> SystemState:
    state = db.scalars(
        select(SystemState).where(SystemState.id == 1).with_for_update()
    ).first()
    if state is None:
        state = SystemState(id=1)
        db.add(state)
        db.flush()
    return state


def run_cycle(db: Session, *, demo: bool = False) -> Cycle:
    deadline = monotonic() + MAX_WALL_SECONDS
    state = ensure_state(db)
    if state.frozen:
        cycle = Cycle(status="frozen", rationale="Cycle skipped because autonomy is frozen.", turns=0, tool_calls=0)
        db.add(cycle)
        db.flush()
        return cycle
    if state.cycle_count >= MAX_CYCLES:
        cycle = Cycle(status="circuit_breaker", rationale="maximum cycle count reached", turns=0, tool_calls=0)
        db.add(cycle)
        db.flush()
        return cycle

    cycle = Cycle(status="running")
    db.add(cycle)
    db.flush()
    model = build_model()
    proposal = model.propose({"objective": state.objective, "owner_goal": state.owner_goal, "strategy": state.strategy})
    cycle.rationale = proposal["rationale"][:2000]
    requested_turns = int(proposal.get("max_turns", MAX_TURNS))
    if requested_turns < 0 or requested_turns > MAX_TURNS or monotonic() >= deadline:
        cycle.status = "circuit_breaker"
        cycle.rationale = "cycle proposal exceeded the turn or wall-clock limit"
        cycle.finished_at = utcnow()
        db.flush()
        return cycle
    cycle.turns = requested_turns

    ensure_agents(db)
    ensure_paper_treasury(db)
    opportunities = upsert_opportunities(db)
    if not opportunities:
        cycle.status = "failed"
        cycle.rationale = "No opportunities were available."
        cycle.finished_at = utcnow()
        db.flush()
        return cycle

    if not demo:
        experiment = db.scalars(
            select(Experiment)
            .where(Experiment.status.in_(("DRAFT", "REVIEW", "APPROVED", "RUNNING", "PAUSED")))
            .with_for_update()
            .order_by(Experiment.created_at)
            .limit(1)
        ).first()
        if experiment is None:
            negotiation = db.scalars(
                select(DemandNegotiation)
                .where(
                    DemandNegotiation.mode == "imported",
                    DemandNegotiation.state == "OWNER_GO_NO_GO",
                    DemandNegotiation.owner_go.is_(True),
                )
                .order_by(DemandNegotiation.updated_at)
                .limit(1)
            ).first()
            if negotiation is not None and negotiation.agreed_currency != "CAD":
                cycle.status = "blocked"
                cycle.rationale = "Owner-approved agreement needs explicit CAD conversion provenance before experiment accounting."
            elif negotiation is not None:
                try:
                    _validate_runtime_negotiation(db, negotiation, {"OWNER_GO_NO_GO"})
                except Exception:
                    return _blocked_cycle(
                        db,
                        state,
                        cycle,
                        "Trusted counterparty receipt could not be verified; cycle blocked.",
                    )
                create_request = ActionRequest(
                    action_type="experiment.create",
                    requesting_agent="CEO Agent",
                    simulation=True,
                    payload={"negotiation_id": negotiation.id},
                )
                create_payload = create_request.model_dump(mode="json", exclude={"approval_id"})
                create_approval_id = matching_approved_id(
                    db,
                    create_request.action_type,
                    create_request.requesting_agent,
                    create_payload,
                )
                if create_approval_id:
                    create_request = create_request.model_copy(update={"approval_id": create_approval_id})
                create_policy = policy_engine.evaluate(db, create_request)
                if create_policy.decision == "ALLOW":
                    expiry = negotiation.expires_at
                    if expiry and expiry.tzinfo is None:
                        expiry = expiry.replace(tzinfo=timezone.utc)
                    duration_days = max(1, min(365, (expiry - datetime.now(timezone.utc)).days + 1)) if expiry else 7
                    experiment = create_experiment(
                        db,
                        ExperimentCreate(
                            title=negotiation.requested_product[:200],
                            hypothesis=f"Deliver the trusted-receipt agreement for {negotiation.counterparty_identity}.",
                            proposed_actions=["Build only the agreed bounded artifact", "Record paper acceptance evidence"],
                            opportunity_id=negotiation.opportunity_id,
                            negotiation_id=negotiation.id,
                            expected_revenue_cents=negotiation.agreed_price_cents or 0,
                            max_loss_cents=0,
                            max_spend_cents=0,
                            duration_days=duration_days,
                            success_criteria=negotiation.acceptance_criteria,
                            kill_criteria="Stop if the agreement expires, scope changes, or the owner freezes autonomy.",
                        ),
                    )
                    if create_approval_id:
                        consume_approval(db, create_approval_id, "CEO Agent")
                else:
                    cycle.status = "awaiting_approval" if create_policy.decision == "REQUIRE_APPROVAL" else "blocked"
                    cycle.rationale = create_policy.reason
            else:
                cycle.status = "blocked"
                cycle.rationale = "No trusted-receipt counterparty agreement with owner go is ready; demo fixtures cannot qualify."

        if experiment is not None and experiment.status in {"DRAFT", "REVIEW", "APPROVED"}:
            negotiation = db.get(DemandNegotiation, experiment.negotiation_id) if experiment.negotiation_id else None
            try:
                if negotiation is None:
                    raise ValueError("experiment negotiation is missing")
                _validate_runtime_negotiation(db, negotiation, ACTIVE_NEGOTIATION_STATES)
            except Exception:
                return _blocked_cycle(
                    db,
                    state,
                    cycle,
                    "Trusted experiment negotiation receipt could not be verified; cycle blocked.",
                )
            if experiment.status == "DRAFT":
                transition_experiment(db, experiment, "REVIEW")
            if experiment.status == "REVIEW":
                transition_experiment(db, experiment, "APPROVED")
            run_request = ActionRequest(
                action_type="experiment.run",
                requesting_agent="CEO Agent",
                simulation=True,
                experiment_id=experiment.id,
            )
            payload = run_request.model_dump(mode="json", exclude={"approval_id"})
            approval_id = matching_approved_id(db, run_request.action_type, run_request.requesting_agent, payload)
            if approval_id:
                run_request = run_request.model_copy(update={"approval_id": approval_id})
            run_policy = policy_engine.evaluate(db, run_request)
            if run_policy.decision == "ALLOW":
                transition_experiment(db, experiment, "RUNNING")
                if approval_id:
                    consume_approval(db, approval_id, "CEO Agent")
                cycle.status = "experiment_started"
                cycle.rationale = "Owner-go agreement resumed into one bounded paper experiment."
            else:
                cycle.status = "awaiting_approval" if run_policy.decision == "REQUIRE_APPROVAL" else "blocked"
                cycle.rationale = run_policy.reason
        elif experiment is not None and experiment.status in {"RUNNING", "PAUSED"}:
            negotiation = db.get(DemandNegotiation, experiment.negotiation_id) if experiment.negotiation_id else None
            try:
                if negotiation is None:
                    raise ValueError("experiment negotiation is missing")
                _validate_runtime_negotiation(db, negotiation, ACTIVE_NEGOTIATION_STATES)
            except Exception:
                return _blocked_cycle(
                    db,
                    state,
                    cycle,
                    "Trusted active experiment receipt could not be verified; cycle blocked.",
                )
            cycle.status = "monitoring"
            cycle.rationale = f"Monitoring bounded experiment {experiment.id}; no external adapter executed."

        cycle.finished_at = utcnow()
        state.cycle_count += 1
        record_audit(db, "ceo_cycle_real_pipeline", "CEO Agent", cycle.rationale, {"cycle_id": cycle.id, "status": cycle.status, "experiment_id": experiment.id if experiment else None})
        db.flush()
        return cycle

    calls = 0
    for opportunity in opportunities:
        if calls >= MAX_TOOL_CALLS or monotonic() >= deadline:
            cycle.tool_calls = calls
            cycle.status = "circuit_breaker"
            cycle.rationale = "cycle reached the tool-call or wall-clock limit"
            cycle.finished_at = utcnow()
            db.flush()
            return cycle
        result = tool_broker.call(
            db,
            ActionRequest(
                action_type="simulation.research",
                requesting_agent="Research Agent",
                simulation=True,
                payload={"evidence": opportunity.evidence, "opportunity_id": opportunity.id},
            ),
        )
        calls += 1
        if result.policy.decision != "ALLOW":
            cycle.status = "failed"
            cycle.rationale = "Research was blocked by policy."
            cycle.finished_at = utcnow()
            db.flush()
            return cycle
    cycle.tool_calls = calls
    cycle.model_cost_cents = 0
    cycle.status = "awaiting_owner_selection" if demo else "blocked"
    cycle.rationale = (
        "Research snapshot recorded; owner must select an opportunity and complete a real receipt-backed negotiation before build."
        if demo
        else cycle.rationale
    )
    cycle.finished_at = utcnow()
    state.cycle_count += 1
    record_audit(db, "ceo_cycle_waiting_for_owner", "CEO Agent", cycle.rationale, {"cycle_id": cycle.id, "opportunity_count": len(opportunities)})
    db.flush()
    return cycle
