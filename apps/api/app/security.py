from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import record_audit
from .models import CeoSchedule, SecurityEvent, SystemState, uid, utcnow


def security_event(
    db: Session,
    severity: str,
    event_type: str,
    detail: dict[str, Any] | None = None,
    freeze: bool = False,
) -> SecurityEvent:
    event = SecurityEvent(
        severity=severity,
        event_type=event_type,
        detail=detail or {},
        froze_autonomy=freeze,
    )
    db.add(event)
    state = (
        db.scalars(
            select(SystemState).where(SystemState.id == 1).with_for_update()
        ).first()
        if freeze
        else db.get(SystemState, 1)
    )
    if freeze and state is None:
        state = SystemState(id=1)
        db.add(state)
        db.flush()
    if freeze:
        assert state is not None
        state.frozen = True
        state.freeze_reason = event_type
        schedule = db.scalars(
            select(CeoSchedule).where(CeoSchedule.id == 1).with_for_update()
        ).first()
        if schedule is not None:
            schedule.active = False
            schedule.remaining_runs = 0
            schedule.generation = uid()
            schedule.running = False
            schedule.run_started_at = None
            schedule.cancelled_at = utcnow()
    record_audit(db, "security_event", "policy-engine", event_type, detail or {})
    db.flush()
    # Security denials must survive the request transaction even when the
    # caller converts the denial into an HTTP error and the framework rolls
    # back the surrounding unit of work.
    db.commit()
    return event


def current_security_state(db: Session) -> dict[str, Any]:
    state = db.get(SystemState, 1)
    events = list(
        db.scalars(select(SecurityEvent).order_by(SecurityEvent.created_at.desc()).limit(25))
    )
    return {
        "frozen": bool(state and state.frozen),
        "freeze_reason": state.freeze_reason if state else None,
        "events": events,
    }
