from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import record_audit
from .memory import remember
from .models import DemandEvidence, DemandNegotiation, Experiment, Opportunity, Postmortem, utcnow
from .negotiations import begin_build
from .schemas import ExperimentCreate
from .treasury import ensure_paper_treasury, paper_balance


LIFECYCLE = ("DRAFT", "REVIEW", "APPROVED", "RUNNING", "PAUSED", "SUCCESS", "FAILURE", "TERMINATED")
TRANSITIONS = {
    "DRAFT": {"REVIEW", "TERMINATED"},
    "REVIEW": {"APPROVED", "TERMINATED"},
    "APPROVED": {"RUNNING", "TERMINATED"},
    "RUNNING": {"PAUSED", "SUCCESS", "FAILURE", "TERMINATED"},
    "PAUSED": {"RUNNING", "TERMINATED"},
    "SUCCESS": set(),
    "FAILURE": set(),
    "TERMINATED": set(),
}


def create_experiment(
    db: Session,
    data: ExperimentCreate,
    owner_agent: str = "CEO Agent",
    *,
    allow_demo: bool = False,
) -> Experiment:
    if not data.negotiation_id:
        raise ValueError("an experiment requires an owner-approved counterparty negotiation")
    from .runtime import _validate_runtime_negotiation, ensure_state

    # Match the CEO cycle's global lock order: SystemState -> negotiation.
    ensure_state(db)
    negotiation = db.scalars(
        select(DemandNegotiation)
        .where(DemandNegotiation.id == data.negotiation_id)
        .with_for_update()
    ).first()
    if negotiation is None:
        raise KeyError("negotiation not found")
    if negotiation.mode == "demo-only" and not allow_demo:
        raise ValueError("synthetic demo negotiations cannot authorize a real experiment")
    opportunity_id = negotiation.opportunity_id
    if data.opportunity_id and data.opportunity_id != opportunity_id:
        raise ValueError("experiment opportunity must match its gated negotiation")
    opportunity = db.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise KeyError("opportunity not found")
    if db.query(Experiment).filter(Experiment.negotiation_id == negotiation.id).first():
        raise ValueError("a negotiation can authorize only one experiment")
    if negotiation.state not in {"OWNER_GO_NO_GO", "BUILDING"}:
        raise ValueError("experiment requires COUNTERPARTY_AGREED followed by OWNER_GO_NO_GO")
    # Keep the negotiation row locked while revalidating every runtime gate.
    # The CEO cycle uses this same validator; the authenticated manual path
    # must not turn a legacy or tampered state flag into work.
    _validate_runtime_negotiation(db, negotiation, {"OWNER_GO_NO_GO", "BUILDING"})
    if negotiation.agreed_currency != "CAD":
        raise ValueError("experiment accounting requires a CAD agreement; conversion provenance is unavailable")
    if data.max_spend_cents > data.max_loss_cents:
        raise ValueError("experiment max spend cannot exceed max loss")
    stream_type = opportunity.stream_type
    ensure_paper_treasury(db)
    paper_capital = max(1, paper_balance(db))
    if data.max_loss_cents > int(paper_capital * 0.10):
        raise ValueError("experiment risk exceeds the 10% portfolio cap")
    active_experiments = db.query(Experiment).filter(Experiment.status.in_(("DRAFT", "REVIEW", "APPROVED", "RUNNING", "PAUSED"))).all()
    prior_stream_risk = sum(item.max_loss_cents for item in active_experiments if item.stream_type == stream_type)
    if prior_stream_risk + data.max_loss_cents > int(paper_capital * 0.35):
        raise ValueError("stream committed risk exceeds the 35% portfolio cap")
    if sum(item.max_loss_cents for item in active_experiments) + data.max_loss_cents > int(paper_capital * 0.75):
        raise ValueError("committed risk would violate the 25% unallocated reserve")
    evidence = db.get(DemandEvidence, opportunity.demand_evidence_id) if opportunity and opportunity.demand_evidence_id else None
    if evidence:
        platform_risk = 0
        counterparty_risk = 0
        for item in active_experiments:
            item_opportunity = db.get(Opportunity, item.opportunity_id) if item.opportunity_id else None
            item_evidence = db.get(DemandEvidence, item_opportunity.demand_evidence_id) if item_opportunity and item_opportunity.demand_evidence_id else None
            item_negotiation = db.get(DemandNegotiation, item.negotiation_id) if item.negotiation_id else None
            if item_evidence and item_evidence.source_platform == evidence.source_platform:
                platform_risk += item.max_loss_cents
            if item_negotiation and item_negotiation.counterparty_identity == negotiation.counterparty_identity:
                counterparty_risk += item.max_loss_cents
        if max(platform_risk, counterparty_risk) + data.max_loss_cents > int(paper_capital * 0.20):
            raise ValueError("counterparty or platform risk exceeds the 20% concentration cap")
    if stream_type == "bug_bounty" and data.max_spend_cents:
        raise ValueError("bug-bounty experiments have no real spend in this MVP")
    if stream_type == "bug_bounty" and data.max_loss_cents > int(paper_capital * 0.05):
        raise ValueError("bug-bounty paper time/compute risk exceeds the 5% allocation cap")
    if negotiation.state == "OWNER_GO_NO_GO":
        begin_build(db, negotiation)
    experiment = Experiment(
        title=data.title,
        hypothesis=data.hypothesis,
        proposed_actions=data.proposed_actions,
        opportunity_id=opportunity_id,
        negotiation_id=data.negotiation_id,
        stream_type=stream_type,
        expected_revenue_cents=data.expected_revenue_cents,
        max_loss_cents=data.max_loss_cents,
        max_spend_cents=data.max_spend_cents,
        duration_days=data.duration_days,
        success_criteria=data.success_criteria,
        kill_criteria=data.kill_criteria,
        owner_agent=owner_agent,
    )
    db.add(experiment)
    db.flush()
    record_audit(db, "experiment_created", owner_agent, data.title, {"experiment_id": experiment.id})
    return experiment


def transition(db: Session, experiment: Experiment, target: str, actor: str = "CEO Agent") -> Experiment:
    if target not in TRANSITIONS.get(experiment.status, set()):
        raise ValueError(f"invalid experiment transition {experiment.status} -> {target}")
    previous = experiment.status
    experiment.status = target
    if target == "RUNNING":
        experiment.start_date = utcnow()
    if target in {"SUCCESS", "FAILURE", "TERMINATED"}:
        experiment.end_date = utcnow()
    record_audit(db, "experiment_transition", actor, f"{previous} -> {target}", {"experiment_id": experiment.id, "status": target})
    db.flush()
    if target in {"SUCCESS", "FAILURE", "TERMINATED"}:
        write_postmortem(db, experiment)
    return experiment


def recompute_financials(experiment: Experiment) -> None:
    experiment.profit_cents = experiment.revenue_cents - experiment.expenses_cents
    experiment.roi_bps = (
        int(experiment.profit_cents * 10_000 / experiment.expenses_cents)
        if experiment.expenses_cents
        else 0
    )


def write_postmortem(db: Session, experiment: Experiment) -> Postmortem:
    recompute_financials(experiment)
    existing = db.query(Postmortem).filter(Postmortem.experiment_id == experiment.id).first()
    if existing:
        return existing
    success = experiment.status == "SUCCESS"
    postmortem = Postmortem(
        experiment_id=experiment.id,
        hypothesis=experiment.hypothesis,
        actions=experiment.proposed_actions,
        money_spent_cents=experiment.expenses_cents,
        revenue_generated_cents=experiment.revenue_cents,
        profit_loss_cents=experiment.profit_cents,
        conversion_metrics={"simulated_orders": 1 if success else 0, "conversion_bps": 1_000 if success else 0},
        worked="The bounded paper outcome met its declared success gate." if success else "The experiment remained bounded and produced a reviewable outcome.",
        failed="No material failure was recorded in the paper path." if success else "The experiment did not meet its declared success gate.",
        repeat_decision="repeat_scaled" if success else "do_not_repeat",
        reusable_lessons=["Keep first experiments reversible and ledger-backed."] if success else ["Kill losing experiments before expanding spend."],
    )
    db.add(postmortem)
    remember(
        db,
        "experiment" if success else "failure",
        {"experiment_id": experiment.id, "profit_cents": experiment.profit_cents, "lesson": postmortem.reusable_lessons[0]},
        tags=["simulated", "postmortem"],
        experiment_id=experiment.id,
    )
    record_audit(db, "experiment_postmortem", "Verification Agent", "postmortem recorded", {"experiment_id": experiment.id})
    db.flush()
    return postmortem
