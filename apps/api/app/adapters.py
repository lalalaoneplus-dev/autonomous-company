from __future__ import annotations

from typing import Any, Protocol


class InertAdapter:
    """Base for real integrations: deliberately cannot make external calls."""

    enabled = False

    def execute(self, **_: Any) -> dict[str, Any]:
        raise RuntimeError("real adapter is disabled; use a mock adapter in simulation mode")


class FiatPaymentAdapter(InertAdapter):
    pass


class CardSpendingAdapter(InertAdapter):
    pass


class CryptoWalletAdapter(InertAdapter):
    pass


class RevenueCollectionAdapter(InertAdapter):
    pass


class SafeSmartAccountAdapter(InertAdapter):
    pass


class MockAdapter:
    enabled = True

    def execute(self, **payload: Any) -> dict[str, Any]:
        return {"simulated": True, "payload": payload}


class ToolAdapter(Protocol):
    def execute(self, **payload: Any) -> dict[str, Any]: ...

