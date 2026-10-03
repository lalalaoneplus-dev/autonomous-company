from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditEvent, utcnow


def record_audit(
    db: Session,
    event_type: str,
    actor: str,
    rationale: str = "",
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        event_type=event_type,
        actor=actor,
        rationale=rationale[:2000],
        payload=payload or {},
    )
    db.add(event)
    db.flush()
    return event


def list_audit(db: Session, limit: int = 100) -> list[AuditEvent]:
    return list(db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)))

