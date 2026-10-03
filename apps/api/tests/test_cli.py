import json
import sys

from app import cli
from app.config import settings


def test_smoke_uses_disposable_database(tmp_path, monkeypatch, capsys):
    operator_database = tmp_path / "operator.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{operator_database}")
    monkeypatch.setattr(sys, "argv", ["autonomous-company", "smoke"])

    cli.main()

    result = json.loads(capsys.readouterr().out)
    assert result["health"]["status"] == "ok"
    assert result["overview"]["autonomy_level"] == 0
    assert operator_database.exists() is False
