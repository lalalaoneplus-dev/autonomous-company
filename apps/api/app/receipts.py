from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from pydantic import BaseModel

from .config import settings


def _payload(receipt: BaseModel | dict[str, Any]) -> bytes:
    data = receipt.model_dump(mode="json") if isinstance(receipt, BaseModel) else dict(receipt)
    data.pop("signature", None)
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def sign_trusted_receipt(receipt: BaseModel | dict[str, Any], secret: str) -> str:
    if len(secret) < 32:
        raise ValueError("trusted receipt secret must contain at least 32 characters")
    return hmac.new(secret.encode(), _payload(receipt), hashlib.sha256).hexdigest()


def verify_trusted_receipt(receipt: BaseModel | dict[str, Any]) -> None:
    secret = settings.trusted_receipt_hmac_secret
    if not secret or len(secret) < 32:
        raise ValueError("trusted external-receipt adapter is not configured")
    supplied = receipt.signature if isinstance(receipt, BaseModel) else str(receipt.get("signature", ""))
    expected = sign_trusted_receipt(receipt, secret)
    if not hmac.compare_digest(supplied, expected):
        raise ValueError("trusted external receipt signature is invalid")
