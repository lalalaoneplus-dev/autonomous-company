from datetime import datetime, timezone
import hashlib

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.bounty import create_finding, create_program_scope, transition_finding, transition_program
from app.config import Settings, settings
from app.db import configure_database
from app.main import app
from app.receipts import sign_trusted_receipt
from app.schemas import (
    BugBountyFindingCreate,
    BugBountyFindingTransitionRequest,
    ExternalStateReceipt,
    ProgramScopeCreate,
    ProgramScopeTransitionRequest,
)


def _program(db):
    return create_program_scope(
        db,
        ProgramScopeCreate(
            program_url="https://example.test/security",
            assets_in_scope=["api.example.test"],
            safe_harbor="No destructive testing.",
            rules=["Use the test account only."],
            rate_limits={"requests_per_minute": 10},
            test_plan="Passive observation only; exact host only.",
            content_hash="a" * 64,
        ),
    )


def _receipt(subject_id: str, event_type: str) -> ExternalStateReceipt:
    payload = {
        "receipt_id": f"receipt-{event_type.lower()}",
        "source_url": "https://bounty.example.test/report/1",
        "remote_id": f"remote-{event_type.lower()}",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": hashlib.sha256(f"{subject_id}:{event_type}".encode()).hexdigest(),
        "subject_id": subject_id,
        "event_type": event_type,
        "verification_method": "trusted_adapter_hmac_v1",
    }
    unsigned = ExternalStateReceipt.model_validate({**payload, "signature": "0" * 64})
    return ExternalStateReceipt.model_validate(
        {**payload, "signature": sign_trusted_receipt(unsigned, settings.trusted_receipt_hmac_secret)}
    )


def test_bug_bounty_external_actions_setting_is_default_off_and_boolean_validated(monkeypatch):
    monkeypatch.delenv("BUG_BOUNTY_EXTERNAL_ACTIONS_ENABLED", raising=False)
    assert Settings(_env_file=None).bug_bounty_external_actions_enabled is False

    monkeypatch.setenv("BUG_BOUNTY_EXTERNAL_ACTIONS_ENABLED", "true")
    assert Settings(_env_file=None).bug_bounty_external_actions_enabled is True

    monkeypatch.setenv("BUG_BOUNTY_EXTERNAL_ACTIONS_ENABLED", "not-a-boolean")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_default_off_preserves_preparation_but_denies_external_program_and_finding_states(db, monkeypatch):
    monkeypatch.setattr(settings, "bug_bounty_external_actions_enabled", False)
    program = _program(db)
    transition_program(db, program, ProgramScopeTransitionRequest(target="SCOPE_VERIFIED"))
    transition_program(
        db,
        program,
        ProgramScopeTransitionRequest(
            target="OWNER_TARGET_AUTHORIZATION", assets=["api.example.test"], owner_approved=True
        ),
    )
    transition_program(db, program, ProgramScopeTransitionRequest(target="PASSIVE_TRIAGE"))
    transition_program(db, program, ProgramScopeTransitionRequest(target="TEST_PLAN_REVIEW", owner_approved=True))

    with pytest.raises(ValueError, match="disabled by configuration"):
        transition_program(
            db,
            program,
            ProgramScopeTransitionRequest(
                target="ACTIVE_TESTING", assets=["api.example.test"], owner_approved=True
            ),
        )
    assert program.status == "TEST_PLAN_REVIEW"

    finding = create_finding(
        db,
        program,
        BugBountyFindingCreate(
            title="Passive observation",
            description="Local evidence only.",
            asset="api.example.test",
        ),
    )
    assert finding.status == "DUPLICATE_CHECK"
    transition_finding(db, finding, BugBountyFindingTransitionRequest(target="REPORT_DRAFT"))
    transition_finding(
        db,
        finding,
        BugBountyFindingTransitionRequest(target="OWNER_SUBMISSION_APPROVAL", owner_approved=True),
    )

    with pytest.raises(ValueError, match="disabled by configuration"):
        transition_finding(
            db,
            finding,
            BugBountyFindingTransitionRequest(target="SUBMITTED", owner_approved=True),
        )
    assert finding.status == "OWNER_SUBMISSION_APPROVAL"


def test_default_off_passive_finding_and_draft_are_reachable_through_owner_api(db, monkeypatch):
    monkeypatch.setattr(settings, "bug_bounty_external_actions_enabled", False)
    configure_database(db.get_bind().url.render_as_string(hide_password=False))
    headers = {"X-Owner-Token": "test-owner"}
    scope = {
        "program_url": "https://example.test/security",
        "assets_in_scope": ["api.example.test"],
        "safe_harbor": "No destructive testing.",
        "rules": ["Use the test account only."],
        "rate_limits": {"requests_per_minute": 10},
        "test_plan": "Passive observation only; exact host only.",
        "content_hash": "b" * 64,
    }
    with TestClient(app) as client:
        imported = client.post("/api/bug-bounty/programs", headers=headers, json=scope)
        assert imported.status_code == 200
        program_id = imported.json()["id"]
        for target, payload in (
            ("SCOPE_VERIFIED", {}),
            (
                "OWNER_TARGET_AUTHORIZATION",
                {"assets": ["api.example.test"], "owner_approved": True},
            ),
            ("PASSIVE_TRIAGE", {}),
        ):
            response = client.post(
                f"/api/bug-bounty/programs/{program_id}/transition",
                headers=headers,
                json={"target": target, **payload},
            )
            assert response.status_code == 200, response.text

        wrong_asset = client.post(
            f"/api/bug-bounty/programs/{program_id}/findings",
            headers=headers,
            json={"title": "Passive observation", "description": "Local evidence only.", "asset": "other.example.test"},
        )
        assert wrong_asset.status_code == 400
        created = client.post(
            f"/api/bug-bounty/programs/{program_id}/findings",
            headers=headers,
            json={"title": "Passive observation", "description": "Local evidence only.", "asset": "api.example.test"},
        )
        assert created.status_code == 200
        finding = created.json()
        assert finding["status"] == "DUPLICATE_CHECK"
        assert finding["owner_submission_approved"] is False

        drafted = client.post(
            f"/api/bug-bounty/findings/{finding['id']}/transition",
            headers=headers,
            json={"target": "REPORT_DRAFT"},
        )
        assert drafted.status_code == 200
        reviewed = client.post(
            f"/api/bug-bounty/findings/{finding['id']}/transition",
            headers=headers,
            json={"target": "OWNER_SUBMISSION_APPROVAL", "owner_approved": True},
        )
        assert reviewed.status_code == 200
        submitted = client.post(
            f"/api/bug-bounty/findings/{finding['id']}/transition",
            headers=headers,
            json={"target": "SUBMITTED", "owner_approved": True},
        )
        assert submitted.status_code == 400
        assert "disabled by configuration" in submitted.json()["detail"]


def test_enabled_path_keeps_exact_owner_receipt_payment_and_disclosure_gates(db, monkeypatch):
    monkeypatch.setattr(settings, "bug_bounty_external_actions_enabled", True)
    program = _program(db)
    transition_program(db, program, ProgramScopeTransitionRequest(target="SCOPE_VERIFIED"))
    with pytest.raises(ValueError, match="owner approval"):
        transition_program(
            db,
            program,
            ProgramScopeTransitionRequest(target="OWNER_TARGET_AUTHORIZATION"),
        )
    transition_program(
        db,
        program,
        ProgramScopeTransitionRequest(
            target="OWNER_TARGET_AUTHORIZATION", assets=["api.example.test"], owner_approved=True
        ),
    )
    transition_program(db, program, ProgramScopeTransitionRequest(target="PASSIVE_TRIAGE"))
    transition_program(db, program, ProgramScopeTransitionRequest(target="TEST_PLAN_REVIEW", owner_approved=True))
    with pytest.raises(ValueError, match="owner target authorization"):
        transition_program(db, program, ProgramScopeTransitionRequest(target="ACTIVE_TESTING"))
    transition_program(
        db,
        program,
        ProgramScopeTransitionRequest(
            target="ACTIVE_TESTING", assets=["api.example.test"], owner_approved=True
        ),
    )

    finding = create_finding(
        db,
        program,
        BugBountyFindingCreate(
            title="Passive observation",
            description="Local evidence only.",
            asset="api.example.test",
        ),
    )
    transition_finding(db, finding, BugBountyFindingTransitionRequest(target="DUPLICATE_CHECK"))
    transition_finding(db, finding, BugBountyFindingTransitionRequest(target="REPORT_DRAFT"))
    transition_finding(
        db,
        finding,
        BugBountyFindingTransitionRequest(target="OWNER_SUBMISSION_APPROVAL", owner_approved=True),
    )
    with pytest.raises(ValueError, match="trusted external-state receipt"):
        transition_finding(
            db,
            finding,
            BugBountyFindingTransitionRequest(target="SUBMITTED", owner_approved=True),
        )
    transition_finding(
        db,
        finding,
        BugBountyFindingTransitionRequest(
            target="SUBMITTED", owner_approved=True, external_receipt=_receipt(finding.id, "BUG_BOUNTY_SUBMITTED")
        ),
    )
    transition_finding(
        db,
        finding,
        BugBountyFindingTransitionRequest(
            target="TRIAGED", external_receipt=_receipt(finding.id, "BUG_BOUNTY_TRIAGED")
        ),
    )
    transition_finding(
        db,
        finding,
        BugBountyFindingTransitionRequest(
            target="ACCEPTED", external_receipt=_receipt(finding.id, "BUG_BOUNTY_ACCEPTED")
        ),
    )
    with pytest.raises(ValueError, match="payment evidence"):
        transition_finding(db, finding, BugBountyFindingTransitionRequest(target="PAID", owner_approved=True))
    with pytest.raises(ValueError, match="PAPER_ONLY"):
        transition_finding(
            db,
            finding,
            BugBountyFindingTransitionRequest(
                target="PAID", owner_approved=True, payment_evidence={"status": "PAID"}
            ),
        )
    transition_finding(
        db,
        finding,
        BugBountyFindingTransitionRequest(
            target="PAID", owner_approved=True, payment_evidence={"status": "PAPER_ONLY", "amount_cents": 1}
        ),
    )
    with pytest.raises(ValueError, match="disclosure approval"):
        transition_finding(db, finding, BugBountyFindingTransitionRequest(target="DISCLOSURE_APPROVAL", owner_approved=True))
    transition_finding(
        db,
        finding,
        BugBountyFindingTransitionRequest(
            target="DISCLOSURE_APPROVAL", owner_approved=True, public_disclosure_approved=True
        ),
    )
