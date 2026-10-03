from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class OpportunitySource(Protocol):
    name: str

    def discover(self) -> list[dict[str, Any]]: ...


class CommercePlatform(Protocol):
    name: str

    def post(self, content: str) -> dict[str, Any]: ...

    def message(self, recipient: str, content: str) -> dict[str, Any]: ...

    def create_offer(self, title: str, price_cents: int) -> dict[str, Any]: ...


class DisabledMoltbookAdapter:
    """Live Moltbook integration point; intentionally has no network behavior."""

    name = "moltbook-live"
    enabled = False

    def discover(self) -> list[dict[str, Any]]:
        return []

    def post(self, content: str) -> dict[str, Any]:
        raise RuntimeError("live Moltbook adapter is disabled")

    def message(self, recipient: str, content: str) -> dict[str, Any]:
        raise RuntimeError("live Moltbook adapter is disabled")

    def create_offer(self, title: str, price_cents: int) -> dict[str, Any]:
        raise RuntimeError("live Moltbook adapter is disabled")


@dataclass
class MockMoltbookAdapter:
    name: str = "moltbook-simulation"
    records: list[dict[str, Any]] = field(default_factory=list)

    def discover(self) -> list[dict[str, Any]]:
        return [
            {
                "title": "Agent-to-agent invoice reconciliation bounty",
                "category": "agent-to-agent services",
                "mechanism": "bounty",
                "hypothesis": "A bounded reconciliation report can earn a small legitimate bounty.",
                "expected_revenue_cents": 900,
                "max_downside_cents": 150,
                "required_capital_cents": 100,
                "time_to_revenue_days": 5,
                "margin_bps": 7800,
                "confidence_bps": 7600,
                "evidence_strength_bps": 7000,
                "reversibility_bps": 9000,
                "legal_risk_bps": 500,
                "source": self.name,
            }
        ]

    def _record(self, kind: str, **payload: Any) -> dict[str, Any]:
        record = {"kind": kind, **payload}
        self.records.append(record)
        return {"simulated": True, **record}

    def post(self, content: str) -> dict[str, Any]:
        return self._record("post", content=content)

    def message(self, recipient: str, content: str) -> dict[str, Any]:
        return self._record("message", recipient=recipient, content=content)

    def create_offer(self, title: str, price_cents: int) -> dict[str, Any]:
        return self._record("offer", title=title, price_cents=price_cents)

    def create_order(self, offer_id: str, buyer: str) -> dict[str, Any]:
        return self._record("order", offer_id=offer_id, buyer=buyer)

    def deliver(self, order_id: str, artifact: str) -> dict[str, Any]:
        return self._record("delivery", order_id=order_id, artifact=artifact)

    def accept(self, order_id: str) -> dict[str, Any]:
        return self._record("acceptance", order_id=order_id)

    def reputation(self, counterparty: str) -> dict[str, Any]:
        return self._record("reputation", counterparty=counterparty, score=100)


@dataclass
class SimulatedPlatformRegistry:
    adapters: list[OpportunitySource] = field(default_factory=list)

    def register_defaults(self) -> None:
        if not self.adapters:
            self.adapters.append(MockMoltbookAdapter())

    def discover(self) -> list[dict[str, Any]]:
        self.register_defaults()
        discoveries: list[dict[str, Any]] = []
        for adapter in self.adapters:
            discoveries.extend(adapter.discover())
        return discoveries


platform_registry = SimulatedPlatformRegistry()

