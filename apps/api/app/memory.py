from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MemoryEntry


MEMORY_KINDS = {"working", "project", "experiment", "counterparty", "strategic", "failure"}


def remember(
    db: Session,
    kind: str,
    content: dict[str, Any],
    tags: list[str] | None = None,
    experiment_id: str | None = None,
    project_id: str | None = None,
) -> MemoryEntry:
    if kind not in MEMORY_KINDS:
        raise ValueError(f"unsupported memory kind: {kind}")
    entry = MemoryEntry(
        kind=kind,
        content=content,
        tags=tags or [],
        experiment_id=experiment_id,
        project_id=project_id,
    )
    db.add(entry)
    db.flush()
    return entry


def retrieve(db: Session, kind: str | None = None, tag: str | None = None, limit: int = 50) -> list[MemoryEntry]:
    query = select(MemoryEntry).order_by(MemoryEntry.created_at.desc()).limit(limit)
    if kind:
        query = query.where(MemoryEntry.kind == kind)
    entries = list(db.scalars(query))
    if tag:
        entries = [entry for entry in entries if tag in (entry.tags or [])]
    return entries

