from __future__ import annotations

from sqlalchemy.orm import Session

from .agents import ensure_agents
from .config import settings
from .db import configure_database
from .memory import remember
from .models import MemoryEntry, Project, SystemState
from .opportunities import upsert_opportunities
from .treasury import ensure_paper_treasury


def seed_demo(db: Session, *, demo_autonomy: bool = True) -> SystemState:
    state = db.get(SystemState, 1)
    if state is None:
        state = SystemState(id=1)
        db.add(state)
        db.flush()
    state.objective = "Increase long-term legitimate economic profit while respecting deterministic constraints."
    state.owner_goal = "Retain legitimate surplus toward a future robot/equipment goal."
    state.strategy = "Work backward from the owner goal: find verified demand, deliver a small licensed artifact, measure settlement, and scale only after evidence."
    state.real_money_enabled = False
    if demo_autonomy:
        state.autonomy_level = 3
    ensure_agents(db)
    ensure_paper_treasury(db, settings.paper_treasury_cents)
    upsert_opportunities(db)
    if db.query(Project).filter(Project.name == "Goal-Backed Asset Experiments").first() is None:
        db.add(
            Project(
                name="Goal-Backed Asset Experiments",
                concept="Small legitimate digital deliverables selected from verified demand.",
                customer_problem="Approved counterparties need bounded research or automation artifacts.",
                audience="Verified simulated agents and compliant marketplace customers.",
                solution="Create, license, deliver, and measure small assets without self-dealing.",
                status="simulation",
            )
        )
    if not db.query(MemoryEntry).filter_by(kind="working").first():
        remember(db, "working", {"objective": state.objective, "owner_goal": state.owner_goal}, tags=["seed", "goal"])
    db.flush()
    return state


def main() -> None:
    configure_database()
    from .db import SessionLocal

    assert SessionLocal is not None
    with SessionLocal() as db:
        seed_demo(db)
        db.commit()
    print("seeded simulated treasury and opportunities")


if __name__ == "__main__":
    main()
