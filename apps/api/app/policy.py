from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .approvals import create_approval, latest_approval_event
from .audit import record_audit
from .models import ApprovalRequest, Cycle, Experiment, ModelUsage, PolicyDecision, Project, SystemState
from .schemas import ActionRequest, PolicyResult
from .security import security_event


@dataclass(frozen=True)
class PolicyRule:
    action_type: str
    autonomy_required: int
    external: bool = False
    financial: bool = False


RULES = {
    "research.search": PolicyRule("research.search", 0),
    "research.fetch": PolicyRule("research.fetch", 0),
    "simulation.research": PolicyRule("simulation.research", 0),
    "simulation.expense": PolicyRule("simulation.expense", 3, financial=True),
    "simulation.revenue": PolicyRule("simulation.revenue", 4),
    "experiment.create": PolicyRule("experiment.create", 1),
    "experiment.run": PolicyRule("experiment.run", 1),
    "experiment.scale": PolicyRule("experiment.scale", 2, financial=True),
    "experiment.terminate": PolicyRule("experiment.terminate", 0),
    "memory.write": PolicyRule("memory.write", 0),
    "analytics.record": PolicyRule("analytics.record", 0),
    "bugbounty.passive_triage": PolicyRule("bugbounty.passive_triage", 0),
    "bugbounty.test_plan": PolicyRule("bugbounty.test_plan", 1, external=True),
    "bugbounty.active_testing": PolicyRule("bugbounty.active_testing", 4, external=True),
    "bugbounty.submit": PolicyRule("bugbounty.submit", 4, external=True),
    "publish": PolicyRule("publish", 2, external=True),
    "communicate": PolicyRule("communicate", 2, external=True),
    "spend": PolicyRule("spend", 3, external=True, financial=True),
    "transfer": PolicyRule("transfer", 3, external=True, financial=True),
    "crypto.transfer": PolicyRule("crypto.transfer", 4, external=True, financial=True),
    "wallet.execute": PolicyRule("wallet.execute", 4, external=True, financial=True),
}

PROHIBITED = (
    "wash trading",
    "fake bid",
    "fake purchase",
    "fake buyer",
    "fake counterparty",
    "self-dealing",
    "self-purchase",
    "self purchase",
    "synthetic volume",
    "artificial trading volume",
    "artificial volume",
    "fake scarcity",
    "market manipulation",
    "fraud",
    "fraudulent",
    "impersonat",
    "deceptive financial",
    "false financial",
    "misrepresent financial",
    "fake review",
    "fake testimonial",
    "phishing",
    "out-of-scope",
    "out of scope",
    "destructive",
    "pii",
    "exfiltrat",
    "persistence",
    "social engineering",
    "denial of service",
    "dos",
    "load test",
    "credential theft",
    "password theft",
    "without authorization",
    "threat",
    "money laundering",
    "sanctions evasion",
    "malware",
    "unauthorized access",
    "illegal goods",
    "unlicensed asset",
    "prohibited content",
    "spam",
    "bypass platform",
    "disable audit",
    "disable policy",
    "increase own permission",
    "change own policy",
    "extract api key",
    "reveal api key",
    "private key",
)


def _text(request: ActionRequest) -> str:
    return " ".join(
        [
            request.action_type,
            request.category or "",
            request.counterparty or "",
            request.domain or "",
            json.dumps(request.payload, sort_keys=True, default=str),
        ]
    ).lower()


def _state(db: Session) -> SystemState:
    # Serialize policy-budget and rate-window decisions on PostgreSQL. SQLite's
    # single-writer behavior supplies the local equivalent.
    state = db.scalars(select(SystemState).where(SystemState.id == 1).with_for_update()).first()
    if state is None:
        state = SystemState(id=1)
        db.add(state)
        db.flush()
    return state


def _normalise(value: object) -> str:
    return value.strip().casefold() if isinstance(value, str) else ""


def _normalise_domain(value: str | None) -> str:
    raw = value.strip().casefold() if isinstance(value, str) else ""
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"//{raw}")
    return (parsed.hostname or "").rstrip(".")


def _matches_domain(value: str, candidate: str) -> bool:
    return value == candidate or value.endswith(f".{candidate}")


def _category_spend_total(db: Session, category: str) -> int:
    """Return persisted allowed financial spend for one normalized category."""

    total = 0
    # ponytail: bounded O(n) history scan; add a persisted category-spend ledger if policy volume requires it.
    for decision in db.scalars(
        select(PolicyDecision).where(PolicyDecision.decision == "ALLOW")
    ):
        rule = RULES.get(decision.action_type)
        if rule is None or not rule.financial or decision.amount_cents <= 0:
            continue
        payload = decision.request_payload
        if isinstance(payload, dict) and _normalise(payload.get("category")) == category:
            total += decision.amount_cents
    return total


def _restriction_reason(
    state: SystemState, request: ActionRequest, db: Session | None = None
) -> str | None:
    category = _normalise(request.category)
    raw_category_allowlist = state.category_allowlist or []
    raw_category_denylist = state.category_denylist or []
    if not isinstance(raw_category_allowlist, list) or not all(isinstance(item, str) for item in raw_category_allowlist):
        return "category allowlist configuration is invalid"
    if not isinstance(raw_category_denylist, list) or not all(isinstance(item, str) for item in raw_category_denylist):
        return "category denylist configuration is invalid"
    category_allowlist = {_normalise(item) for item in raw_category_allowlist}
    category_denylist = {_normalise(item) for item in raw_category_denylist}
    raw_category_limits = state.category_limits_cents or {}
    if not isinstance(raw_category_limits, dict):
        return "category limit configuration is invalid"
    category_limits: dict[str, int] = {}
    for key, value in raw_category_limits.items():
        if not isinstance(key, str) or not _normalise(key):
            return "category limit configuration is invalid"
        try:
            parsed_value = int(value)
        except (TypeError, ValueError):
            return "category limit configuration is invalid"
        if parsed_value < 0:
            return "category limit configuration is invalid"
        category_limits[_normalise(key)] = parsed_value
    if category_allowlist or category_denylist or category_limits:
        if not category:
            return "category is required by the configured policy"
        if category in category_denylist:
            return "category is denied by policy"
        if category_allowlist and category not in category_allowlist:
            return "category is not on the policy allowlist"
        if category_limits and category not in category_limits:
            return "category has no configured spending limit"
        if category in category_limits:
            limit = category_limits[category]
            if request.amount_cents > limit:
                return "category spending limit exceeded"
            rule = RULES.get(request.action_type)
            if (
                db is not None
                and rule is not None
                and rule.financial
                and _category_spend_total(db, category) + request.amount_cents > limit
            ):
                return "category spending limit exceeded"

    counterparty = _normalise(request.counterparty)
    raw_counterparty_allowlist = state.counterparty_allowlist or []
    raw_counterparty_denylist = state.counterparty_denylist or []
    if not isinstance(raw_counterparty_allowlist, list) or not all(isinstance(item, str) for item in raw_counterparty_allowlist):
        return "counterparty allowlist configuration is invalid"
    if not isinstance(raw_counterparty_denylist, list) or not all(isinstance(item, str) for item in raw_counterparty_denylist):
        return "counterparty denylist configuration is invalid"
    counterparty_allowlist = {_normalise(item) for item in raw_counterparty_allowlist}
    counterparty_denylist = {_normalise(item) for item in raw_counterparty_denylist}
    if counterparty_allowlist or counterparty_denylist:
        if not counterparty:
            return "counterparty is required by the configured policy"
        if counterparty in counterparty_denylist:
            return "counterparty is denied by policy"
        if counterparty_allowlist and counterparty not in counterparty_allowlist:
            return "counterparty is not on the policy allowlist"

    domain = _normalise_domain(request.domain)
    raw_domain_allowlist = state.domain_allowlist or []
    raw_domain_denylist = state.domain_denylist or []
    if not isinstance(raw_domain_allowlist, list) or not all(isinstance(item, str) for item in raw_domain_allowlist):
        return "domain allowlist configuration is invalid"
    if not isinstance(raw_domain_denylist, list) or not all(isinstance(item, str) for item in raw_domain_denylist):
        return "domain denylist configuration is invalid"
    domain_allowlist = {_normalise_domain(item) for item in raw_domain_allowlist}
    domain_denylist = {_normalise_domain(item) for item in raw_domain_denylist}
    if domain_allowlist or domain_denylist:
        if not domain:
            return "domain is required by the configured policy"
        if any(_matches_domain(domain, item) for item in domain_denylist if item):
            return "domain is denied by policy"
        if domain_allowlist and not any(_matches_domain(domain, item) for item in domain_allowlist if item):
            return "domain is not on the policy allowlist"
    return None


def _rate_limit_config(state: SystemState, key: str) -> tuple[int, int] | None:
    configured = state.rate_limits or {}
    if not isinstance(configured, dict):
        return None
    raw = configured.get(key, configured.get("*"))
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw, 60
    if not isinstance(raw, dict):
        return None
    try:
        maximum = int(raw.get("max_requests", raw.get("limit", raw.get("requests", 0))))
        window = int(raw.get("window_seconds", raw.get("window", 60)))
    except (TypeError, ValueError):
        return None
    return maximum, window


def _rate_limit_reason(db: Session, state: SystemState, request: ActionRequest) -> str | None:
    key = request.action_type
    config = _rate_limit_config(state, key)
    if config is None:
        return "rate limit is not configured for this action"
    maximum, window_seconds = config
    if maximum <= 0 or window_seconds <= 0:
        return "rate limit configuration is invalid"
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    used = db.scalar(
        select(func.count(PolicyDecision.id)).where(
            PolicyDecision.rate_limit_key == key,
            PolicyDecision.decision == "ALLOW",
            PolicyDecision.created_at >= cutoff,
        )
    ) or 0
    if used >= maximum:
        return "rate limit exceeded"
    return None


def _record_usage(db: Session, state: SystemState, request: ActionRequest) -> None:
    if not (request.model_cost_cents or request.api_cost_cents or request.input_tokens or request.output_tokens):
        return
    state.model_cost_cents += request.model_cost_cents
    state.api_cost_cents += request.api_cost_cents
    db.add(
        ModelUsage(
            agent=request.requesting_agent,
            model_name=request.model_name,
            cycle_id=request.cycle_id,
            experiment_id=request.experiment_id,
            project_id=request.project_id,
            input_tokens=request.input_tokens,
            output_tokens=request.output_tokens,
            model_cost_cents=request.model_cost_cents,
            api_cost_cents=request.api_cost_cents,
            estimated_cost_cents=request.model_cost_cents + request.api_cost_cents,
        )
    )


def _attribution_reason(db: Session, request: ActionRequest) -> str | None:
    if request.cycle_id and db.get(Cycle, request.cycle_id) is None:
        return "model usage cycle attribution target was not found"
    if request.experiment_id and db.get(Experiment, request.experiment_id) is None:
        return "model usage experiment attribution target was not found"
    if request.project_id and db.get(Project, request.project_id) is None:
        return "model usage project attribution target was not found"
    return None


class PolicyEngine:
    """Deterministic, fail-closed gate for every action request."""

    def evaluate(self, db: Session, request: ActionRequest) -> PolicyResult:
        state = _state(db)
        rule = RULES.get(request.action_type)
        text = _text(request)
        reason = ""
        decision = "DENY"
        approval_id: str | None = None
        rate_limit_key = request.action_type
        supplied_approval = (
            db.scalars(
                select(ApprovalRequest)
                .where(ApprovalRequest.id == request.approval_id)
                .with_for_update()
            ).first()
            if request.approval_id
            else None
        )
        approval_event = latest_approval_event(db, request.approval_id) if request.approval_id else None
        expected_payload = dict(supplied_approval.payload) if supplied_approval else {}
        if approval_event and approval_event.event == "EDIT_AND_APPROVE":
            expected_payload.update(approval_event.payload.get("edits", {}))
        approval_matches = bool(
            supplied_approval
            and approval_event
            and approval_event.event in {"APPROVE", "EDIT_AND_APPROVE"}
            and supplied_approval.action_type == request.action_type
            and supplied_approval.requested_by == request.requesting_agent
            and expected_payload == request.model_dump(mode="json", exclude={"approval_id"})
        )

        if request.amount_cents < 0:
            reason = "negative amounts are invalid"
        elif any(term in text for term in PROHIBITED):
            reason = "prohibited or policy-circumventing behavior"
            security_event(
                db,
                "CRITICAL" if any(term in text for term in ("policy", "audit", "permission", "private key")) else "HIGH",
                "prohibited_action_attempt",
                {"action_type": request.action_type, "agent": request.requesting_agent},
                freeze=True,
            )
        elif state.frozen and (request.external or request.amount_cents > 0 or request.action_type not in {"research.search", "simulation.research"}):
            reason = "autonomy is frozen"
        elif request.approval_id and not approval_matches:
            reason = "approval is missing, mismatched, already consumed, or denied"
        elif rule is None:
            reason = "unknown action type; policy is fail-closed"
        elif (attribution_reason := _attribution_reason(db, request)):
            reason = attribution_reason
        elif (restriction_reason := _restriction_reason(state, request, db)):
            reason = restriction_reason
        elif request.model_cost_cents and state.model_cost_cents + request.model_cost_cents > state.model_cost_limit_cents:
            reason = "model cost budget exceeded"
        elif request.api_cost_cents and state.api_cost_cents + request.api_cost_cents > state.api_cost_limit_cents:
            reason = "API cost budget exceeded"
        elif request.action_type in {"simulation.expense", "simulation.revenue"} and request.amount_cents <= 0:
            reason = "simulated financial amounts must be positive"
        elif request.action_type.startswith("simulation.") and not request.simulation:
            reason = "simulation actions require simulation=true"
        elif request.simulation and not state.real_money_enabled and request.external:
            reason = "simulation requests cannot call external systems"
        elif state.real_money_enabled and not request.simulation and not request.external:
            reason = "real-money execution requires an explicit external adapter"
        elif request.amount_cents > state.per_transaction_limit_cents and rule.financial:
            reason = "per-transaction spending limit exceeded"
        elif rule.financial and request.amount_cents and state.global_spend_cents + request.amount_cents > state.global_spend_limit_cents:
            reason = "global spending limit exceeded"
        elif rule.financial and request.amount_cents and state.daily_spend_cents + request.amount_cents > state.daily_spend_limit_cents:
            reason = "daily spending limit exceeded"
        elif request.experiment_id and request.amount_cents and rule and rule.financial and (
            (experiment := db.get(Experiment, request.experiment_id)) is not None
            and experiment.expenses_cents + request.amount_cents > experiment.max_spend_cents
        ):
            reason = "experiment spending limit exceeded"
        elif (rate_limit_reason := _rate_limit_reason(db, state, request)):
            reason = rate_limit_reason
        elif state.autonomy_level < max(rule.autonomy_required, request.autonomy_required) and not approval_matches:
            reason = "action exceeds configured autonomy level"
            decision = "REQUIRE_APPROVAL"
        elif (
            request.approval_required
            or rule.external
            or (rule.financial and request.amount_cents > state.approval_threshold_cents)
        ) and not approval_matches:
            reason = "owner approval required for material or external action"
            decision = "REQUIRE_APPROVAL"
        else:
            reason = "deterministic policy checks passed"
            decision = "ALLOW"

        policy = PolicyDecision(
            action_type=request.action_type,
            requesting_agent=request.requesting_agent,
            decision=decision,
            reason=reason,
            amount_cents=request.amount_cents,
            rate_limit_key=rate_limit_key,
            request_payload=request.model_dump(mode="json"),
        )
        db.add(policy)
        db.flush()
        if decision == "ALLOW":
            _record_usage(db, state, request)
        record_audit(
            db,
            "policy_decision",
            request.requesting_agent,
            reason,
            {"policy_decision_id": policy.id, "action_type": request.action_type, "decision": decision},
        )
        if decision == "REQUIRE_APPROVAL":
            approval = create_approval(
                db,
                "spending" if rule and rule.financial else "external_action",
                request.requesting_agent,
                request.action_type,
                request.model_dump(mode="json", exclude={"approval_id"}),
                reason,
            )
            approval_id = approval.id
        elif approval_matches:
            approval_id = request.approval_id
        db.flush()
        return PolicyResult(decision=decision, reason=reason, policy_decision_id=policy.id, approval_id=approval_id)

    def deny_permission(self, db: Session, request: ActionRequest, reason: str) -> PolicyResult:
        """Persist a broker permission denial after the action rule passed."""

        policy = PolicyDecision(
            action_type=request.action_type,
            requesting_agent=request.requesting_agent,
            decision="DENY",
            reason=reason,
            amount_cents=request.amount_cents,
            rate_limit_key=request.action_type,
            request_payload=request.model_dump(mode="json"),
        )
        db.add(policy)
        db.flush()
        record_audit(
            db,
            "policy_permission_denied",
            request.requesting_agent,
            reason,
            {"policy_decision_id": policy.id, "action_type": request.action_type},
        )
        return PolicyResult(decision="DENY", reason=reason, policy_decision_id=policy.id)


policy_engine = PolicyEngine()
