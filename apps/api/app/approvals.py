from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import record_audit
from .models import ApprovalEvent, ApprovalRequest, uid


def create_approval(
    db: Session,
    approval_class: str,
    requested_by: str,
    action_type: str,
    payload: dict[str, Any],
    reason: str,
) -> ApprovalRequest:
    approval = ApprovalRequest(
        approval_class=approval_class,
        requested_by=requested_by,
        action_type=action_type,
        payload=payload,
        reason=reason,
    )
    db.add(approval)
    db.flush()
    db.add(
        ApprovalEvent(
            approval_id=approval.id,
            event_id=uid(),
            event="PENDING",
            actor=requested_by,
            payload={"reason": reason},
        )
    )
    record_audit(db, "approval_requested", requested_by, reason, {"approval_id": approval.id, "action_type": action_type})
    db.flush()
    return approval


def latest_approval_event(db: Session, approval_id: str) -> ApprovalEvent | None:
    return db.scalars(
        select(ApprovalEvent)
        .where(ApprovalEvent.approval_id == approval_id)
        .order_by(ApprovalEvent.created_at.desc())
        .limit(1)
    ).first()


def approval_status(db: Session, approval_id: str) -> str:
    event = latest_approval_event(db, approval_id)
    return event.event if event else "UNKNOWN"


def matching_approved_id(
    db: Session,
    action_type: str,
    requested_by: str,
    payload: dict[str, Any],
) -> str | None:
    requests = db.scalars(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.action_type == action_type,
            ApprovalRequest.requested_by == requested_by,
        )
        .order_by(ApprovalRequest.created_at.desc())
    )
    for request in requests:
        event = latest_approval_event(db, request.id)
        if event is None or event.event not in {"APPROVE", "EDIT_AND_APPROVE"}:
            continue
        expected = dict(request.payload)
        if event.event == "EDIT_AND_APPROVE":
            expected.update(event.payload.get("edits", {}))
        if expected == payload:
            return request.id
    return None


def decide_approval(
    db: Session,
    approval_id: str,
    decision: str,
    actor: str,
    edits: dict[str, Any] | None = None,
) -> ApprovalEvent:
    approval = db.scalars(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id)
        .with_for_update()
    ).first()
    if approval is None:
        raise KeyError("approval not found")
    if approval_status(db, approval_id) != "PENDING":
        raise ValueError("approval is already decided")
    event = ApprovalEvent(
        approval_id=approval_id,
        event_id=uid(),
        event=decision,
        actor=actor,
        payload={"edits": edits or {}},
    )
    db.add(event)
    record_audit(db, "approval_decided", actor, decision, {"approval_id": approval_id, "edits": edits or {}})
    db.flush()
    return event


def consume_approval(db: Session, approval_id: str, actor: str) -> ApprovalEvent:
    approval = db.scalars(
        select(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id)
        .with_for_update()
    ).first()
    if approval is None:
        raise ValueError("approval is not executable")
    if approval_status(db, approval_id) not in {"APPROVE", "EDIT_AND_APPROVE"}:
        raise ValueError("approval is not executable")
    event = ApprovalEvent(
        approval_id=approval_id,
        event_id=uid(),
        event="CONSUMED",
        actor=actor,
        payload={},
    )
    db.add(event)
    record_audit(db, "approval_consumed", actor, "approved action executed once", {"approval_id": approval_id})
    db.flush()
    return event


def list_approvals(db: Session, limit: int = 100) -> list[dict[str, Any]]:
    requests = list(db.scalars(select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc()).limit(limit)))
    return [
        {
            "id": request.id,
            "approval_class": request.approval_class,
            "requested_by": request.requested_by,
            "action_type": request.action_type,
            "payload": request.payload,
            "reason": request.reason,
            "status": approval_status(db, request.id),
            "created_at": request.created_at,
        }
        for request in requests
    ]
