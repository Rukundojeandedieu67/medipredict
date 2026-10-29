from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import database, main
from backend.app.config import settings
from backend.app.models import AuthUser


ADMIN_EMAIL = "admin@example.org"
ADMIN_PASSWORD = "correct horse battery staple"


def _client(monkeypatch, tmp_path):
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
    monkeypatch.setattr(settings, "auth_initial_admin_email", ADMIN_EMAIL)
    monkeypatch.setattr(settings, "auth_initial_admin_password", ADMIN_PASSWORD)
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    return TestClient(main.app), test_engine, test_session


def test_login_is_required_admin_can_create_users_and_logout_revokes_session(
    monkeypatch, tmp_path
):
    client, test_engine, test_session = _client(monkeypatch, tmp_path)
    try:
        with client:
            assert client.get("/api/v1/inventory/summary").status_code == 401
            login = client.post(
                "/api/v1/auth/login",
                json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            )
            assert login.status_code == 200
            assert login.headers["set-cookie"].lower().find("httponly") >= 0
            session = login.json()
            csrf_header = {"X-CSRF-Token": session["csrf_token"]}

            created = client.post(
                "/api/v1/auth/users",
                json={
                    "email": "new.user@example.org",
                    "password": "a sufficiently long password",
                    "role": "admin",
                },
                headers=csrf_header,
            )
            assert created.status_code == 201
            assert created.json()["role"] == "user"

            assert client.post(
                "/api/v1/auth/users",
                json={
                    "email": "another.user@example.org",
                    "password": "a sufficiently long password",
                },
            ).status_code == 403

            assert client.post(
                "/api/v1/auth/logout", headers=csrf_header
            ).status_code == 200
            assert client.get("/api/v1/auth/me").status_code == 401

        with TestClient(main.app) as user_client:
            user_login = user_client.post(
                "/api/v1/auth/login",
                json={
                    "email": "new.user@example.org",
                    "password": "a sufficiently long password",
                },
            )
            assert user_login.status_code == 200
            assert user_login.json()["user"]["role"] == "user"
            user_csrf = {"X-CSRF-Token": user_login.json()["csrf_token"]}
            forbidden = user_client.post(
                "/api/v1/auth/users",
                json={
                    "email": "other@example.org",
                    "password": "a sufficiently long password",
                },
                headers=user_csrf,
            )
            assert forbidden.status_code == 403
    finally:
        test_engine.dispose()


def test_login_rejects_bad_credentials_and_csrf_is_required(monkeypatch, tmp_path):
    client, test_engine, test_session = _client(monkeypatch, tmp_path)
    try:
        with client:
            wrong_password = client.post(
                "/api/v1/auth/login",
                json={"email": ADMIN_EMAIL, "password": "incorrect password"},
            )
            assert wrong_password.status_code == 401

            login = client.post(
                "/api/v1/auth/login",
                json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            )
            assert login.status_code == 200
            no_csrf = client.post("/api/v1/auth/logout")
            assert no_csrf.status_code == 403

            with test_session() as db:
                admin = db.query(AuthUser).filter_by(email=ADMIN_EMAIL).one()
                assert admin.role == "admin"
    finally:
        test_engine.dispose()
