from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app


def test_catalog_test_returns_productcode_sample() -> None:
    repository = MagicMock()
    repository.check_connection.return_value = True
    repository.fetch_sample_rows.return_value = [
        {
            "productcode": "B1EB5-W",
            "name": "B1EB5-W",
            "description": "BRP 120V WHIP END EXT CBL",
            "description2": "BRP 120V WHIP END EXT CBL",
            "row_id": 333427,
        },
        {
            "productcode": "NA1-2DDDA10-HV",
            "name": "NA1-2DDDA10-HV",
            "description": "HIGH VOLTAGE",
            "description2": "HV CABLE",
        },
    ]
    with (
        patch("app.main.normalized_catalog_source", return_value="postgresql"),
        patch("app.main.postgres_catalog_repository", return_value=repository),
    ):
        response = TestClient(app).get("/api/catalog/test")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["catalog_source"] == "postgresql"
    assert body["database"] == "connected"
    assert body["table"] == "productmaster"
    assert body["count"] == 2
    assert body["products"][0] == {
        "Productcode": "B1EB5-W",
        "name": "B1EB5-W",
        "description": "BRP 120V WHIP END EXT CBL",
        "description2": "BRP 120V WHIP END EXT CBL",
    }
    assert "333427" not in str(body)
    assert body["products"][1]["Productcode"] == "NA1-2DDDA10-HV"
    repository.fetch_sample_rows.assert_called_once_with(limit=5)


def test_catalog_test_returns_numeric_productcode_as_string() -> None:
    repository = MagicMock()
    repository.check_connection.return_value = True
    repository.fetch_sample_rows.return_value = [
        {
            "productcode": 333479,
            "name": "RR 2BA KR",
            "description": "RR 2BA KR",
            "description2": None,
        },
    ]
    with (
        patch("app.main.normalized_catalog_source", return_value="postgresql"),
        patch("app.main.postgres_catalog_repository", return_value=repository),
    ):
        response = TestClient(app).get("/api/catalog/test")
    body = response.json()
    assert body["products"][0]["Productcode"] == "333479"
    assert isinstance(body["products"][0]["Productcode"], str)
    assert "333,479" not in response.text


def test_catalog_test_disconnected() -> None:
    repository = MagicMock()
    repository.check_connection.return_value = False
    with (
        patch("app.main.normalized_catalog_source", return_value="postgresql"),
        patch("app.main.postgres_catalog_repository", return_value=repository),
    ):
        response = TestClient(app).get("/api/catalog/test")
    assert response.status_code == 503
    assert response.json()["database"] == "disconnected"


def test_catalog_test_requires_postgresql() -> None:
    with patch("app.main.normalized_catalog_source", return_value="excel"):
        response = TestClient(app).get("/api/catalog/test")
    assert response.status_code == 400
