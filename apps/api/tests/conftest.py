from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app import db as db_module
from app.config import settings
from app.db import create_schema, configure_database


@pytest.fixture(autouse=True)
def configured_owner_token():
    previous = settings.owner_token
    previous_receipt_secret = settings.trusted_receipt_hmac_secret
    settings.owner_token = "test-owner"
    settings.trusted_receipt_hmac_secret = "test-trusted-receipt-secret-32-characters"
    yield
    settings.owner_token = previous
    settings.trusted_receipt_hmac_secret = previous_receipt_secret


@pytest.fixture()
def db(tmp_path) -> Iterator[Session]:
    configure_database(f"sqlite:///{tmp_path / 'test.db'}")
    create_schema()
    assert db_module.SessionLocal is not None
    with db_module.SessionLocal() as session:
        yield session
