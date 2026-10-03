"""Passive bug-bounty scope and finding controls.

This module deliberately contains no HTTP client, scanner, credential store, or
reporting adapter.  It records imported program rules and keeps every active or
external step behind explicit owner gates.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from .audit import record_audit
from .config import settings
from .models import BugBountyFinding, ProgramScope
from .receipts import verify_trusted_receipt
from .schemas import BugBountyFindingCreate, BugBountyFindingTransitionRequest, ProgramScopeCreate, ProgramScopeTransitionRequest
from .security import security_event


PROGRAM_STATES = (
    "PROGRAM_DISCOVERED",
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
)

PROGRAM_TRANSITIONS: dict[str, set[str]] = {
    "PROGRAM_DISCOVERED": {"SCOPE_VERIFIED", "DECLINED", "EXPIRED"},
    "SCOPE_VERIFIED": {"OWNER_TARGET_AUTHORIZATION", "DECLINED", "EXPIRED"},
    "OWNER_TARGET_AUTHORIZATION": {"PASSIVE_TRIAGE", "DECLINED", "EXPIRED"},
    "PASSIVE_TRIAGE": {"TEST_PLAN_REVIEW", "DECLINED", "EXPIRED"},
    "TEST_PLAN_REVIEW": {"ACTIVE_TESTING", "DECLINED", "EXPIRED"},
    "ACTIVE_TESTING": {"FINDING_VALIDATED", "DECLINED", "EXPIRED"},
    "FINDING_VALIDATED": {"DUPLICATE_CHECK", "DECLINED", "EXPIRED"},
    "DUPLICATE_CHECK": {"REPORT_DRAFT", "DUPLICATE", "DECLINED", "EXPIRED"},
    "REPORT_DRAFT": {"OWNER_SUBMISSION_APPROVAL", "DECLINED", "EXPIRED"},
    "OWNER_SUBMISSION_APPROVAL": {"SUBMITTED", "DECLINED", "EXPIRED"},
    "SUBMITTED": {"TRIAGED", "DECLINED", "EXPIRED"},
    "TRIAGED": {"ACCEPTED", "REJECTED", "DUPLICATE", "DECLINED", "EXPIRED"},
    "ACCEPTED": {"PAID"},
    "PAID": {"DISCLOSURE_APPROVAL"},
    "REJECTED": set(),
    "DUPLICATE": set(),
    "DISCLOSURE_APPROVAL": set(),
    "DECLINED": set(),
    "EXPIRED": set(),
}

# These are deliberately broad.  A false positive can be reviewed by the owner;
# a false negative could cause unauthorized testing or disclosure.
HARD_DENY_TERMS = (
    "out-of-scope",
    "out of scope",
    "destructive",
    "pii",
    "personal data",
    "exfiltrat",
    "persistence",
    "persistent access",
    "phishing",
    "social engineering",
    "denial of service",
    "dos",
    "load test",
    "load testing",
    "credential theft",
    "password theft",
    "steal credentials",
    "threat",
    "unauthorized",
    "without authorization",
)

EXTERNAL_EVENTS = {
    "SUBMITTED": "BUG_BOUNTY_SUBMITTED",
    "TRIAGED": "BUG_BOUNTY_TRIAGED",
    "ACCEPTED": "BUG_BOUNTY_ACCEPTED",
    "REJECTED": "BUG_BOUNTY_REJECTED",
    "DUPLICATE": "BUG_BOUNTY_DUPLICATE",
}

EXTERNAL_ACTION_TARGETS = {
    "ACTIVE_TESTING",
    "SUBMITTED",
    "TRIAGED",
    "ACCEPTED",
    "REJECTED",
    "DUPLICATE",
    "PAID",
    "DISCLOSURE_APPROVAL",
}


def _scope_text(action: str, asset: str | None, detail: Any = None) -> str:
    return " ".join((action, asset or "", json.dumps(detail or {}, sort_keys=True, default=str))).lower()


def _deny(db: Session, reason: str, detail: dict[str, Any]) -> None:
    security_event(db, "HIGH", "bug_bounty_action_denied", {"reason": reason, **detail}, freeze=True)
    raise ValueError(reason)


def _exact_asset_allowed(program: ProgramScope, asset: str) -> bool:
    return bool(
        asset
        and asset in (program.assets_in_scope or [])
        and asset not in (program.assets_out_of_scope or [])
        and asset in (program.authorized_assets or [])
    )


def _deny_disabled_external_action(db: Session, subject_id: str, target: str) -> None:
    if not settings.bug_bounty_external_actions_enabled and target in EXTERNAL_ACTION_TARGETS:
        _deny(
            db,
            "external bug-bounty actions are disabled by configuration",
            {"subject_id": subject_id, "target": target},
        )


def validate_bounty_action(
    db: Session,
    program: ProgramScope,
    action: str,
    *,
    asset: str | None = None,
    detail: Any = None,
) -> None:
    """Fail closed for risky or unapproved bug-bounty actions."""

    text = _scope_text(action, asset, detail)
    if any(term in text for term in HARD_DENY_TERMS):
        _deny(db, "bug-bounty hard-deny rule matched", {"program_id": program.id, "action": action, "asset": asset})
    if asset and not _in_scope_exact(program, asset):
        _deny(db, "asset is outside the imported exact scope", {"program_id": program.id, "asset": asset})
    if action == "active_testing":
        if program.status != "ACTIVE_TESTING" or not program.owner_target_authorized or not program.test_plan.strip():
            _deny(db, "active testing requires owner target authorization", {"program_id": program.id})
        if not asset or not _exact_asset_allowed(program, asset):
            _deny(db, "asset is not an exact owner-authorized in-scope target", {"program_id": program.id, "asset": asset})
    elif action in {"report_submit", "public_disclosure"}:
        _deny(db, "external submission or disclosure requires its explicit owner gate", {"program_id": program.id, "action": action})


def create_program_scope(db: Session, data: ProgramScopeCreate) -> ProgramScope:
    if set(data.assets_in_scope) & set(data.assets_out_of_scope):
        raise ValueError("an asset cannot be both in and out of scope")
    program = ProgramScope(
        program_url=str(data.program_url),
        assets_in_scope=data.assets_in_scope,
        assets_out_of_scope=data.assets_out_of_scope,
        safe_harbor=data.safe_harbor,
        rules=data.rules,
        rate_limits=data.rate_limits,
        test_plan=data.test_plan,
        test_account_requirements=data.test_account_requirements,
        required_headers=data.required_headers,
        payout_tiers=data.payout_tiers,
        disclosure_policy=data.disclosure_policy,
        captured_at=data.captured_at,
        content_hash=data.content_hash,
        status="PROGRAM_DISCOVERED",
    )
    db.add(program)
    db.flush()
    record_audit(
        db,
        "bug_bounty_program_imported",
        "Bug Bounty Agent",
        "Program scope evidence imported; no target was contacted or tested.",
        {"program_id": program.id, "program_url": program.program_url},
    )
    return program


def transition_program(
    db: Session,
    program: ProgramScope,
    data: ProgramScopeTransitionRequest,
) -> ProgramScope:
    current = program.status
    target = data.target
    if target not in PROGRAM_STATES or target not in PROGRAM_TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid bug-bounty transition {current} -> {target}")
    _deny_disabled_external_action(db, program.id, target)
    external_receipt = _validate_external_state(program.id, target, data.external_receipt)

    if target == "SCOPE_VERIFIED":
        if not program.assets_in_scope or set(program.assets_in_scope) & set(program.assets_out_of_scope or []):
            raise ValueError("scope must be non-empty and non-overlapping")
        if not program.safe_harbor.strip() or not program.rules or not program.rate_limits:
            raise ValueError("safe harbor, rules, and rate limits are required before scope verification")
    elif target == "OWNER_TARGET_AUTHORIZATION":
        if not data.owner_approved:
            raise ValueError("owner approval is required to authorize targets")
        assets = data.assets or []
        if not assets or any(not _in_scope_exact(program, asset) for asset in assets):
            raise ValueError("owner authorization must enumerate exact in-scope assets")
        program.authorized_assets = assets
        program.owner_target_authorized = True
    elif target == "TEST_PLAN_REVIEW":
        if not data.owner_approved:
            raise ValueError("owner approval is required for the test-plan review gate")
        if not program.test_plan.strip():
            raise ValueError("a non-empty test plan is required before review")
    elif target == "ACTIVE_TESTING":
        if not data.owner_approved or not program.owner_target_authorized:
            raise ValueError("active testing requires explicit owner target authorization")
        if not program.test_plan.strip():
            raise ValueError("active testing requires an approved non-empty test plan")
        assets = data.assets or program.authorized_assets
        if not assets or any(not _exact_asset_allowed(program, asset) for asset in assets):
            raise ValueError("active testing requires exact authorized assets only")
        # This is a state declaration, not an executor.  The agent still has no
        # network/scanner/credential capability in this MVP.
        if any(
            term in _scope_text("active_testing", authorized_asset, data.model_dump())
            for authorized_asset in assets
            for term in HARD_DENY_TERMS
        ):
            _deny(db, "bug-bounty hard-deny rule matched", {"program_id": program.id, "action": "active_testing"})
    elif target == "OWNER_SUBMISSION_APPROVAL" and not data.owner_approved:
        raise ValueError("owner approval is required before report submission")
    elif target == "SUBMITTED" and not data.owner_approved:
        raise ValueError("owner submission approval is required")
    elif target == "PAID":
        if not data.owner_approved:
            raise ValueError("owner approval is required to record bounty payout evidence")
        if not data.payment_evidence:
            raise ValueError("payment evidence is required before bounty revenue can be recognized")
        if current != "ACCEPTED":
            raise ValueError("bounty payment requires accepted finding")
        _validate_paper_payment(data.payment_evidence)
        program.payment_evidence = data.payment_evidence
        program.paper_outcome = True
    elif target == "DISCLOSURE_APPROVAL" and not data.owner_approved:
        raise ValueError("owner disclosure approval is required")

    program.status = target
    record_audit(
        db,
        "bug_bounty_program_transition",
        "owner" if data.owner_approved else "Bug Bounty Agent",
        f"{current} -> {target}; no external adapter executed",
        {
            "program_id": program.id,
            "assets": data.assets,
            "paper_outcome": target == "PAID",
            "external_receipt": external_receipt,
        },
    )
    db.flush()
    return program


def _in_scope_exact(program: ProgramScope, asset: str) -> bool:
    return bool(asset and asset in (program.assets_in_scope or []) and asset not in (program.assets_out_of_scope or []))


def _validate_paper_payment(evidence: dict[str, Any]) -> None:
    if evidence.get("status") != "PAPER_ONLY":
        raise ValueError("bounty payment evidence must be explicitly PAPER_ONLY")
    if "amount_cents" in evidence:
        try:
            amount = int(evidence["amount_cents"])
        except (TypeError, ValueError) as exc:
            raise ValueError("paper payment amount must be a positive integer") from exc
        if amount <= 0:
            raise ValueError("paper payment amount must be positive")


def _validate_external_state(subject_id: str, target: str, receipt: Any) -> dict[str, Any] | None:
    expected = EXTERNAL_EVENTS.get(target)
    if expected is None:
        return None
    if receipt is None:
        raise ValueError(f"{target} requires a trusted external-state receipt")
    if receipt.subject_id != subject_id or receipt.event_type != expected:
        raise ValueError("external-state receipt does not match this record and transition")
    observed_at = receipt.observed_at
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    if observed_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("external-state receipt cannot be from the future")
    verify_trusted_receipt(receipt)
    return receipt.model_dump(mode="json")


def create_finding(db: Session, program: ProgramScope, data: BugBountyFindingCreate) -> BugBountyFinding:
    passive = program.status in {"PASSIVE_TRIAGE", "TEST_PLAN_REVIEW"}
    if program.status == "ACTIVE_TESTING":
        if not _exact_asset_allowed(program, data.asset):
            raise ValueError("finding asset is not an exact authorized target")
        program.status = "FINDING_VALIDATED"
    elif passive:
        if (
            not program.assets_in_scope
            or set(program.assets_in_scope) & set(program.assets_out_of_scope or [])
            or not program.safe_harbor.strip()
            or not program.rules
            or not program.rate_limits
        ):
            raise ValueError("passive findings require a verified scope")
        if not _exact_asset_allowed(program, data.asset):
            raise ValueError("finding asset is not an exact authorized target")
    elif program.status != "FINDING_VALIDATED":
        raise ValueError("findings require the validated-finding lifecycle state")
    if not _in_scope_exact(program, data.asset):
        raise ValueError("finding asset is out of scope")
    text = _scope_text(data.title, data.asset, {"description": data.description, "evidence": data.evidence})
    if any(term in text for term in HARD_DENY_TERMS):
        _deny(db, "finding contains prohibited testing or evidence language", {"program_id": program.id, "asset": data.asset})
    finding = BugBountyFinding(
        program_scope_id=program.id,
        title=data.title,
        description=data.description,
        asset=data.asset,
        severity=data.severity,
        evidence=data.evidence,
        validation_notes=data.validation_notes,
        status="DUPLICATE_CHECK" if passive else "FINDING_VALIDATED",
    )
    db.add(finding)
    db.flush()
    record_audit(
        db,
        "bug_bounty_finding_draft" if passive else "bug_bounty_finding_validated",
        "Bug Bounty Agent",
        "Passive draft record; no exploit, external access, or validation claim performed." if passive else "Passive finding record; no exploit or external access performed.",
        {"finding_id": finding.id, "program_id": program.id},
    )
    return finding


def transition_finding(
    db: Session,
    finding: BugBountyFinding,
    data: BugBountyFindingTransitionRequest,
) -> BugBountyFinding:
    current = finding.status
    target = data.target
    allowed = {
        "FINDING_VALIDATED": {"DUPLICATE_CHECK"},
        "DUPLICATE_CHECK": {"REPORT_DRAFT", "DUPLICATE"},
        "REPORT_DRAFT": {"OWNER_SUBMISSION_APPROVAL"},
        "OWNER_SUBMISSION_APPROVAL": {"SUBMITTED"},
        "SUBMITTED": {"TRIAGED"},
        "TRIAGED": {"ACCEPTED", "REJECTED", "DUPLICATE"},
        "ACCEPTED": {"PAID"},
        "PAID": {"DISCLOSURE_APPROVAL"},
    }
    if target not in allowed.get(current, set()):
        raise ValueError(f"invalid finding transition {current} -> {target}")
    _deny_disabled_external_action(db, finding.id, target)
    external_receipt = _validate_external_state(finding.id, target, data.external_receipt)
    if target == "OWNER_SUBMISSION_APPROVAL" and not data.owner_approved:
        raise ValueError("owner approval is required before report submission")
    if target == "SUBMITTED":
        if not data.owner_approved:
            raise ValueError("owner submission approval is required")
        finding.owner_submission_approved = True
    if target == "DUPLICATE":
        finding.duplicate_reference = data.duplicate_reference
    if external_receipt:
        existing_receipts = list((finding.evidence or {}).get("external_state_receipts", []))
        finding.evidence = {**(finding.evidence or {}), "external_state_receipts": [*existing_receipts, external_receipt]}
    if target == "PAID":
        if not data.owner_approved:
            raise ValueError("owner approval is required to record payout evidence")
        if not data.payment_evidence:
            raise ValueError("payment evidence is required before bounty revenue can be recognized")
        _validate_paper_payment(data.payment_evidence)
        finding.payment_evidence = data.payment_evidence
        finding.paper_outcome = True
        # No LedgerTransaction is created: paper bounty outcomes never become
        # treasury revenue and real payout adapters are not present.
    if target == "DISCLOSURE_APPROVAL":
        if not data.owner_approved or not data.public_disclosure_approved:
            raise ValueError("explicit owner disclosure approval is required")
        finding.public_disclosure_approved = True
    finding.status = target
    program = db.get(ProgramScope, finding.program_scope_id)
    if program is not None:
        program.status = target
        if target == "PAID":
            program.payment_evidence = finding.payment_evidence
            program.paper_outcome = True
    record_audit(
        db,
        "bug_bounty_finding_transition",
        "owner" if data.owner_approved else "Bug Bounty Agent",
        f"{current} -> {target}; external submission/disclosure remains disabled",
        {
            "finding_id": finding.id,
            "paper_outcome": finding.paper_outcome,
            "payment_evidence": bool(data.payment_evidence),
            "external_receipt": external_receipt,
        },
    )
    db.flush()
    return finding


class BugBountyAgent:
    """Passive-by-default specialist contract used by the control plane."""

    passive_by_default = True

    def validate_action(self, db: Session, program: ProgramScope, action: str, *, asset: str | None = None, detail: Any = None) -> None:
        validate_bounty_action(db, program, action, asset=asset, detail=detail)
