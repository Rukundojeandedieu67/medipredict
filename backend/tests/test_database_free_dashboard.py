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
    assert summary.status_code == 503
    assert "MEDIPREDICT_DATABASE_ENABLED=true" in summary.json()["detail"]


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


def test_startup_logs_local_providers_without_secrets(monkeypatch, caplog):
    monkeypatch.setattr(settings, "database_enabled", False)
    monkeypatch.setattr(settings, "storage_backend", "local")

    with TestClient(main.app):
        pass

    assert "Aiven PostgreSQL is not configured" in caplog.text
    assert "Database-backed features are disabled" in caplog.text
    assert "Using local file storage; Cloudflare R2 is not configured" in caplog.text
    assert "MEDIPREDICT_DATABASE_ENABLED=true" in caplog.text


def test_startup_logs_missing_cloudflare_settings_by_name(monkeypatch, caplog):
    monkeypatch.setattr(settings, "database_enabled", False)
    monkeypatch.setattr(settings, "storage_backend", "s3")
    monkeypatch.setattr(settings, "object_store_bucket", None)
    monkeypatch.setattr(settings, "object_store_endpoint_url", None)
    monkeypatch.setattr(settings, "object_store_access_key_id", None)
    monkeypatch.setattr(settings, "object_store_secret_access_key", None)
    monkeypatch.setattr(settings, "dashboard_data_key", None)

    with TestClient(main.app):
        pass

    assert "Cloudflare R2 is selected but configuration is incomplete" in caplog.text
    for setting in (
        "MEDIPREDICT_OBJECT_STORE_BUCKET",
        "MEDIPREDICT_OBJECT_STORE_ENDPOINT_URL",
        "MEDIPREDICT_OBJECT_STORE_ACCESS_KEY_ID",
        "MEDIPREDICT_OBJECT_STORE_SECRET_ACCESS_KEY",
        "MEDIPREDICT_DASHBOARD_DATA_KEY",
    ):
        assert setting in caplog.text
