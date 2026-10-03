from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.runtime as runtime
from app import db as db_module
from app.models import CeoSchedule, SystemState
from app.queue import dispatch_job
from app.security import security_event
from app.config import settings


def _persist_schedule(db, *, generation: str = "schedule-generation", remaining_runs: int = 2, active: bool = True) -> CeoSchedule:
    schedule = db.get(CeoSchedule, 1)
    if schedule is None:
        schedule = CeoSchedule(id=1, generation=generation)
        db.add(schedule)
    schedule.generation = generation
    schedule.active = active
    schedule.remaining_runs = remaining_runs
    schedule.running = False
    schedule.run_started_at = None
    schedule.cancelled_at = None
    db.commit()
    return schedule


def test_recurring_schedule_is_singleton_bounded_and_cancellable(db, monkeypatch):
    monkeypatch.setattr(settings, "queue_mode", "redis")

    class FakeQueue:
        def __init__(self):
            self.calls = []
            self.committed_generations = []

        def enqueue(self, job, payload, **kwargs):
            assert db_module.SessionLocal is not None
            with db_module.SessionLocal() as committed:
                schedule = committed.get(CeoSchedule, 1)
                self.committed_generations.append(schedule.generation if schedule and schedule.active else None)
            self.calls.append((job, payload, kwargs))
            return {
                "job": job,
                "payload": payload,
                "mode": "redis",
                "queue_job_id": f"fake-{len(self.calls)}",
                **kwargs,
            }

    fake_queue = FakeQueue()
    monkeypatch.setattr(main, "build_queue", lambda: fake_queue)
    headers = {"X-Owner-Token": "test-owner"}
    with TestClient(main.app) as client:
        first = client.post("/api/ceo/schedule?recurring=true&interval_seconds=60", headers=headers)
        assert first.status_code == 200
        body = first.json()
        assert body["remaining_runs"] == runtime.MAX_CYCLES
        assert body["schedule_generation"]
        assert fake_queue.calls[0][1]["schedule_generation"] == body["schedule_generation"]
        assert fake_queue.committed_generations[0] == body["schedule_generation"]
        assert fake_queue.calls[0][2]["repeat_times"] == runtime.MAX_CYCLES - 1

        duplicate = client.post("/api/ceo/schedule?recurring=true&interval_seconds=60", headers=headers)
        assert duplicate.status_code == 409
        assert client.post("/api/ceo/schedule/cancel").status_code == 403

        cancelled = client.post("/api/ceo/schedule/cancel", headers=headers)
        assert cancelled.status_code == 200
        assert cancelled.json()["active"] is False
        second = client.post("/api/ceo/schedule?recurring=true&interval_seconds=60", headers=headers)
        assert second.status_code == 200
        assert second.json()["schedule_generation"] != body["schedule_generation"]


def test_recurring_enqueue_failure_invalidates_committed_generation(db, monkeypatch):
    monkeypatch.setattr(settings, "queue_mode", "redis")
    attempted = []

    class FailingQueue:
        def enqueue(self, _job, payload, **_kwargs):
            attempted.append(payload["schedule_generation"])
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr(main, "build_queue", FailingQueue)
    with TestClient(main.app) as client:
        with pytest.raises(RuntimeError, match="redis unavailable"):
            client.post(
                "/api/ceo/schedule?recurring=true&interval_seconds=60",
                headers={"X-Owner-Token": "test-owner"},
            )
    db.expire_all()
    schedule = db.get(CeoSchedule, 1)
    assert attempted and schedule and schedule.active is False
    assert schedule.generation != attempted[0]


def test_delayed_one_shot_schedule_is_rejected_before_enqueue(monkeypatch):
    monkeypatch.setattr(settings, "queue_mode", "redis")
    calls = []

    class QueueMustNotBeUsed:
        def enqueue(self, *args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("unfenced delayed one-shot must not be enqueued")

    monkeypatch.setattr(main, "build_queue", lambda: QueueMustNotBeUsed())
    with TestClient(main.app) as client:
        response = client.post(
            "/api/ceo/schedule?delay_seconds=1",
            headers={"X-Owner-Token": "test-owner"},
        )
    assert response.status_code == 400
    assert calls == []


def test_dispatch_skips_stale_cancelled_and_busy_generations(db, monkeypatch):
    state = SystemState(id=1)
    db.add(state)
    _persist_schedule(db, generation="current-generation")
    calls = []

    def fake_run_cycle(db, *, demo=False):
        calls.append(demo)
        return SimpleNamespace(id=f"cycle-{len(calls)}", status="ok")

    monkeypatch.setattr(runtime, "run_cycle", fake_run_cycle)
    stale = dispatch_job("ceo_cycle", {"recurring": True, "schedule_generation": "old-generation"})
    assert stale["status"] == "skipped"
    assert stale["reason"] == "stale_schedule_generation"
    assert calls == []

    schedule = db.get(CeoSchedule, 1)
    assert schedule
    schedule.active = False
    db.commit()
    cancelled = dispatch_job("ceo_cycle", {"recurring": True, "schedule_generation": "current-generation"})
    assert cancelled["reason"] == "cancelled_schedule_generation"
    assert calls == []

    schedule.active = True
    schedule.running = True
    schedule.run_started_at = datetime.now(timezone.utc)
    db.commit()
    busy = dispatch_job("ceo_cycle", {"recurring": True, "schedule_generation": "current-generation"})
    assert busy["reason"] == "schedule_run_in_progress"
    assert calls == []


def test_dispatch_decrements_remaining_and_deactivates_at_zero_or_circuit_breaker(db, monkeypatch):
    db.add(SystemState(id=1))
    _persist_schedule(db, generation="bounded-generation", remaining_runs=2)
    statuses = iter(("ok", "ok"))

    def fake_run_cycle(db, *, demo=False):
        return SimpleNamespace(id="cycle", status=next(statuses))

    monkeypatch.setattr(runtime, "run_cycle", fake_run_cycle)
    payload = {"recurring": True, "schedule_generation": "bounded-generation"}
    assert dispatch_job("ceo_cycle", payload)["status"] == "ok"
    db.expire_all()
    schedule = db.get(CeoSchedule, 1)
    assert schedule and schedule.remaining_runs == 1 and schedule.active is True
    assert dispatch_job("ceo_cycle", payload)["status"] == "ok"
    db.expire_all()
    schedule = db.get(CeoSchedule, 1)
    assert schedule and schedule.remaining_runs == 0 and schedule.active is False and schedule.running is False

    _persist_schedule(db, generation="circuit-generation", remaining_runs=2)
    monkeypatch.setattr(runtime, "run_cycle", lambda db, *, demo=False: SimpleNamespace(id="circuit", status="circuit_breaker"))
    assert dispatch_job("ceo_cycle", {"recurring": True, "schedule_generation": "circuit-generation"})["status"] == "circuit_breaker"
    db.expire_all()
    schedule = db.get(CeoSchedule, 1)
    assert schedule and schedule.active is False and schedule.remaining_runs == 0


def test_manual_and_automatic_freeze_invalidate_queued_generation(db, monkeypatch):
    db.add(SystemState(id=1))
    _persist_schedule(db, generation="freeze-generation", remaining_runs=2)
    calls = []
    monkeypatch.setattr(runtime, "run_cycle", lambda db, *, demo=False: calls.append(True))

    security_event(db, "HIGH", "automatic_freeze", {}, freeze=True)
    db.expire_all()
    schedule = db.get(CeoSchedule, 1)
    assert schedule and schedule.active is False
    assert dispatch_job("ceo_cycle", {"recurring": True, "schedule_generation": "freeze-generation"})["status"] == "skipped"
    assert calls == []

    state = db.get(SystemState, 1)
    assert state
    state.frozen = False
    db.commit()
    assert dispatch_job("ceo_cycle", {"recurring": True, "schedule_generation": "freeze-generation"})["status"] == "skipped"
    assert calls == []

    _persist_schedule(db, generation="manual-freeze-generation", remaining_runs=2)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/security/freeze",
            headers={"X-Owner-Token": "test-owner"},
            json={"reason": "manual test freeze"},
        )
        assert response.status_code == 200
    db.expire_all()
    schedule = db.get(CeoSchedule, 1)
    assert schedule and schedule.active is False
    state = db.get(SystemState, 1)
    assert state and state.frozen is True
    assert dispatch_job("ceo_cycle", {"recurring": True, "schedule_generation": "manual-freeze-generation"})["status"] == "skipped"
    with TestClient(main.app) as client:
        response = client.post("/api/security/unfreeze", headers={"X-Owner-Token": "test-owner"})
        assert response.status_code == 200
    db.expire_all()
    state = db.get(SystemState, 1)
    schedule = db.get(CeoSchedule, 1)
    assert state and state.frozen is False
    assert schedule and schedule.active is False
    assert dispatch_job("ceo_cycle", {"recurring": True, "schedule_generation": "manual-freeze-generation"})["status"] == "skipped"
