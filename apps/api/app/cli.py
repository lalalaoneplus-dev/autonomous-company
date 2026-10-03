from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from .config import settings
from .db import configure_database, create_schema
from .main import app
from .models import DemandEvidence
from .schemas import DemandEvidenceCreate
from .audit import record_audit
from .seed import seed_demo


def _run_smoke() -> None:
    """Exercise the API against a disposable database, never operator state."""

    with TemporaryDirectory(prefix="autonomous-company-smoke-") as directory:
        configure_database(f"sqlite:///{Path(directory) / 'smoke.db'}")
        create_schema()
        previous_owner_token = settings.owner_token
        settings.owner_token = "smoke-owner"
        try:
            with TestClient(app) as client:
                health = client.get("/health")
                overview = client.get(
                    "/api/overview",
                    headers={"X-Owner-Token": settings.owner_token},
                )
                print(json.dumps({"health": health.json(), "overview": overview.json()}, default=str))
        finally:
            settings.owner_token = previous_owner_token


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["seed", "cycle", "smoke", "import-demand"], nargs="?", default="cycle")
    parser.add_argument("--file", help="JSON demand snapshot for import-demand")
    parser.add_argument("--verified", action="store_true", help="legacy hint only; imported evidence remains unverified until a receipt is recorded")
    args = parser.parse_args()
    if args.command == "smoke":
        _run_smoke()
        return
    configure_database()
    from .db import SessionLocal

    assert SessionLocal is not None
    with SessionLocal() as db:
        if args.command == "import-demand":
            if not args.file:
                parser.error("import-demand requires --file")
            with open(args.file, encoding="utf-8") as handle:
                payload = json.load(handle)
            data = DemandEvidenceCreate.model_validate({**payload, "verified_snapshot": args.verified})
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
                # A CLI flag cannot establish an external source receipt.  Keep
                # imported evidence honest until the owner records one through
                # the receipt endpoint.
                verification_status="imported_unverified",
                verification_receipt={},
                source_verified_at=None,
            )
            db.add(evidence)
            record_audit(
                db,
                "demand_evidence_imported",
                "owner" if args.verified else "operator",
                "External content remains untrusted until a persisted source receipt is recorded.",
                {"source_url": evidence.source_url, "requested_verified_snapshot": args.verified},
            )
            db.commit()
            print(json.dumps({"id": evidence.id, "verification_status": evidence.verification_status}))
            return
        seed_demo(db)
        db.commit()
    if args.command == "seed":
        print("seeded")
        return
    if args.command == "cycle":
        with SessionLocal() as db:
            response = TestClient(app).post(
                "/api/demo/cycle",
                headers={"X-Owner-Token": settings.owner_token or ""},
            )
            print(response.text)
        return
if __name__ == "__main__":
    main()
