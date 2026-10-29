import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import database, main
from backend.app.config import settings


@pytest.fixture
def admin_client(tmp_path, monkeypatch):
    test_engine = create_engine(
        f"sqlite:///{(tmp_path / 'auth.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    database.Base.metadata.create_all(test_engine)
    test_session = sessionmaker(
        bind=test_engine, autoflush=False, expire_on_commit=False
    )
    monkeypatch.setattr(main, "engine", test_engine)
    monkeypatch.setattr(main, "SessionLocal", test_session)
    monkeypatch.setattr(database, "SessionLocal", test_session)
    monkeypatch.setattr(settings, "database_enabled", True)
    monkeypatch.setattr(settings, "auth_secret_key", "test-session-secret-key-32-chars")
    monkeypatch.setattr(settings, "auth_initial_admin_email", "admin@example.org")
    monkeypatch.setattr(
        settings,
        "auth_initial_admin_password",
        "correct horse battery staple",
    )
    monkeypatch.setattr(settings, "auth_cookie_secure", False)

    with TestClient(main.app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={
                "email": "admin@example.org",
                "password": "correct horse battery staple",
            },
        )
        assert login.status_code == 200
        yield client, {"X-CSRF-Token": login.json()["csrf_token"]}

    test_engine.dispose()
