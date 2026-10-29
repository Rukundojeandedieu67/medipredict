import pytest
from fastapi.testclient import TestClient

from backend.app import database, main
from backend.app.config import settings


def test_dashboard_routes_do_not_connect_to_database(monkeypatch):
    monkeypatch.setattr(settings, "database_enabled", False)
    monkeypatch.setattr(main, "load_rows", lambda: [])

    def fail_if_called(*args, **kwargs):
        pytest.fail("Database access must remain disabled in dashboard-only mode.")

    monkeypatch.setattr(database.Base.metadata, "create_all", fail_if_called)
    monkeypatch.setattr(database.engine, "connect", fail_if_called)

    with TestClient(main.app) as client:
        health = client.get("/api/v1/health")
        summary = client.get("/api/v1/inventory/summary")

    assert health.status_code == 200
    assert summary.status_code == 200
    assert summary.json()["facilities"] == 0


def test_database_backed_routes_report_unavailable_in_dashboard_only_mode(
    monkeypatch,
):
    monkeypatch.setattr(settings, "database_enabled", False)

    with TestClient(main.app) as client:
        response = client.get(
            "/api/v1/data/datasets",
            headers={"X-Admin-API-Key": "local-test-key"},
        )

    assert response.status_code == 503
    assert "MEDIPREDICT_DATABASE_ENABLED=true" in response.json()["detail"]
