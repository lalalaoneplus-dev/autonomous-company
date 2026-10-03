from app.policy import policy_engine
from app.schemas import ActionRequest
from app.seed import seed_demo
from app.models import SystemState


def test_category_cap_accumulates_only_allowed_financial_spend(db):
    seed_demo(db)
    state = db.get(SystemState, 1)
    assert state
    state.autonomy_level = 4
    state.category_limits_cents = {"research": 10, "other": 10, "denied": 10}
    state.category_denylist = ["denied"]

    first = policy_engine.evaluate(
        db,
        ActionRequest(action_type="simulation.expense", category=" Research ", simulation=True, amount_cents=6),
    )
    denied = policy_engine.evaluate(
        db,
        ActionRequest(action_type="simulation.expense", category="denied", simulation=True, amount_cents=5),
    )
    unrelated = policy_engine.evaluate(
        db,
        ActionRequest(action_type="simulation.expense", category="other", simulation=True, amount_cents=9),
    )
    revenue = policy_engine.evaluate(
        db,
        ActionRequest(action_type="simulation.revenue", category="research", simulation=True, amount_cents=4),
    )
    second = policy_engine.evaluate(
        db,
        ActionRequest(action_type="simulation.expense", category="research", simulation=True, amount_cents=4),
    )
    over_cap = policy_engine.evaluate(
        db,
        ActionRequest(action_type="simulation.expense", category="research", simulation=True, amount_cents=1),
    )

    assert first.decision == "ALLOW"
    assert denied.decision == "DENY"
    assert unrelated.decision == "ALLOW"
    assert revenue.decision == "ALLOW"
    assert second.decision == "ALLOW"
    assert over_cap.decision == "DENY"
    assert "category spending limit" in over_cap.reason
