from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .approvals import consume_approval
from .audit import record_audit
from .models import AgentState, DeliverableProof, DemandNegotiation, Experiment
from .policy import policy_engine
from .schemas import ActionRequest, PolicyResult
from .treasury import record_expense, record_revenue


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    category: str
    risk_class: str
    required_autonomy_level: int
    financial_exposure: bool
    approval_may_be_needed: bool


TOOLS = [
    ToolDefinition("research.search", "Search approved research sources", "research", "low", 0, False, False),
    ToolDefinition("research.fetch", "Fetch a webpage as untrusted data", "research", "low", 0, False, False),
    ToolDefinition("simulation.research", "Return seeded research evidence", "research", "low", 0, False, False),
    ToolDefinition("sandbox.execute", "Execute in a restricted workspace", "execution", "medium", 1, False, True),
    ToolDefinition("publish", "Publish through a configured adapter", "publishing", "high", 2, False, True),
    ToolDefinition("communicate", "Send an approved communication", "communication", "high", 2, False, True),
    ToolDefinition("spend", "Spend through an approved payment adapter", "commerce", "high", 3, True, True),
    ToolDefinition("simulation.expense", "Record a simulated expense", "commerce", "low", 3, True, False),
    ToolDefinition("simulation.revenue", "Record simulated customer revenue", "commerce", "low", 4, False, False),
    ToolDefinition("crypto.transfer", "Transfer through a constrained wallet", "crypto", "critical", 4, True, True),
    ToolDefinition("analytics.record", "Record simulated funnel metrics", "analytics", "low", 0, False, False),
    ToolDefinition("bugbounty.passive_triage", "Review imported scope and passive evidence only", "bug-bounty", "low", 0, False, False),
    ToolDefinition("bugbounty.test_plan", "Draft an owner-reviewable bounded test plan", "bug-bounty", "high", 1, False, True),
    ToolDefinition("bugbounty.active_testing", "Disabled external testing placeholder", "bug-bounty", "critical", 4, False, True),
    ToolDefinition("bugbounty.submit", "Disabled external report submission placeholder", "bug-bounty", "critical", 4, False, True),
    ToolDefinition("marketplace.request", "Request work from an internal simulated agent", "marketplace", "medium", 1, False, True),
    ToolDefinition("nft.metadata", "Generate collectible metadata without deployment", "nft", "medium", 1, False, True),
]


@dataclass
class ToolResult:
    policy: PolicyResult
    executed: bool
    output: dict[str, Any]


class ToolBroker:
    def call(self, db: Session, request: ActionRequest) -> ToolResult:
        policy = policy_engine.evaluate(db, request)
        if policy.decision != "ALLOW":
            return ToolResult(policy=policy, executed=False, output={"blocked": True})

        agent = db.scalars(select(AgentState).where(AgentState.role == request.requesting_agent)).first()
        if agent is None or not agent.active or request.action_type not in (agent.permissions or []):
            reason = "requesting agent is not permitted to invoke this broker tool"
            permission = policy_engine.deny_permission(db, request, reason)
            return ToolResult(policy=permission, executed=False, output={"blocked": True, "reason": reason})

        output: dict[str, Any] = {"simulated": request.simulation}
        if request.action_type == "simulation.expense":
            if not request.experiment_id:
                return ToolResult(policy=policy, executed=False, output={"error": "experiment_id is required"})
            experiment = db.get(Experiment, request.experiment_id)
            if experiment is None:
                return ToolResult(policy=policy, executed=False, output={"error": "experiment not found"})
            if experiment.status != "RUNNING":
                return ToolResult(policy=policy, executed=False, output={"error": "experiment must be RUNNING before expense"})
            record_expense(
                db,
                request.amount_cents,
                request.payload.get("description", "Simulated experiment expense"),
                agent=request.requesting_agent,
                experiment_id=experiment.id,
                policy_decision_id=policy.policy_decision_id,
            )
            experiment.expenses_cents += request.amount_cents
            output["expense_cents"] = request.amount_cents
        elif request.action_type == "simulation.revenue":
            if request.amount_cents <= 0:
                return ToolResult(policy=policy, executed=False, output={"error": "revenue amount must be positive"})
            if not request.experiment_id:
                return ToolResult(policy=policy, executed=False, output={"error": "experiment_id is required"})
            experiment = db.get(Experiment, request.experiment_id)
            if experiment is None:
                return ToolResult(policy=policy, executed=False, output={"error": "experiment not found"})
            if experiment.status != "RUNNING":
                return ToolResult(policy=policy, executed=False, output={"error": "experiment must be RUNNING before revenue"})
            if not experiment.negotiation_id:
                return ToolResult(policy=policy, executed=False, output={"error": "revenue requires a gated negotiation"})
            negotiation = db.get(DemandNegotiation, experiment.negotiation_id)
            if negotiation is None or negotiation.state != "OWNER_DELIVERY_DECISION" or negotiation.owner_delivery_decision != "PAPER":
                return ToolResult(policy=policy, executed=False, output={"error": "revenue requires the owner delivery decision gate"})
            if negotiation.agreed_currency != "CAD":
                return ToolResult(policy=policy, executed=False, output={"error": "cross-currency revenue requires explicit conversion provenance"})
            if request.amount_cents != negotiation.agreed_price_cents:
                return ToolResult(policy=policy, executed=False, output={"error": "revenue must equal the agreed CAD minor-unit price"})
            if experiment.revenue_cents:
                return ToolResult(policy=policy, executed=False, output={"error": "paper settlement is already recorded"})
            proof = db.scalars(select(DeliverableProof).where(DeliverableProof.experiment_id == experiment.id)).first()
            if proof is None or proof.settlement != "PAPER" or proof.acceptance != "SIMULATED":
                return ToolResult(policy=policy, executed=False, output={"error": "revenue requires a paper deliverable proof"})
            record_revenue(
                db,
                request.amount_cents,
                request.payload.get("description", "Simulated customer revenue"),
                agent=request.requesting_agent,
                experiment_id=experiment.id,
                policy_decision_id=policy.policy_decision_id,
            )
            experiment.revenue_cents += request.amount_cents
            output["revenue_cents"] = request.amount_cents
        elif request.action_type == "simulation.research":
            output.update({"evidence": request.payload.get("evidence", "seeded simulation evidence")})
        else:
            output["adapter"] = "inert"
            output["message"] = "No external adapter is enabled in this phase."
            record_audit(db, "tool_result", request.requesting_agent, request.action_type, output)
            db.flush()
            return ToolResult(policy=policy, executed=False, output=output)
        record_audit(db, "tool_result", request.requesting_agent, request.action_type, output)
        if request.approval_id:
            consume_approval(db, request.approval_id, request.requesting_agent)
        db.flush()
        return ToolResult(policy=policy, executed=True, output=output)


tool_broker = ToolBroker()
