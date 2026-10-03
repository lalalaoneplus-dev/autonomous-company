from fastapi.testclient import TestClient

from app.db import configure_database
from app.main import app
from app.models import SystemState
from app.policy import policy_engine
from app.schemas import ActionRequest


OWNER_HEADERS = {"X-Owner-Token": "test-owner"}


def test_owner_updates_financial_limits_and_approval_threshold(db):
    configure_database(db.get_bind().url.render_as_string(hide_password=False))
    with TestClient(app) as client:
        response = client.patch(
            "/api/settings",
            headers=OWNER_HEADERS,
            json={
                "autonomy_level": 3,
                "global_spend_limit_cents": 400,
                "per_transaction_limit_cents": 150,
                "daily_spend_limit_cents": 200,
                "approval_threshold_cents": 100,
            },
        )
        assert response.status_code == 200
        limits = response.json()["limits"]
        assert limits["global_spend_cents"] == 400
        assert limits["per_transaction_cents"] == 150
        assert limits["daily_spend_cents"] == 200
        assert limits["approval_threshold_cents"] == 100

    db.expire_all()
    state = db.get(SystemState, 1)
    assert state
    assert state.approval_threshold_cents == 100
    allowed = policy_engine.evaluate(
        db,
        ActionRequest(action_type="simulation.expense", amount_cents=100, simulation=True),
    )
    requires_approval = policy_engine.evaluate(
        db,
        ActionRequest(action_type="simulation.expense", amount_cents=101, simulation=True),
    )
    assert allowed.decision == "ALLOW"
    assert requires_approval.decision == "REQUIRE_APPROVAL"


def test_settings_keep_real_money_forced_off_and_reveal_legacy_value(db):
    configure_database(db.get_bind().url.render_as_string(hide_password=False))
    db.add(SystemState(id=1, real_money_enabled=True))
    db.commit()

    with TestClient(app) as client:
        legacy = client.get("/api/settings", headers=OWNER_HEADERS)
        assert legacy.status_code == 200
        assert legacy.json()["real_money_enabled"] is False
        assert legacy.json()["real_money_enabled_stored"] is True
        assert legacy.json()["real_money_forced_off"] is True

        cleared = client.patch(
            "/api/settings",
            headers=OWNER_HEADERS,
            json={"real_money_enabled": False},
        )
        assert cleared.status_code == 200
        assert cleared.json()["real_money_enabled"] is False
        assert cleared.json()["real_money_enabled_stored"] is False

        assert client.patch(
            "/api/settings",
            headers=OWNER_HEADERS,
            json={"real_money_enabled": True},
        ).status_code == 400

    db.expire_all()
    state = db.get(SystemState, 1)
    assert state and state.real_money_enabled is False


def test_settings_reject_negative_financial_limits(db):
    configure_database(db.get_bind().url.render_as_string(hide_password=False))
    with TestClient(app) as client:
        response = client.patch(
            "/api/settings",
            headers=OWNER_HEADERS,
            json={"approval_threshold_cents": -1},
        )
    assert response.status_code == 422


def test_autonomy_ladder_gates_experiment_creation_and_simulated_revenue(db):
    state = SystemState(id=1, autonomy_level=0)
    db.add(state)
    db.flush()

    create = policy_engine.evaluate(
        db,
        ActionRequest(action_type="experiment.create", simulation=True),
    )
    revenue = policy_engine.evaluate(
        db,
        ActionRequest(action_type="simulation.revenue", simulation=True, amount_cents=1),
    )

    assert create.decision == "REQUIRE_APPROVAL"
    assert revenue.decision == "REQUIRE_APPROVAL"
