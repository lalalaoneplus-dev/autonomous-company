from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db as db_module
from app.config import settings
from app.main import _alembic_heads, app


API_ROOT = Path(__file__).parents[1]


def _migrate(database: Path, revision: str = "head") -> None:
    settings.database_url = f"sqlite:///{database}"
    db_module.configure_database(settings.database_url)
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    command.upgrade(config, revision)


def test_readiness_checks_current_schema_and_configured_redis(tmp_path, monkeypatch):
    _migrate(tmp_path / "current.db")
    with TestClient(app) as client:
        direct = client.get("/ready")
        assert direct.status_code == 200
        assert direct.json() == {
            "status": "ready",
            "dependencies": {"database": "ok", "redis": "disabled"},
            "schema_revision": _alembic_heads()[0],
        }

        monkeypatch.setattr(settings, "queue_mode", "redis")
        monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
        unavailable = client.get("/ready")
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"] == "redis unavailable"


def test_readiness_rejects_empty_and_stale_schema(tmp_path):
    empty = tmp_path / "empty.db"
    settings.database_url = f"sqlite:///{empty}"
    db_module.configure_database(settings.database_url)
    with TestClient(app) as client:
        assert client.get("/ready").status_code == 503

    stale = tmp_path / "stale.db"
    _migrate(stale)
    assert db_module.engine is not None
    with db_module.engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'stale'"))
    with TestClient(app) as client:
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["detail"] == "database schema unavailable"
