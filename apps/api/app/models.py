from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class SystemState(Base):
    __tablename__ = "system_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    objective: Mapped[str] = mapped_column(Text, default="Increase long-term legitimate economic profit.")
    strategy: Mapped[str] = mapped_column(Text, default="Prefer reversible, evidence-backed paper experiments.")
    owner_goal: Mapped[str] = mapped_column(Text, default="Retain legitimate surplus toward a future equipment goal.")
    autonomy_level: Mapped[int] = mapped_column(Integer, default=0)
    real_money_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    frozen: Mapped[bool] = mapped_column(Boolean, default=False)
    freeze_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cycle_count: Mapped[int] = mapped_column(Integer, default=0)
    global_spend_limit_cents: Mapped[int] = mapped_column(Integer, default=50_000)
    per_transaction_limit_cents: Mapped[int] = mapped_column(Integer, default=500)
    daily_spend_limit_cents: Mapped[int] = mapped_column(Integer, default=5_000)
    approval_threshold_cents: Mapped[int] = mapped_column(Integer, default=250)
    model_cost_limit_cents: Mapped[int] = mapped_column(Integer, default=1_000)
    global_spend_cents: Mapped[int] = mapped_column(Integer, default=0)
    daily_spend_cents: Mapped[int] = mapped_column(Integer, default=0)
    model_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    api_cost_limit_cents: Mapped[int] = mapped_column(Integer, default=1_000)
    api_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    category_allowlist: Mapped[list[str]] = mapped_column(JSON, default=list)
    category_denylist: Mapped[list[str]] = mapped_column(JSON, default=list)
    category_limits_cents: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    counterparty_allowlist: Mapped[list[str]] = mapped_column(JSON, default=list)
    counterparty_denylist: Mapped[list[str]] = mapped_column(JSON, default=list)
    domain_allowlist: Mapped[list[str]] = mapped_column(JSON, default=list)
    domain_denylist: Mapped[list[str]] = mapped_column(JSON, default=list)
    rate_limits: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        default=lambda: {"*": {"max_requests": 60, "window_seconds": 60}},
    )
    goal_reserve_cents: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CeoSchedule(Base):
    """Singleton durable fence for recurring CEO wake-ups."""

    __tablename__ = "ceo_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    generation: Mapped[str] = mapped_column(String(36), unique=True, default=uid)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    remaining_runs: Mapped[int] = mapped_column(Integer, default=0)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=3_600)
    running: Mapped[bool] = mapped_column(Boolean, default=False)
    run_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AgentState(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    role: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    instructions: Mapped[str] = mapped_column(Text)
    permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Counterparty(Base):
    __tablename__ = "counterparties"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(60), default="simulated")
    status: Mapped[str] = mapped_column(String(30), default="approved")
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    negotiation_id: Mapped[str | None] = mapped_column(ForeignKey("demand_negotiations.id"), nullable=True)
    execution_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    concept: Mapped[str] = mapped_column(Text)
    customer_problem: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(Text, default="")
    solution: Mapped[str] = mapped_column(Text, default="")
    price_cents: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    analytics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DemandEvidence(Base):
    __tablename__ = "demand_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    source_url: Mapped[str] = mapped_column(Text)
    source_platform: Mapped[str] = mapped_column(String(80))
    buyer_identity: Mapped[str] = mapped_column(String(200))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status_checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quoted_need: Mapped[str] = mapped_column(Text)
    stated_budget_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stated_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(128))
    external_content_untrusted: Mapped[bool] = mapped_column(Boolean, default=True)
    verification_status: Mapped[str] = mapped_column(String(40), default="imported_unverified")
    verification_receipt: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(80))
    # Shared portfolio key.  Stream-specific policy is applied at the gate;
    # evidence, approvals, experiments, and paper ledger remain shared.
    stream_type: Mapped[str] = mapped_column(String(40), default="agent_services", index=True)
    demand_evidence_id: Mapped[str | None] = mapped_column(ForeignKey("demand_evidence.id"), nullable=True)
    mechanism: Mapped[str] = mapped_column(String(80), default="service")
    source: Mapped[str] = mapped_column(String(80), default="simulation")
    hypothesis: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text, default="")
    expected_revenue_cents: Mapped[int] = mapped_column(Integer, default=0)
    max_downside_cents: Mapped[int] = mapped_column(Integer, default=0)
    required_capital_cents: Mapped[int] = mapped_column(Integer, default=0)
    time_to_revenue_days: Mapped[int] = mapped_column(Integer, default=30)
    margin_bps: Mapped[int] = mapped_column(Integer, default=0)
    execution_difficulty: Mapped[int] = mapped_column(Integer, default=1)
    confidence_bps: Mapped[int] = mapped_column(Integer, default=0)
    reversibility_bps: Mapped[int] = mapped_column(Integer, default=0)
    legal_risk_bps: Mapped[int] = mapped_column(Integer, default=0)
    evidence_strength_bps: Mapped[int] = mapped_column(Integer, default=0)
    score_bps: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="candidate", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DemandNegotiation(Base):
    __tablename__ = "demand_negotiations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunities.id"), index=True)
    mode: Mapped[str] = mapped_column(String(30), default="imported")
    state: Mapped[str] = mapped_column(String(40), default="DEMAND_DISCOVERED", index=True)
    counterparty_identity: Mapped[str] = mapped_column(String(200))
    requested_product: Mapped[str] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(Text, default="")
    acceptance_criteria: Mapped[str] = mapped_column(Text, default="")
    agreed_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agreed_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    counterparty_agreed: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_go: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_delivery_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    remote_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    content_hashes: Mapped[list[str]] = mapped_column(JSON, default=list)
    external_receipt: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Cycle(Base):
    __tablename__ = "cycles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    rationale: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[int] = mapped_column(Integer, default=0)
    turns: Mapped[int] = mapped_column(Integer, default=0)
    model_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    opportunity_id: Mapped[str | None] = mapped_column(ForeignKey("opportunities.id"), nullable=True)
    negotiation_id: Mapped[str | None] = mapped_column(ForeignKey("demand_negotiations.id"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    stream_type: Mapped[str] = mapped_column(String(40), default="agent_services", index=True)
    title: Mapped[str] = mapped_column(String(200))
    hypothesis: Mapped[str] = mapped_column(Text)
    proposed_actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    expected_revenue_cents: Mapped[int] = mapped_column(Integer, default=0)
    max_loss_cents: Mapped[int] = mapped_column(Integer, default=0)
    max_spend_cents: Mapped[int] = mapped_column(Integer, default=0)
    duration_days: Mapped[int] = mapped_column(Integer, default=7)
    success_criteria: Mapped[str] = mapped_column(Text, default="")
    kill_criteria: Mapped[str] = mapped_column(Text, default="")
    confidence_bps: Mapped[int] = mapped_column(Integer, default=0)
    owner_agent: Mapped[str] = mapped_column(String(80), default="CEO Agent")
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revenue_cents: Mapped[int] = mapped_column(Integer, default=0)
    expenses_cents: Mapped[int] = mapped_column(Integer, default=0)
    profit_cents: Mapped[int] = mapped_column(Integer, default=0)
    roi_bps: Mapped[int] = mapped_column(Integer, default=0)
    outcome_action: Mapped[str | None] = mapped_column(String(30), nullable=True)
    observations: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Postmortem(Base):
    __tablename__ = "postmortems"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), unique=True)
    hypothesis: Mapped[str] = mapped_column(Text)
    actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    money_spent_cents: Mapped[int] = mapped_column(Integer, default=0)
    revenue_generated_cents: Mapped[int] = mapped_column(Integer, default=0)
    profit_loss_cents: Mapped[int] = mapped_column(Integer, default=0)
    conversion_metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    worked: Mapped[str] = mapped_column(Text, default="")
    failed: Mapped[str] = mapped_column(Text, default="")
    repeat_decision: Mapped[str] = mapped_column(String(30), default="review")
    reusable_lessons: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DeliverableProof(Base):
    __tablename__ = "deliverable_proofs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), unique=True)
    artifact_manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    buyer_response: Mapped[str] = mapped_column(String(30), default="NOT_CONTACTED")
    acceptance: Mapped[str] = mapped_column(String(30), default="SIMULATED")
    settlement: Mapped[str] = mapped_column(String(20), default="PAPER")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProgramScope(Base):
    """Imported bug-bounty scope; never a live testing credential or adapter."""

    __tablename__ = "program_scopes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    program_url: Mapped[str] = mapped_column(Text)
    assets_in_scope: Mapped[list[str]] = mapped_column(JSON, default=list)
    assets_out_of_scope: Mapped[list[str]] = mapped_column(JSON, default=list)
    safe_harbor: Mapped[str] = mapped_column(Text, default="")
    rules: Mapped[list[str]] = mapped_column(JSON, default=list)
    rate_limits: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    test_plan: Mapped[str] = mapped_column(Text, default="")
    test_account_requirements: Mapped[str] = mapped_column(Text, default="")
    required_headers: Mapped[list[str]] = mapped_column(JSON, default=list)
    payout_tiers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    disclosure_policy: Mapped[str] = mapped_column(Text, default="")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(40), default="PROGRAM_DISCOVERED", index=True)
    owner_target_authorized: Mapped[bool] = mapped_column(Boolean, default=False)
    authorized_assets: Mapped[list[str]] = mapped_column(JSON, default=list)
    payment_evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    paper_outcome: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class BugBountyFinding(Base):
    """Passive finding/report record with explicit owner and payment gates."""

    __tablename__ = "bug_bounty_findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    program_scope_id: Mapped[str] = mapped_column(ForeignKey("program_scopes.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    asset: Mapped[str] = mapped_column(String(300))
    severity: Mapped[str] = mapped_column(String(30), default="informational")
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(40), default="FINDING_VALIDATED", index=True)
    validation_notes: Mapped[str] = mapped_column(Text, default="")
    duplicate_reference: Mapped[str | None] = mapped_column(String(300), nullable=True)
    payout_cents: Mapped[int] = mapped_column(Integer, default=0)
    payment_evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    paper_outcome: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_submission_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    public_disclosure_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class MemoryEntry(Base):
    __tablename__ = "memory_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    experiment_id: Mapped[str | None] = mapped_column(ForeignKey("experiments.id"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LedgerAccount(Base):
    __tablename__ = "ledger_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    kind: Mapped[str] = mapped_column(String(30))
    currency: Mapped[str] = mapped_column(String(3), default="CAD")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LedgerTransaction(Base):
    __tablename__ = "ledger_transactions"
    __table_args__ = (
        Index(
            "uq_ledger_transactions_paper_opening",
            "external_reference",
            unique=True,
            sqlite_where=text("external_reference = 'paper-opening'"),
            postgresql_where=text("external_reference = 'paper-opening'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    currency: Mapped[str] = mapped_column(String(3), default="CAD")
    amount_cents: Mapped[int] = mapped_column(Integer)
    debit_account_id: Mapped[str] = mapped_column(ForeignKey("ledger_accounts.id"))
    credit_account_id: Mapped[str] = mapped_column(ForeignKey("ledger_accounts.id"))
    experiment_id: Mapped[str | None] = mapped_column(ForeignKey("experiments.id"), nullable=True)
    agent: Mapped[str] = mapped_column(String(80), default="system")
    external_reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    policy_decision_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="settled", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    action_type: Mapped[str] = mapped_column(String(100), index=True)
    requesting_agent: Mapped[str] = mapped_column(String(80))
    decision: Mapped[str] = mapped_column(String(30), index=True)
    reason: Mapped[str] = mapped_column(Text)
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    policy_name: Mapped[str] = mapped_column(String(100), default="default")
    rate_limit_key: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str] = mapped_column(String(100), default="system")
    rationale: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    froze_autonomy: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    approval_class: Mapped[str] = mapped_column(String(50), index=True)
    requested_by: Mapped[str] = mapped_column(String(100))
    action_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApprovalEvent(Base):
    __tablename__ = "approval_events"
    __table_args__ = (UniqueConstraint("approval_id", "event_id", name="uq_approval_event"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    approval_id: Mapped[str] = mapped_column(ForeignKey("approval_requests.id"), index=True)
    event_id: Mapped[str] = mapped_column(String(36), default=uid)
    event: Mapped[str] = mapped_column(String(30), index=True)
    actor: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelUsage(Base):
    __tablename__ = "model_usage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    agent: Mapped[str] = mapped_column(String(80))
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cycle_id: Mapped[str | None] = mapped_column(ForeignKey("cycles.id"), nullable=True)
    experiment_id: Mapped[str | None] = mapped_column(ForeignKey("experiments.id"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    model_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    api_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_cents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
