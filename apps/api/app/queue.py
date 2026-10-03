from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

from sqlalchemy import select

from .config import settings
from .models import CeoSchedule, SystemState, uid, utcnow


SCHEDULE_ROW_ID = 1
SCHEDULE_LEASE_SECONDS = 120


def _locked_schedule(db) -> CeoSchedule | None:
    return db.scalars(
        select(CeoSchedule).where(CeoSchedule.id == SCHEDULE_ROW_ID).with_for_update()
    ).first()


def _ensure_schedule(db) -> CeoSchedule:
    schedule = _locked_schedule(db)
    if schedule is None:
        schedule = CeoSchedule(id=SCHEDULE_ROW_ID, generation=uid())
        db.add(schedule)
        db.flush()
    return schedule


def _run_is_live(schedule: CeoSchedule) -> bool:
    if not schedule.running:
        return False
    if schedule.run_started_at is None:
        return True
    started_at = schedule.run_started_at
    if started_at.tzinfo is None:
        from datetime import timezone

        started_at = started_at.replace(tzinfo=timezone.utc)
    return started_at > utcnow() - timedelta(seconds=SCHEDULE_LEASE_SECONDS)


def _invalidate_locked(schedule: CeoSchedule) -> CeoSchedule:
    schedule.active = False
    schedule.remaining_runs = 0
    schedule.generation = uid()
    schedule.running = False
    schedule.run_started_at = None
    schedule.cancelled_at = utcnow()
    return schedule


def create_recurring_schedule(db, interval_seconds: int, max_runs: int) -> CeoSchedule:
    state = db.scalars(
        select(SystemState).where(SystemState.id == 1).with_for_update()
    ).first()
    if state and state.frozen:
        raise ValueError("autonomy is frozen")
    schedule = _ensure_schedule(db)
    if schedule.active:
        raise ValueError("an active recurring CEO schedule already exists")
    if schedule.running and _run_is_live(schedule):
        raise ValueError("a recurring CEO schedule is still running")
    schedule.generation = uid()
    schedule.active = True
    schedule.remaining_runs = max_runs
    schedule.interval_seconds = interval_seconds
    schedule.running = False
    schedule.run_started_at = None
    schedule.last_run_at = None
    schedule.cancelled_at = None
    db.flush()
    return schedule


def cancel_recurring_schedule(db) -> CeoSchedule:
    schedule = _ensure_schedule(db)
    _invalidate_locked(schedule)
    db.flush()
    return schedule


def invalidate_recurring_schedule(db) -> CeoSchedule | None:
    """Invalidate an existing generation without creating a schedule row."""

    schedule = _locked_schedule(db)
    if schedule is None:
        return None
    _invalidate_locked(schedule)
    db.flush()
    return schedule


def _skip_schedule(reason: str, generation: str | None = None) -> dict[str, Any]:
    return {
        "cycle_id": None,
        "status": "skipped",
        "reason": reason,
        "schedule_generation": generation,
    }


def _claim_recurring(db, generation: str) -> dict[str, Any] | None:
    state = db.scalars(
        select(SystemState).where(SystemState.id == 1).with_for_update()
    ).first()
    schedule = _locked_schedule(db)
    if schedule is None:
        db.rollback()
        return _skip_schedule("schedule_not_found", generation)
    if schedule.generation != generation:
        db.rollback()
        return _skip_schedule("stale_schedule_generation", generation)
    if not schedule.active:
        db.rollback()
        return _skip_schedule("cancelled_schedule_generation", generation)
    if state and state.frozen:
        _invalidate_locked(schedule)
        db.commit()
        return _skip_schedule("frozen_schedule_generation", generation)
    if schedule.remaining_runs <= 0:
        schedule.active = False
        db.commit()
        return _skip_schedule("schedule_exhausted", generation)
    if schedule.running:
        if _run_is_live(schedule):
            db.rollback()
            return _skip_schedule("schedule_run_in_progress", generation)
        schedule.running = False
        schedule.run_started_at = None
    schedule.running = True
    schedule.run_started_at = utcnow()
    schedule.remaining_runs -= 1
    if schedule.remaining_runs <= 0:
        schedule.active = False
    db.commit()
    return None


def _finish_recurring(db, generation: str, status: str) -> None:
    state = db.scalars(
        select(SystemState).where(SystemState.id == 1).with_for_update()
    ).first()
    schedule = _locked_schedule(db)
    if schedule is None:
        db.commit()
        return
    if schedule.generation != generation:
        # A freeze/cancel/new generation owns the row now.  Preserve the cycle
        # result without mutating the newer schedule's run state.
        db.commit()
        return
    schedule.running = False
    schedule.run_started_at = None
    schedule.last_run_at = utcnow()
    if status in {"circuit_breaker", "frozen"} or (state and state.frozen):
        schedule.active = False
        schedule.remaining_runs = 0
    elif schedule.remaining_runs <= 0:
        schedule.active = False
    db.commit()


@dataclass
class DirectQueue:
    pending: list[dict[str, Any]] = field(default_factory=list)

    def enqueue(
        self,
        job: str,
        payload: dict[str, Any],
        delay_seconds: int = 0,
        repeat_seconds: int = 0,
        repeat_times: int = 0,
    ) -> dict[str, Any]:
        if delay_seconds or repeat_seconds or repeat_times:
            raise ValueError("direct queue cannot delay or repeat jobs")
        item = {"job": job, "payload": payload, "mode": "direct"}
        self.pending.append(item)
        return item

    def run_next(self, handlers: dict[str, Callable[[dict[str, Any]], Any]]) -> Any:
        if not self.pending:
            return None
        item = self.pending.pop(0)
        handler = handlers.get(item["job"])
        if handler is None:
            raise KeyError(f"unknown job: {item['job']}")
        return handler(item["payload"])


class RedisQueue:
    """RQ-backed production queue with bounded retries; imported only in redis mode."""

    def __init__(self, redis_url: str):
        from redis import Redis
        from rq import Queue, Retry

        self.queue = Queue("autonomous-company", connection=Redis.from_url(redis_url))
        self.retry = Retry(max=3, interval=[1, 5, 15])

    def enqueue(
        self,
        job: str,
        payload: dict[str, Any],
        delay_seconds: int = 0,
        repeat_seconds: int = 0,
        repeat_times: int = 0,
    ) -> dict[str, Any]:
        if (
            job == "ceo_cycle"
            and delay_seconds
            and not (
                payload.get("recurring") is True
                and isinstance(payload.get("schedule_generation"), str)
                and bool(payload["schedule_generation"])
            )
        ):
            raise ValueError("delayed CEO cycles require a recurring schedule generation")
        enqueue = self.queue.enqueue_in if delay_seconds else self.queue.enqueue
        args = (timedelta(seconds=delay_seconds), "app.queue.dispatch_job", job, payload) if delay_seconds else ("app.queue.dispatch_job", job, payload)
        options: dict[str, Any] = {"retry": self.retry, "job_timeout": 60}
        if repeat_seconds and repeat_times:
            from rq import Repeat

            options["repeat"] = Repeat(times=repeat_times, interval=repeat_seconds)
        queued = enqueue(*args, **options)
        return {
            "job": job,
            "payload": payload,
            "mode": "redis",
            "queue_job_id": queued.id,
            "delay_seconds": delay_seconds,
            "repeat_seconds": repeat_seconds,
            "repeat_times": repeat_times,
        }


def build_queue() -> DirectQueue | RedisQueue:
    if settings.queue_mode == "redis":
        return RedisQueue(settings.redis_url)
    return DirectQueue()


def dispatch_job(job: str, payload: dict[str, Any]) -> dict[str, Any]:
    """RQ entry point for the bounded CEO wake-up job."""

    if job != "ceo_cycle":
        raise KeyError(f"unknown job: {job}")
    from . import db as db_module
    from .runtime import run_cycle

    if db_module.SessionLocal is None:
        db_module.configure_database()
    assert db_module.SessionLocal is not None
    generation = payload.get("schedule_generation")
    if payload.get("recurring") and not isinstance(generation, str):
        return _skip_schedule("missing_schedule_generation")
    with db_module.SessionLocal() as db:
        if generation is not None:
            if not isinstance(generation, str) or not generation:
                return _skip_schedule("invalid_schedule_generation", str(generation))
            skipped = _claim_recurring(db, generation)
            if skipped is not None:
                return skipped
        try:
            cycle = run_cycle(db, demo=bool(payload.get("demo", False)))
        except Exception:
            if generation is not None:
                db.rollback()
                _finish_recurring(db, generation, "failed")
            raise
        if generation is not None:
            _finish_recurring(db, generation, cycle.status)
        else:
            db.commit()
        return {"cycle_id": cycle.id, "status": cycle.status, "schedule_generation": generation}
