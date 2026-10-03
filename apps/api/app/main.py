from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .adapters import MockAdapter
from .agents import SPECIALIST_CONTRACTS, ensure_agents
from .approvals import decide_approval, list_approvals
from .audit import list_audit, record_audit
from .broker import TOOLS, tool_broker
from .bounty import create_finding, create_program_scope, transition_finding, transition_program
from .config import settings
from .db import get_db
from .experiments import create_experiment, transition as transition_experiment
from .memory import retrieve
from .models import (
    AgentState,
    ApprovalEvent,
    AuditEvent,
    BugBountyFinding,
    DemandEvidence,
    DemandNegotiation,
    DeliverableProof,
    Experiment,
    LedgerAccount,
    LedgerTransaction,
    MemoryEntry,
    Opportunity,
    ProgramScope,
    Project,
    SecurityEvent,
    SystemState,
)
from .opportunities import portfolio_snapshot, upsert_opportunities
from .queue import build_queue, cancel_recurring_schedule, create_recurring_schedule, invalidate_recurring_schedule
from .negotiations import (
    begin_negotiating,
    create_deliverable_proof,
    create_negotiation,
    draft_outreach,
    mark_agreement,
    owner_delivery_decision,
    owner_go_no_go,
)
from .runtime import MAX_CYCLES, _validate_runtime_negotiation, ensure_state, run_cycle
from .schemas import (
    ActionRequest,
    ApprovalDecisionRequest,
    BugBountyFindingCreate,
    BugBountyFindingTransitionRequest,
    DemandEvidenceCreate,
    DemandEvidenceVerificationRequest,
    DeliverableProofCreate,
    ExperimentCreate,
    ExperimentTransitionRequest,
    FreezeRequest,
    NegotiationAgreementRequest,
    NegotiationCreate,
    NegotiationDraftRequest,
    OwnerDeliveryDecisionRequest,
    OwnerGoNoGoRequest,
    OpportunityCreate,
    OwnerSettingRequest,
    ProgramScopeCreate,
    ProgramScopeTransitionRequest,
    ProjectCreate,
)
from .security import current_security_state, security_event
from .seed import seed_demo
from .treasury import paper_balance, treasury_snapshot


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="Autonomous Company API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def serialize(value: Any) -> Any:
    if isinstance(value, list):
        return [serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize(item) for key, item in value.items()}
    if hasattr(value, "__table__"):
        return {column.name: serialize(getattr(value, column.name)) for column in value.__table__.columns}
    return jsonable_encoder(value)


def owner_guard(x_owner_token: str | None = Header(default=None)) -> None:
    if not settings.owner_token or not x_owner_token or not secrets.compare_digest(x_owner_token, settings.owner_token):
        raise HTTPException(status_code=403, detail="owner control required")


def state_or_create(db: Session) -> SystemState:
    state = db.get(SystemState, 1)
    if state is None:
        state = SystemState(id=1, real_money_enabled=False)
        db.add(state)
        db.flush()
    return state


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "llm_mode": settings.llm_mode, "queue_mode": settings.queue_mode, "real_money_enabled": False}


def _alembic_heads() -> tuple[str, ...]:
    api_root = Path(__file__).resolve().parents[1]
    config = AlembicConfig(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", str(api_root / "alembic"))
    return tuple(ScriptDirectory.from_config(config).get_heads())


def _verified_schema_revision(db: Session) -> str:
    heads = _alembic_heads()
    if len(heads) != 1:
        raise RuntimeError("local Alembic scripts do not have exactly one head")
    revisions = db.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    if len(revisions) != 1 or revisions[0] != heads[0]:
        raise RuntimeError("database schema revision is not the local Alembic head")
    return revisions[0]


@app.get("/ready")
def readiness(db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        if db.scalar(select(1)) != 1:
            raise RuntimeError("database probe returned an unexpected result")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    try:
        schema_revision = _verified_schema_revision(db)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database schema unavailable") from exc

    dependencies = {"database": "ok", "redis": "disabled"}
    if settings.queue_mode == "redis":
        from redis import Redis

        client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=0.25,
            socket_timeout=0.25,
        )
        try:
            if client.ping() is not True:
                raise RuntimeError("Redis ping returned an unexpected result")
        except Exception as exc:
            raise HTTPException(status_code=503, detail="redis unavailable") from exc
        finally:
            client.close()
        dependencies["redis"] = "ok"
    return {"status": "ready", "dependencies": dependencies, "schema_revision": schema_revision}


@app.get("/api/overview")
def overview(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    state = state_or_create(db)
    snapshot = treasury_snapshot(db)
    portfolio = portfolio_snapshot(db)
    db.commit()
    return {
        "treasury": snapshot,
        "objective": state.objective,
        "owner_goal": state.owner_goal,
        "autonomy_level": state.autonomy_level,
        "active_experiments": db.query(Experiment).filter(Experiment.status.in_(["RUNNING", "PAUSED"])).count(),
        "opportunities": db.query(Opportunity).count(),
        "pending_approvals": sum(1 for item in list_approvals(db, 200) if item["status"] == "PENDING"),
        "portfolio": portfolio,
        "security": current_security_state(db),
        "cycle_count": state.cycle_count,
        "model_cost_cents": state.model_cost_cents,
    }


@app.get("/api/ceo")
def ceo_state(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    state = state_or_create(db)
    latest = db.query(Experiment).order_by(Experiment.created_at.desc()).first()
    return {
        "objective": state.objective,
        "owner_goal": state.owner_goal,
        "strategy": state.strategy,
        "autonomy_level": state.autonomy_level,
        "frozen": state.frozen,
        "latest_experiment": serialize(latest) if latest else None,
    }


@app.post("/api/ceo/cycle")
def ceo_cycle(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    cycle = run_cycle(db)
    db.commit()
    return serialize(cycle)


@app.post("/api/ceo/schedule")
def schedule_cycle(
    delay_seconds: int = Query(default=0, ge=0, le=86_400),
    recurring: bool = False,
    interval_seconds: int = Query(default=3_600, ge=60, le=86_400),
    db: Session = Depends(get_db),
    _: None = Depends(owner_guard),
) -> dict[str, Any]:
    state = state_or_create(db)
    if state.frozen:
        raise HTTPException(status_code=409, detail="autonomy is frozen")
    if delay_seconds and not recurring:
        raise HTTPException(
            status_code=400,
            detail="delayed one-shot CEO cycles are disabled; use an immediate cycle or a fenced recurring schedule",
        )
    if settings.queue_mode == "direct":
        if delay_seconds or recurring:
            raise HTTPException(status_code=400, detail="delayed or recurring scheduling requires QUEUE_MODE=redis")
        cycle = run_cycle(db)
        record_audit(db, "cycle_scheduled", "owner", "direct mode executed one bounded cycle", {"cycle_id": cycle.id})
        db.commit()
        return {"scheduled": True, "executed": True, "mode": "direct", "cycle": serialize(cycle)}
    if recurring:
        try:
            schedule = create_recurring_schedule(db, interval_seconds, MAX_CYCLES)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        generation = schedule.generation
        payload = {
            "demo": False,
            "recurring": True,
            "schedule_generation": generation,
        }
        # Make the generation visible before an immediate Redis worker can
        # claim it. If enqueue fails after accepting the job, invalidating the
        # generation makes that job harmless.
        record_audit(
            db,
            "cycle_schedule_reserved",
            "owner",
            "durable recurring CEO schedule generation reserved",
            {"schedule_generation": generation, "remaining_runs": schedule.remaining_runs},
        )
        db.commit()
        try:
            queued = build_queue().enqueue(
                "ceo_cycle",
                payload,
                delay_seconds=delay_seconds,
                repeat_seconds=interval_seconds,
                repeat_times=max(0, MAX_CYCLES - 1),
            )
        except Exception:
            invalidated = cancel_recurring_schedule(db)
            record_audit(
                db,
                "cycle_schedule_enqueue_failed",
                "owner",
                "recurring CEO schedule generation invalidated after enqueue failure",
                {"schedule_generation": generation, "replacement_generation": invalidated.generation},
            )
            db.commit()
            raise
        record_audit(db, "cycle_scheduled", "owner", "Redis recurring CEO schedule queued", queued)
        db.commit()
        return {
            "scheduled": True,
            "executed": False,
            "schedule_generation": generation,
            "remaining_runs": MAX_CYCLES,
            **queued,
        }
    queued = build_queue().enqueue(
        "ceo_cycle",
        {"demo": False},
        delay_seconds=delay_seconds,
        repeat_seconds=interval_seconds if recurring else 0,
        repeat_times=MAX_CYCLES if recurring else 0,
    )
    record_audit(db, "cycle_scheduled", "owner", "Redis wake-up queued", queued)
    db.commit()
    return {"scheduled": True, "executed": False, **queued}


@app.post("/api/ceo/schedule/cancel")
def cancel_schedule(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    schedule = cancel_recurring_schedule(db)
    record_audit(
        db,
        "cycle_schedule_cancelled",
        "owner",
        "owner cancelled the recurring CEO schedule",
        {"schedule_generation": schedule.generation},
    )
    db.commit()
    return {"cancelled": True, "active": schedule.active, "schedule_generation": schedule.generation}


@app.get("/api/agents")
def agents(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> list[dict[str, Any]]:
    ensure_agents(db)
    return [serialize(agent) for agent in db.scalars(select(AgentState).order_by(AgentState.role))]


@app.get("/api/opportunities")
def opportunities(db: Session = Depends(get_db), limit: int = Query(default=100, le=500), _: None = Depends(owner_guard)) -> list[dict[str, Any]]:
    return [serialize(item) for item in db.scalars(select(Opportunity).order_by(Opportunity.score_bps.desc()).limit(limit))]


@app.get("/api/demand-evidence")
def demand_evidence(db: Session = Depends(get_db), limit: int = Query(default=100, le=500), _: None = Depends(owner_guard)) -> list[dict[str, Any]]:
    return [serialize(item) for item in db.scalars(select(DemandEvidence).order_by(DemandEvidence.captured_at.desc()).limit(limit))]


@app.post("/api/demand-evidence")
def import_demand_evidence(
    data: DemandEvidenceCreate,
    db: Session = Depends(get_db),
    _: None = Depends(owner_guard),
) -> dict[str, Any]:
    evidence = DemandEvidence(
        source_url=str(data.source_url),
        source_platform=data.source_platform,
        buyer_identity=data.buyer_identity,
        captured_at=data.captured_at,
        status_checked_at=data.status_checked_at,
        quoted_need=data.quoted_need,
        stated_budget_cents=data.stated_budget_cents,
        stated_currency=data.stated_currency,
        content_hash=data.content_hash,
        external_content_untrusted=True,
        # A caller-supplied boolean is not source verification.  Verification
        # can only be recorded by the receipt endpoint below.
        verification_status="imported_unverified",
        verification_receipt={},
        source_verified_at=None,
    )
    db.add(evidence)
    record_audit(db, "demand_evidence_imported", "owner", "External content remains untrusted until a persisted source receipt is recorded.", {"source_url": evidence.source_url, "verification_status": evidence.verification_status, "requested_verified_snapshot": data.verified_snapshot})
    db.commit()
    return serialize(evidence)


@app.post("/api/demand-evidence/{evidence_id}/verification-receipt")
def verify_demand_evidence(
    evidence_id: str,
    data: DemandEvidenceVerificationRequest,
    db: Session = Depends(get_db),
    _: None = Depends(owner_guard),
) -> dict[str, Any]:
    evidence = db.get(DemandEvidence, evidence_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="demand evidence not found")
    if str(data.source_url).rstrip("/") != evidence.source_url.rstrip("/"):
        raise HTTPException(status_code=400, detail="receipt source_url does not match imported evidence")
    if data.content_hash != evidence.content_hash:
        raise HTTPException(status_code=400, detail="receipt content_hash does not match imported evidence")
    observed_at = data.observed_at if data.observed_at.tzinfo else data.observed_at.replace(tzinfo=timezone.utc)
    if observed_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise HTTPException(status_code=400, detail="receipt observation time cannot be in the future")
    if data.source_http_status >= 400:
        raise HTTPException(status_code=400, detail="qualifying demand requires a reachable source receipt")
    evidence.verification_receipt = data.model_dump(mode="json")
    evidence.source_verified_at = data.observed_at
    evidence.verification_status = "operator_attested_source_receipt"
    record_audit(db, "demand_evidence_source_attested", "owner", "Operator-attested source receipt recorded; this is not platform authentication and content remains untrusted.", {"evidence_id": evidence.id, "receipt_id": data.receipt_id, "source_url": evidence.source_url})
    db.commit()
    return serialize(evidence)


@app.post("/api/opportunities")
def add_opportunity(data: OpportunityCreate, db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    if data.source != "demo-local-fallback" and not data.demand_evidence_id:
        raise HTTPException(status_code=400, detail="imported opportunities require demand_evidence_id")
    evidence = db.get(DemandEvidence, data.demand_evidence_id) if data.demand_evidence_id else None
    if data.demand_evidence_id and evidence is None:
        raise HTTPException(status_code=404, detail="demand evidence not found")
    if data.source != "demo-local-fallback" and (evidence is None or evidence.verification_status != "operator_attested_source_receipt" or not evidence.verification_receipt):
        raise HTTPException(status_code=400, detail="live opportunities require an operator-attested source receipt")
    rows = upsert_opportunities(db, [data.model_dump()])
    db.commit()
    return serialize(rows[0])


@app.get("/api/portfolio")
def portfolio(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    return portfolio_snapshot(db)


@app.get("/api/bug-bounty/programs")
def bug_bounty_programs(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> list[dict[str, Any]]:
    return [serialize(item) for item in db.scalars(select(ProgramScope).order_by(ProgramScope.updated_at.desc()))]


@app.post("/api/bug-bounty/programs")
def import_bug_bounty_program(data: ProgramScopeCreate, db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    try:
        program = create_program_scope(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return serialize(program)


@app.post("/api/bug-bounty/programs/{program_id}/transition")
def transition_bug_bounty_program(
    program_id: str,
    data: ProgramScopeTransitionRequest,
    db: Session = Depends(get_db),
    _: None = Depends(owner_guard),
) -> dict[str, Any]:
    program = db.get(ProgramScope, program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="bug-bounty program not found")
    try:
        transition_program(db, program, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return serialize(program)


@app.get("/api/bug-bounty/findings")
def bug_bounty_findings(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> list[dict[str, Any]]:
    return [serialize(item) for item in db.scalars(select(BugBountyFinding).order_by(BugBountyFinding.updated_at.desc()))]


@app.post("/api/bug-bounty/programs/{program_id}/findings")
def add_bug_bounty_finding(
    program_id: str,
    data: BugBountyFindingCreate,
    db: Session = Depends(get_db),
    _: None = Depends(owner_guard),
) -> dict[str, Any]:
    program = db.get(ProgramScope, program_id)
    if program is None:
        raise HTTPException(status_code=404, detail="bug-bounty program not found")
    try:
        finding = create_finding(db, program, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return serialize(finding)


@app.post("/api/bug-bounty/findings/{finding_id}/transition")
def transition_bug_bounty_finding(
    finding_id: str,
    data: BugBountyFindingTransitionRequest,
    db: Session = Depends(get_db),
    _: None = Depends(owner_guard),
) -> dict[str, Any]:
    finding = db.get(BugBountyFinding, finding_id)
    if finding is None:
        raise HTTPException(status_code=404, detail="bug-bounty finding not found")
    try:
        transition_finding(db, finding, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return serialize(finding)


@app.get("/api/experiments")
def experiments(db: Session = Depends(get_db), limit: int = Query(default=100, le=500), _: None = Depends(owner_guard)) -> list[dict[str, Any]]:
    return [serialize(item) for item in db.scalars(select(Experiment).order_by(Experiment.created_at.desc()).limit(limit))]


@app.post("/api/experiments")
def add_experiment(data: ExperimentCreate, db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    try:
        experiment = create_experiment(db, data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return serialize(experiment)


@app.post("/api/experiments/{experiment_id}/transition")
def transition_experiment_state(
    experiment_id: str,
    data: ExperimentTransitionRequest,
    db: Session = Depends(get_db),
    _: None = Depends(owner_guard),
) -> dict[str, Any]:
    # Match the CEO cycle's global lock order: SystemState -> Experiment.
    ensure_state(db)
    experiment = db.scalars(
        select(Experiment)
        .where(Experiment.id == experiment_id)
        .with_for_update()
    ).first()
    if experiment is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    if data.target == "RUNNING":
        raise HTTPException(
            status_code=409,
            detail="starting an experiment requires the receipt-revalidating CEO cycle and policy approval",
        )
    try:
        transition_experiment(db, experiment, data.target, actor="owner")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return serialize(experiment)


@app.get("/api/negotiations")
def negotiations(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> list[dict[str, Any]]:
    return [serialize(item) for item in db.scalars(select(DemandNegotiation).order_by(DemandNegotiation.updated_at.desc()))]


@app.post("/api/negotiations")
def add_negotiation(data: NegotiationCreate, db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    try:
        negotiation = create_negotiation(db, data)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return serialize(negotiation)


@app.post("/api/negotiations/{negotiation_id}/outreach-draft")
def outreach_draft(
    negotiation_id: str,
    data: NegotiationDraftRequest,
    db: Session = Depends(get_db),
    _: None = Depends(owner_guard),
) -> dict[str, Any]:
    negotiation = db.get(DemandNegotiation, negotiation_id)
    if negotiation is None:
        raise HTTPException(status_code=404, detail="negotiation not found")
    try:
        draft_outreach(db, negotiation, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return serialize(negotiation)


@app.post("/api/negotiations/{negotiation_id}/start")
def start_negotiation(
    negotiation_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(owner_guard),
) -> dict[str, Any]:
    negotiation = db.get(DemandNegotiation, negotiation_id)
    if negotiation is None:
        raise HTTPException(status_code=404, detail="negotiation not found")
    try:
        begin_negotiating(db, negotiation)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return serialize(negotiation)


@app.post("/api/negotiations/{negotiation_id}/agreement")
def agreement(
    negotiation_id: str,
    data: NegotiationAgreementRequest,
    db: Session = Depends(get_db),
    _: None = Depends(owner_guard),
) -> dict[str, Any]:
    negotiation = db.get(DemandNegotiation, negotiation_id)
    if negotiation is None:
        raise HTTPException(status_code=404, detail="negotiation not found")
    try:
        mark_agreement(db, negotiation, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return serialize(negotiation)


@app.post("/api/negotiations/{negotiation_id}/go-no-go")
def go_no_go(
    negotiation_id: str,
    data: OwnerGoNoGoRequest,
    db: Session = Depends(get_db),
    _: None = Depends(owner_guard),
) -> dict[str, Any]:
    negotiation = db.get(DemandNegotiation, negotiation_id)
    if negotiation is None:
        raise HTTPException(status_code=404, detail="negotiation not found")
    try:
        owner_go_no_go(db, negotiation, data.go)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return serialize(negotiation)


@app.post("/api/negotiations/{negotiation_id}/delivery-decision")
def delivery_decision(
    negotiation_id: str,
    data: OwnerDeliveryDecisionRequest,
    db: Session = Depends(get_db),
    _: None = Depends(owner_guard),
) -> dict[str, Any]:
    negotiation = db.get(DemandNegotiation, negotiation_id)
    if negotiation is None:
        raise HTTPException(status_code=404, detail="negotiation not found")
    try:
        owner_delivery_decision(db, negotiation, data.decision)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return serialize(negotiation)


@app.get("/api/deliverable-proofs")
def deliverable_proofs(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> list[dict[str, Any]]:
    return [serialize(item) for item in db.scalars(select(DeliverableProof).order_by(DeliverableProof.created_at.desc()))]


@app.get("/api/experiments/{experiment_id}/deliverable-proof")
def experiment_deliverable_proof(experiment_id: str, db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    proof = db.scalars(select(DeliverableProof).where(DeliverableProof.experiment_id == experiment_id)).first()
    if proof is None:
        raise HTTPException(status_code=404, detail="deliverable proof not found")
    return serialize(proof)


@app.post("/api/experiments/{experiment_id}/deliverable-proof")
def add_deliverable_proof(
    experiment_id: str,
    data: DeliverableProofCreate,
    db: Session = Depends(get_db),
    _: None = Depends(owner_guard),
) -> dict[str, Any]:
    experiment = db.get(Experiment, experiment_id)
    if experiment is None or not experiment.negotiation_id:
        raise HTTPException(status_code=404, detail="experiment negotiation not found")
    negotiation = db.get(DemandNegotiation, experiment.negotiation_id)
    if negotiation is None:
        raise HTTPException(status_code=404, detail="negotiation not found")
    try:
        proof = create_deliverable_proof(db, negotiation, experiment.id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return serialize(proof)


@app.get("/api/projects")
def projects(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> list[dict[str, Any]]:
    return [serialize(item) for item in db.scalars(select(Project).order_by(Project.created_at.desc()))]


@app.post("/api/projects")
def add_project(data: ProjectCreate, db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    if data.negotiation_id:
        # Match the CEO cycle's global lock order: SystemState -> negotiation.
        ensure_state(db)
    negotiation = (
        db.scalars(
            select(DemandNegotiation)
            .where(DemandNegotiation.id == data.negotiation_id)
            .with_for_update()
        ).first()
        if data.negotiation_id
        else None
    )
    if data.negotiation_id and negotiation is None:
        raise HTTPException(status_code=404, detail="negotiation not found")
    if negotiation is not None:
        try:
            _validate_runtime_negotiation(db, negotiation, {"OWNER_GO_NO_GO", "BUILDING"})
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    project = Project(
        **data.model_dump(exclude={"negotiation_id"}),
        negotiation_id=negotiation.id if negotiation else None,
        execution_enabled=bool(negotiation and negotiation.state == "BUILDING"),
    )
    db.add(project)
    db.commit()
    return serialize(project)


@app.get("/api/treasury")
def treasury(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    snapshot = treasury_snapshot(db)
    state = state_or_create(db)
    db.commit()
    return {**snapshot, "goal_reserve_cents": state.goal_reserve_cents, "currency": "CAD", "unit": "cents"}


@app.get("/api/transactions")
def transactions(db: Session = Depends(get_db), limit: int = Query(default=200, le=1000), _: None = Depends(owner_guard)) -> list[dict[str, Any]]:
    accounts = {account.id: account.name for account in db.scalars(select(LedgerAccount))}
    return [
        {
            **serialize(item),
            "debit_account": accounts.get(item.debit_account_id),
            "credit_account": accounts.get(item.credit_account_id),
        }
        for item in db.scalars(select(LedgerTransaction).order_by(LedgerTransaction.created_at.desc()).limit(limit))
    ]


@app.get("/api/approvals")
def approvals(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> list[dict[str, Any]]:
    return serialize(list_approvals(db))


@app.post("/api/approvals/{approval_id}/decision")
def approval_decision(
    approval_id: str,
    data: ApprovalDecisionRequest,
    db: Session = Depends(get_db),
    _: None = Depends(owner_guard),
) -> dict[str, Any]:
    try:
        event = decide_approval(db, approval_id, data.decision, "owner", data.edits)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return serialize(event)


@app.get("/api/memory")
def memory(db: Session = Depends(get_db), kind: str | None = None, tag: str | None = None, _: None = Depends(owner_guard)) -> list[dict[str, Any]]:
    return serialize(retrieve(db, kind=kind, tag=tag))


@app.get("/api/tools")
def tools(_: None = Depends(owner_guard)) -> list[dict[str, Any]]:
    schema = ActionRequest.model_json_schema()
    return [{**tool.__dict__, "parameter_schema": schema} for tool in TOOLS]


@app.post("/api/tools/call")
def call_tool(request: ActionRequest, db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    result = tool_broker.call(db, request)
    db.commit()
    return {"policy": serialize(result.policy), "executed": result.executed, "output": result.output}


@app.get("/api/audit")
def audit(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> list[dict[str, Any]]:
    return serialize(list_audit(db))


@app.get("/api/security")
def security(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    return serialize(current_security_state(db))


@app.get("/api/settings")
def settings_view(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    state = state_or_create(db)
    return {
        "autonomy_level": state.autonomy_level,
        "real_money_enabled": False,
        # Keep the public mode paper-only while making a legacy/manual unsafe
        # persisted value visible to the owner instead of silently masking it.
        "real_money_enabled_stored": bool(state.real_money_enabled),
        "real_money_forced_off": True,
        "objective": state.objective,
        "strategy": state.strategy,
        "owner_goal": state.owner_goal,
        "limits": {
            "global_spend_cents": state.global_spend_limit_cents,
            "per_transaction_cents": state.per_transaction_limit_cents,
            "daily_spend_cents": state.daily_spend_limit_cents,
            "approval_threshold_cents": state.approval_threshold_cents,
            "model_cost_limit_cents": state.model_cost_limit_cents,
            "api_cost_limit_cents": state.api_cost_limit_cents,
        },
        "policy_controls": {
            "category_allowlist": state.category_allowlist,
            "category_denylist": state.category_denylist,
            "category_limits_cents": state.category_limits_cents,
            "counterparty_allowlist": state.counterparty_allowlist,
            "counterparty_denylist": state.counterparty_denylist,
            "domain_allowlist": state.domain_allowlist,
            "domain_denylist": state.domain_denylist,
            "rate_limits": state.rate_limits,
        },
    }


@app.patch("/api/settings")
def update_settings(
    data: OwnerSettingRequest,
    db: Session = Depends(get_db),
    _: None = Depends(owner_guard),
) -> dict[str, Any]:
    state = db.scalars(
        select(SystemState).where(SystemState.id == 1).with_for_update()
    ).first()
    if state is None:
        state = SystemState(id=1, real_money_enabled=False)
        db.add(state)
        db.flush()
    if data.real_money_enabled:
        raise HTTPException(status_code=400, detail="real-money mode is disabled in the simulated MVP")
    if data.real_money_enabled is False:
        state.real_money_enabled = False
    if data.autonomy_level is not None:
        state.autonomy_level = data.autonomy_level
    if data.objective is not None:
        state.objective = data.objective
    if data.strategy is not None:
        state.strategy = data.strategy
    for field in (
        "global_spend_limit_cents",
        "per_transaction_limit_cents",
        "daily_spend_limit_cents",
        "approval_threshold_cents",
        "model_cost_limit_cents",
        "api_cost_limit_cents",
        "category_allowlist",
        "category_denylist",
        "category_limits_cents",
        "counterparty_allowlist",
        "counterparty_denylist",
        "domain_allowlist",
        "domain_denylist",
        "rate_limits",
    ):
        value = getattr(data, field)
        if value is not None:
            setattr(state, field, value)
    record_audit(db, "settings_changed", "owner", "owner control update", data.model_dump(exclude_none=True))
    db.commit()
    return settings_view(db)


@app.post("/api/security/freeze")
def freeze(
    data: FreezeRequest,
    db: Session = Depends(get_db),
    _: None = Depends(owner_guard),
) -> dict[str, Any]:
    state = db.scalars(
        select(SystemState).where(SystemState.id == 1).with_for_update()
    ).first()
    if state is None:
        state = SystemState(id=1, real_money_enabled=False)
        db.add(state)
        db.flush()
    state.frozen = True
    state.freeze_reason = data.reason
    invalidate_recurring_schedule(db)
    security_event(db, "HIGH", "owner_freeze", {"reason": data.reason}, freeze=False)
    db.commit()
    return {"frozen": True, "reason": data.reason}


@app.post("/api/security/unfreeze")
def unfreeze(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    state = db.scalars(
        select(SystemState).where(SystemState.id == 1).with_for_update()
    ).first()
    if state is None:
        state = SystemState(id=1, real_money_enabled=False)
        db.add(state)
        db.flush()
    state.frozen = False
    state.freeze_reason = None
    record_audit(db, "autonomy_unfrozen", "owner", "owner restored autonomy", {})
    db.commit()
    return {"frozen": False}


@app.post("/api/demo/seed")
def demo_seed(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    state = seed_demo(db)
    db.commit()
    return {"seeded": True, "autonomy_level": state.autonomy_level, "treasury_cents": settings.paper_treasury_cents}


@app.post("/api/demo/cycle")
def demo_cycle(db: Session = Depends(get_db), _: None = Depends(owner_guard)) -> dict[str, Any]:
    seed_demo(db)
    cycle = run_cycle(db, demo=True)
    db.commit()
    return serialize(cycle)
