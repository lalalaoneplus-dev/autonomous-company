from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Experiment, Opportunity
from .platforms import platform_registry


STREAM_TYPES = (
    "agent_services",
    "digital_assets",
    "public_tasks",
    "affiliate_content",
    "bug_bounty",
)

# Explicit paper-only portfolio limits.  These are exposed to the dashboard so
# a CEO proposal can compare streams without silently concentrating risk.
PORTFOLIO_CAPS_BPS = {
    "stream_committed_risk": 3_500,
    "counterparty_platform_concentration": 2_000,
    "experiment_risk": 1_000,
    "bug_bounty_time_compute": 500,
    "reserve_unallocated": 2_500,
}


def stream_for(data: dict[str, Any]) -> str:
    explicit = data.get("stream_type")
    if explicit in STREAM_TYPES:
        return explicit
    mechanism = f"{data.get('mechanism', '')} {data.get('category', '')}".lower()
    if "bounty" in mechanism:
        return "bug_bounty"
    if "asset" in mechanism or "collectible" in mechanism:
        return "digital_assets"
    if "affiliate" in mechanism or "content" in mechanism:
        return "affiliate_content"
    if "task" in mechanism or "marketplace" in mechanism:
        return "public_tasks"
    return "agent_services"


def score_opportunity(data: dict[str, Any]) -> int:
    """Compare upside, speed, capital, reversibility, margin, risk and evidence."""
    upside = min(10_000, int(data.get("expected_revenue_cents", 0)) * 10)
    capital = max(0, 10_000 - min(10_000, int(data.get("required_capital_cents", 0)) * 20))
    speed = max(0, 10_000 - min(10_000, int(data.get("time_to_revenue_days", 30)) * 250))
    downside = max(0, 10_000 - min(10_000, int(data.get("max_downside_cents", 0)) * 30))
    difficulty = max(0, 10_000 - min(10_000, int(data.get("execution_difficulty", 1)) * 1_500))
    legal = max(0, 10_000 - int(data.get("legal_risk_bps", 0)))
    evidence = min(10_000, int(data.get("evidence_strength_bps", 0)))
    confidence = min(10_000, int(data.get("confidence_bps", 0)))
    reversibility = min(10_000, int(data.get("reversibility_bps", 0)))
    margin = min(10_000, int(data.get("margin_bps", 0)))
    return int(
        upside * 0.15
        + capital * 0.10
        + speed * 0.10
        + downside * 0.15
        + difficulty * 0.05
        + legal * 0.15
        + evidence * 0.10
        + confidence * 0.10
        + reversibility * 0.05
        + margin * 0.05
    )


def discover_simulated_opportunities() -> list[dict[str, Any]]:
    return [
        {**item, "stream_type": "public_tasks"} for item in platform_registry.discover()
    ] + [
        {
            "title": "Licensed classroom worksheet asset pack",
            "category": "digital assets",
            "mechanism": "licensed asset pack",
            "hypothesis": "A clearly licensed printable pack can sell to a defined classroom audience.",
            "expected_revenue_cents": 1_200,
            "max_downside_cents": 250,
            "required_capital_cents": 150,
            "time_to_revenue_days": 10,
            "margin_bps": 8_300,
            "confidence_bps": 6_800,
            "evidence_strength_bps": 6_500,
            "reversibility_bps": 8_500,
            "legal_risk_bps": 1_200,
            "source": "simulation",
            "stream_type": "digital_assets",
        },
        {
            "title": "Paid skill/tool API access",
            "category": "software utility",
            "mechanism": "paid access",
            "hypothesis": "A narrow utility endpoint can earn usage fees from approved users.",
            "expected_revenue_cents": 1_500,
            "max_downside_cents": 400,
            "required_capital_cents": 300,
            "time_to_revenue_days": 21,
            "margin_bps": 7_000,
            "confidence_bps": 5_800,
            "evidence_strength_bps": 5_500,
            "reversibility_bps": 7_000,
            "legal_risk_bps": 1_500,
            "source": "simulation",
            "stream_type": "agent_services",
        },
        {
            "title": "Compliant content affiliate referral",
            "category": "content and affiliate",
            "mechanism": "affiliate referral",
            "hypothesis": "Evidence-based content can refer customers to a permitted service with disclosure.",
            "expected_revenue_cents": 800,
            "max_downside_cents": 100,
            "required_capital_cents": 50,
            "time_to_revenue_days": 14,
            "margin_bps": 8_000,
            "confidence_bps": 6_000,
            "evidence_strength_bps": 5_700,
            "reversibility_bps": 9_000,
            "legal_risk_bps": 1_700,
            "source": "simulation",
            "stream_type": "affiliate_content",
        },
        {
            "title": "Marketplace microtask service",
            "category": "online service",
            "mechanism": "marketplace microtask",
            "hypothesis": "A bounded data-cleaning microtask can be delivered for a verified customer.",
            "expected_revenue_cents": 1_000,
            "max_downside_cents": 180,
            "required_capital_cents": 100,
            "time_to_revenue_days": 7,
            "margin_bps": 7_500,
            "confidence_bps": 7_100,
            "evidence_strength_bps": 6_900,
            "reversibility_bps": 8_800,
            "legal_risk_bps": 900,
            "source": "simulation",
            "stream_type": "public_tasks",
        },
        {
            "title": "Optional digital collectible concept",
            "category": "digital collectibles",
            "mechanism": "testnet collectible",
            "hypothesis": "A transparent, non-self-dealing collectible concept can be tested without deployment.",
            "expected_revenue_cents": 700,
            "max_downside_cents": 300,
            "required_capital_cents": 200,
            "time_to_revenue_days": 30,
            "margin_bps": 5_000,
            "confidence_bps": 3_500,
            "evidence_strength_bps": 3_000,
            "reversibility_bps": 5_500,
            "legal_risk_bps": 3_000,
            "source": "simulation",
            "stream_type": "digital_assets",
        },
        {
            "title": "Passive bug-bounty scope triage",
            "category": "security research",
            "mechanism": "bug bounty",
            "hypothesis": "A verified program scope can support passive triage before any owner-authorized testing.",
            "expected_revenue_cents": 500,
            "max_downside_cents": 0,
            "required_capital_cents": 0,
            "time_to_revenue_days": 45,
            "margin_bps": 6_000,
            "confidence_bps": 3_000,
            "evidence_strength_bps": 2_000,
            "reversibility_bps": 9_500,
            "legal_risk_bps": 2_500,
            "source": "simulation",
            "stream_type": "bug_bounty",
        },
    ]


def upsert_opportunities(db: Session, rows: list[dict[str, Any]] | None = None) -> list[Opportunity]:
    rows = rows or discover_simulated_opportunities()
    result: list[Opportunity] = []
    for data in rows:
        if data.get("source") in {None, "simulation", "moltbook-simulation"}:
            data["source"] = "demo-local-fallback"
            data["evidence"] = "DEMO LOCAL ONLY: synthetic fixture; not verified public demand."
        elif data.get("source") != "demo-local-fallback" and not data.get("demand_evidence_id"):
            raise ValueError("live opportunity rows require imported demand evidence")
        existing = db.scalars(select(Opportunity).where(Opportunity.title == data["title"])).first()
        score = score_opportunity(data)
        if existing is None:
            existing = Opportunity(
                title=data["title"],
                category=data["category"],
                stream_type=stream_for(data),
                demand_evidence_id=data.get("demand_evidence_id"),
                mechanism=data.get("mechanism", "service"),
                source=data.get("source", "simulation"),
                hypothesis=data["hypothesis"],
                evidence=data.get("evidence", "simulated evidence"),
                expected_revenue_cents=data.get("expected_revenue_cents", 0),
                max_downside_cents=data.get("max_downside_cents", 0),
                required_capital_cents=data.get("required_capital_cents", 0),
                time_to_revenue_days=data.get("time_to_revenue_days", 30),
                margin_bps=data.get("margin_bps", 0),
                execution_difficulty=data.get("execution_difficulty", 1),
                confidence_bps=data.get("confidence_bps", 0),
                reversibility_bps=data.get("reversibility_bps", 0),
                legal_risk_bps=data.get("legal_risk_bps", 0),
                evidence_strength_bps=data.get("evidence_strength_bps", 0),
                score_bps=score,
            )
            db.add(existing)
        else:
            existing.score_bps = score
            existing.stream_type = stream_for(data)
        result.append(existing)
    db.flush()
    return result


def portfolio_snapshot(db: Session) -> dict[str, Any]:
    """Return stream-level counts and paper economics for dashboard consumers."""

    opportunities = list(db.scalars(select(Opportunity)))
    experiments = list(db.scalars(select(Experiment)))
    streams: dict[str, dict[str, Any]] = {
        stream: {
            "opportunities": 0,
            "experiments": 0,
            "paper_revenue_cents": 0,
            "paper_cost_cents": 0,
            "pipeline_downside_cents": 0,
            "committed_risk_cents": 0,
        }
        for stream in STREAM_TYPES
    }
    for opportunity in opportunities:
        bucket = streams.setdefault(opportunity.stream_type, {"opportunities": 0, "experiments": 0, "paper_revenue_cents": 0, "paper_cost_cents": 0, "pipeline_downside_cents": 0, "committed_risk_cents": 0})
        bucket["opportunities"] += 1
        bucket["pipeline_downside_cents"] += opportunity.max_downside_cents
    for experiment in experiments:
        bucket = streams.setdefault(experiment.stream_type, {"opportunities": 0, "experiments": 0, "paper_revenue_cents": 0, "paper_cost_cents": 0, "pipeline_downside_cents": 0, "committed_risk_cents": 0})
        bucket["experiments"] += 1
        bucket["paper_revenue_cents"] += experiment.revenue_cents
        bucket["paper_cost_cents"] += experiment.expenses_cents
        if experiment.status in {"DRAFT", "REVIEW", "APPROVED", "RUNNING", "PAUSED"}:
            bucket["committed_risk_cents"] += experiment.max_loss_cents
    return {
        "caps_bps": PORTFOLIO_CAPS_BPS,
        "streams": streams,
        "metrics_are_paper_only": True,
        "real_money_enabled": False,
    }
