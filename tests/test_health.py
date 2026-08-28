from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app, get_settings


def test_health_postgresql_connected() -> None:
    settings = get_settings()
    with (
        patch("app.main.normalized_catalog_source", return_value="postgresql"),
        patch("app.main._database_status", return_value="connected"),
        patch("app.main.get_settings", return_value=settings),
    ):
        client = TestClient(app)
        response = client.get("/health")
    assert settings.ai_matching_enabled is False
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "catalog_source": "postgresql",
        "database": "connected",
        "ai_matching_enabled": "false",
    }


def test_health_postgresql_disconnected() -> None:
    with (
        patch("app.main.normalized_catalog_source", return_value="postgresql"),
        patch("app.main._database_status", return_value="disconnected"),
    ):
        client = TestClient(app)
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["database"] == "disconnected"
    assert response.json()["status"] == "error"


def test_database_status_uses_repository_check() -> None:
    from app.main import _database_status

    repository = MagicMock()
    repository.check_connection.return_value = True
    with patch("app.main.postgres_catalog_repository", return_value=repository):
        assert _database_status("postgresql") == "connected"
        assert _database_status("excel") == "not_required"
