from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import AgentState


SPECIALIST_CONTRACTS: dict[str, dict[str, Any]] = {
    "Research Agent": {
        "instructions": "Find evidence and opportunities; never spend, publish, or communicate.",
        "permissions": ["research.search", "research.fetch", "simulation.research"],
    },
    "Product/Builder Agent": {
        "instructions": "Design sandboxed digital artifacts; never access secrets or deploy externally.",
        "permissions": ["sandbox.execute", "experiment.create", "memory.write"],
    },
    "Marketing Agent": {
        "instructions": "Draft compliant distribution material; never publish without policy approval.",
        "permissions": ["analytics.record", "publish"],
    },
    "Sales Agent": {
        "instructions": "Handle approved counterparties; never spam, impersonate, or self-deal.",
        "permissions": ["communicate", "marketplace.request", "simulation.revenue"],
    },
    "Finance Analyst Agent": {
        "instructions": "Calculate paper economics from ledger state; never authorize funds.",
        "permissions": ["analytics.record", "memory.write"],
    },
    "Risk/Critic Agent": {
        "instructions": "Challenge assumptions and identify legal, platform, and financial risks.",
        "permissions": ["research.search", "memory.write"],
    },
    "Verification Agent": {
        "instructions": "Verify evidence and outcomes; never alter policy, audit, or treasury controls.",
        "permissions": ["research.fetch", "analytics.record", "memory.write"],
    },
    "Bug Bounty Agent": {
        "instructions": (
            "Passive by default: import and triage public program scope and draft findings only. "
            "Never test without exact owner authorization; never access, exfiltrate, persist, phish, "
            "social-engineer, load-test, or submit/disclose externally."
        ),
        "permissions": ["research.fetch", "analytics.record", "memory.write"],
    },
}


def ensure_agents(db: Session) -> list[AgentState]:
    result: list[AgentState] = []
    for role, contract in SPECIALIST_CONTRACTS.items():
        agent = db.scalars(select(AgentState).where(AgentState.role == role)).first()
        if agent is None:
            agent = AgentState(role=role, instructions=contract["instructions"], permissions=contract["permissions"])
            db.add(agent)
        else:
            agent.instructions = contract["instructions"]
            agent.permissions = contract["permissions"]
        result.append(agent)
    manager = db.scalars(select(AgentState).where(AgentState.role == "CEO Agent")).first()
    if manager is None:
        manager = AgentState(
            role="CEO Agent",
            instructions="Coordinate bounded cycles, choose opportunities, and delegate through the broker.",
            permissions=["experiment.create", "experiment.run", "experiment.scale", "experiment.terminate", "memory.write", "simulation.expense"],
        )
        db.add(manager)
    else:
        manager.permissions = ["experiment.create", "experiment.run", "experiment.scale", "experiment.terminate", "memory.write", "simulation.expense"]
    result.append(manager)
    db.flush()
    return result


class MockCEOModel:
    def propose(self, context: dict[str, Any]) -> dict[str, Any]:
        return {
            "rationale": "Review a diversified multi-stream portfolio, then choose the highest-scoring reversible opportunity with bounded simulated spend.",
            "max_turns": 8,
            "max_tool_calls": 16,
            "max_cost_cents": 100,
        }


class OpenAIAgentsModel:
    """Optional OpenAI Agents SDK bridge; no import or call occurs in mock mode."""

    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise RuntimeError("LLM_MODE=openai requires OPENAI_API_KEY")
        try:
            from agents import Agent, Runner  # type: ignore
        except ImportError as exc:
            raise RuntimeError("install the optional llm extra for OpenAI Agents SDK") from exc
        self.Agent = Agent
        self.Runner = Runner

    def propose(self, context: dict[str, Any]) -> dict[str, Any]:
        # The deterministic manager remains authoritative. This bridge is intentionally
        # narrow: the SDK may suggest structured text, but policy and ledger decide.
        raise RuntimeError("OpenAI proposal execution is opt-in and not enabled for the paper demo")


def build_model() -> MockCEOModel | OpenAIAgentsModel:
    return OpenAIAgentsModel() if settings.llm_mode == "openai" else MockCEOModel()
