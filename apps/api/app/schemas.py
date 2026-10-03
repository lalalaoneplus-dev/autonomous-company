from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator


Decision = Literal["ALLOW", "DENY", "REQUIRE_APPROVAL"]


class ActionRequest(BaseModel):
    action_type: str
    requesting_agent: str = "CEO Agent"
    autonomy_required: int = Field(default=0, ge=0, le=6)
    amount_cents: int = Field(default=0, ge=0)
    api_cost_cents: int = Field(default=0, ge=0)
    model_cost_cents: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    model_name: str | None = None
    category: str | None = None
    counterparty: str | None = None
    domain: str | None = None
    experiment_id: str | None = None
    cycle_id: str | None = None
    project_id: str | None = None
    external: bool = False
    simulation: bool = False
    approval_required: bool = False
    approval_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class PolicyResult(BaseModel):
    decision: Decision
    reason: str
    policy_decision_id: str | None = None
    approval_id: str | None = None


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["APPROVE", "DENY", "EDIT_AND_APPROVE"]
    actor: str = "owner"
    edits: dict[str, Any] = Field(default_factory=dict)


class OwnerSettingRequest(BaseModel):
    autonomy_level: int | None = Field(default=None, ge=0, le=6)
    real_money_enabled: bool | None = None
    objective: str | None = None
    strategy: str | None = None
    global_spend_limit_cents: int | None = Field(default=None, ge=0)
    per_transaction_limit_cents: int | None = Field(default=None, ge=0)
    daily_spend_limit_cents: int | None = Field(default=None, ge=0)
    approval_threshold_cents: int | None = Field(default=None, ge=0)
    model_cost_limit_cents: int | None = Field(default=None, ge=0)
    api_cost_limit_cents: int | None = Field(default=None, ge=0)
    category_allowlist: list[str] | None = None
    category_denylist: list[str] | None = None
    category_limits_cents: dict[str, int] | None = None
    counterparty_allowlist: list[str] | None = None
    counterparty_denylist: list[str] | None = None
    domain_allowlist: list[str] | None = None
    domain_denylist: list[str] | None = None
    rate_limits: dict[str, Any] | None = None


class FreezeRequest(BaseModel):
    reason: str = "Owner requested emergency freeze"


class OpportunityCreate(BaseModel):
    title: str
    category: str
    hypothesis: str
    stream_type: Literal["agent_services", "digital_assets", "public_tasks", "affiliate_content", "bug_bounty"] = "agent_services"
    mechanism: str = "service"
    source: str = "public-demand-import"
    demand_evidence_id: str | None = None
    evidence: str = ""
    expected_revenue_cents: int = Field(default=0, ge=0)
    max_downside_cents: int = Field(default=0, ge=0)
    required_capital_cents: int = Field(default=0, ge=0)
    confidence_bps: int = Field(default=0, ge=0, le=10_000)


class DemandEvidenceCreate(BaseModel):
    source_url: AnyHttpUrl
    source_platform: str
    buyer_identity: str
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status_checked_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    quoted_need: str
    stated_budget_cents: int | None = Field(default=None, ge=0)
    stated_currency: str | None = Field(default=None, min_length=3, max_length=3)
    content_hash: str = Field(min_length=64, max_length=128)
    verified_snapshot: bool = False

    @field_validator("content_hash")
    @classmethod
    def valid_hash(cls, value: str) -> str:
        if not all(character in "0123456789abcdefABCDEF" for character in value):
            raise ValueError("content_hash must be hexadecimal")
        return value.lower()

    @field_validator("stated_currency")
    @classmethod
    def normalize_stated_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class DemandEvidenceVerificationRequest(BaseModel):
    receipt_id: str = Field(min_length=1)
    source_url: AnyHttpUrl
    observed_at: datetime
    source_http_status: int = Field(ge=200, le=599)
    content_hash: str = Field(min_length=64, max_length=128)
    verification_method: str = Field(min_length=1)

    @field_validator("content_hash")
    @classmethod
    def valid_receipt_hash(cls, value: str) -> str:
        if not all(character in "0123456789abcdefABCDEF" for character in value):
            raise ValueError("content_hash must be hexadecimal")
        return value.lower()


class DeliverableProofCreate(BaseModel):
    artifact_manifest: dict[str, Any] = Field(default_factory=dict)


class NegotiationMessage(BaseModel):
    sender: Literal["owner", "counterparty"]
    remote_id: str = Field(min_length=1)
    sent_at: datetime
    content: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=128)

    @field_validator("content_hash")
    @classmethod
    def valid_message_hash(cls, value: str) -> str:
        if not all(character in "0123456789abcdefABCDEF" for character in value):
            raise ValueError("message content_hash must be hexadecimal")
        return value.lower()


class NegotiationCreate(BaseModel):
    opportunity_id: str
    counterparty_identity: str
    requested_product: str
    mode: Literal["imported", "demo-only"] = "imported"
    messages: list[NegotiationMessage] = Field(default_factory=list)
    scope: str = ""
    acceptance_criteria: str = ""
    agreed_price_cents: int | None = Field(default=None, ge=0)
    agreed_currency: str | None = Field(default=None, min_length=3, max_length=3)
    expires_at: datetime | None = None
    counterparty_agreed: bool = False

    @field_validator("agreed_currency")
    @classmethod
    def normalize_optional_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class NegotiationDraftRequest(BaseModel):
    message: NegotiationMessage


class NegotiationReceipt(BaseModel):
    receipt_id: str = Field(min_length=1)
    remote_id: str = Field(min_length=1)
    source_url: AnyHttpUrl
    captured_at: datetime
    source_http_status: int = Field(ge=200, le=599)
    content_hash: str = Field(min_length=64, max_length=128)
    counterparty_identity: str = Field(min_length=1)
    verification_method: Literal["trusted_adapter_hmac_v1"]
    signature: str = Field(min_length=64, max_length=64)

    @field_validator("content_hash")
    @classmethod
    def valid_content_hash(cls, value: str) -> str:
        if not all(character in "0123456789abcdefABCDEF" for character in value):
            raise ValueError("receipt content_hash must be hexadecimal")
        return value.lower()

    @field_validator("signature")
    @classmethod
    def valid_signature(cls, value: str) -> str:
        if not all(character in "0123456789abcdefABCDEF" for character in value):
            raise ValueError("receipt signature must be hexadecimal")
        return value.lower()


class ExternalStateReceipt(BaseModel):
    receipt_id: str = Field(min_length=1)
    source_url: AnyHttpUrl
    remote_id: str = Field(min_length=1)
    observed_at: datetime
    content_hash: str = Field(min_length=64, max_length=128)
    subject_id: str = Field(min_length=1)
    event_type: Literal[
        "BUG_BOUNTY_SUBMITTED",
        "BUG_BOUNTY_TRIAGED",
        "BUG_BOUNTY_ACCEPTED",
        "BUG_BOUNTY_REJECTED",
        "BUG_BOUNTY_DUPLICATE",
    ]
    verification_method: Literal["trusted_adapter_hmac_v1"]
    signature: str = Field(min_length=64, max_length=64)

    @field_validator("content_hash", "signature")
    @classmethod
    def valid_hex(cls, value: str) -> str:
        if not all(character in "0123456789abcdefABCDEF" for character in value):
            raise ValueError("trusted receipt hashes must be hexadecimal")
        return value.lower()


class NegotiationAgreementRequest(BaseModel):
    counterparty_agreed: bool
    scope: str
    acceptance_criteria: str
    agreed_price_cents: int = Field(ge=0)
    agreed_currency: str = Field(min_length=3, max_length=3)
    expires_at: datetime
    message: NegotiationMessage
    external_receipt: NegotiationReceipt

    @field_validator("agreed_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


class OwnerGoNoGoRequest(BaseModel):
    go: bool


class OwnerDeliveryDecisionRequest(BaseModel):
    decision: Literal["PAPER", "REAL"]


class ProgramScopeCreate(BaseModel):
    program_url: AnyHttpUrl
    assets_in_scope: list[str] = Field(default_factory=list, min_length=1)
    assets_out_of_scope: list[str] = Field(default_factory=list)
    safe_harbor: str = ""
    rules: list[str] = Field(default_factory=list)
    rate_limits: dict[str, Any] = Field(default_factory=dict)
    test_plan: str = ""
    test_account_requirements: str = ""
    required_headers: list[str] = Field(default_factory=list)
    payout_tiers: list[dict[str, Any]] = Field(default_factory=list)
    disclosure_policy: str = ""
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    content_hash: str = Field(min_length=64, max_length=128)

    @field_validator("content_hash")
    @classmethod
    def valid_scope_hash(cls, value: str) -> str:
        if not all(character in "0123456789abcdefABCDEF" for character in value):
            raise ValueError("content_hash must be hexadecimal")
        return value.lower()


class ProgramScopeTransitionRequest(BaseModel):
    target: Literal[
        "SCOPE_VERIFIED",
        "OWNER_TARGET_AUTHORIZATION",
        "PASSIVE_TRIAGE",
        "TEST_PLAN_REVIEW",
        "ACTIVE_TESTING",
        "FINDING_VALIDATED",
        "DUPLICATE_CHECK",
        "REPORT_DRAFT",
        "OWNER_SUBMISSION_APPROVAL",
        "SUBMITTED",
        "TRIAGED",
        "ACCEPTED",
        "REJECTED",
        "DUPLICATE",
        "PAID",
        "DISCLOSURE_APPROVAL",
        "DECLINED",
        "EXPIRED",
    ]
    assets: list[str] = Field(default_factory=list)
    owner_approved: bool = False
    payment_evidence: dict[str, Any] = Field(default_factory=dict)
    external_receipt: ExternalStateReceipt | None = None


class BugBountyFindingCreate(BaseModel):
    title: str
    description: str
    asset: str
    severity: str = "informational"
    evidence: dict[str, Any] = Field(default_factory=dict)
    validation_notes: str = ""


class BugBountyFindingTransitionRequest(BaseModel):
    target: Literal[
        "DUPLICATE_CHECK",
        "REPORT_DRAFT",
        "OWNER_SUBMISSION_APPROVAL",
        "SUBMITTED",
        "TRIAGED",
        "ACCEPTED",
        "REJECTED",
        "DUPLICATE",
        "PAID",
        "DISCLOSURE_APPROVAL",
    ]
    owner_approved: bool = False
    public_disclosure_approved: bool = False
    duplicate_reference: str | None = None
    payment_evidence: dict[str, Any] = Field(default_factory=dict)
    external_receipt: ExternalStateReceipt | None = None


class ExperimentCreate(BaseModel):
    title: str
    hypothesis: str
    proposed_actions: list[str] = Field(default_factory=list)
    opportunity_id: str | None = None
    negotiation_id: str | None = None
    stream_type: Literal["agent_services", "digital_assets", "public_tasks", "affiliate_content", "bug_bounty"] = "agent_services"
    expected_revenue_cents: int = Field(default=0, ge=0)
    max_loss_cents: int = Field(default=0, ge=0)
    max_spend_cents: int = Field(default=0, ge=0)
    duration_days: int = Field(default=7, ge=1, le=365)
    success_criteria: str = ""
    kill_criteria: str = ""


class ExperimentTransitionRequest(BaseModel):
    target: Literal["REVIEW", "APPROVED", "RUNNING", "PAUSED", "SUCCESS", "FAILURE", "TERMINATED"]


class ProjectCreate(BaseModel):
    name: str
    concept: str
    negotiation_id: str | None = None
    customer_problem: str = ""
    audience: str = ""
    solution: str = ""
    price_cents: int = Field(default=0, ge=0)


class ModelBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CycleResponse(ModelBase):
    id: str
    status: str
    rationale: str
    tool_calls: int
    turns: int
    model_cost_cents: int
