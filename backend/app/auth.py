import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
from typing import Callable

from sqlalchemy.orm import Session

from .config import settings
from .models.entities import AuthSession, AuthUser

SESSION_COOKIE = "medipredict_session"
SESSION_TTL_SECONDS = 8 * 60 * 60
PASSWORD_HASH_ITERATIONS = 600_000
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 15 * 60


@dataclass(frozen=True)
class AuthPrincipal:
    id: str
    email: str
    role: str
    session_id: str
    csrf_token: str


def auth_is_configured() -> bool:
    return bool(
        settings.database_enabled
        and settings.auth_secret_key
        and len(settings.auth_secret_key) >= 32
    )


def normalize_email(email: str) -> str:
    normalized = email.strip().casefold()
    if (
        len(normalized) > 254
        or normalized.count("@") != 1
        or normalized.startswith("@")
        or normalized.endswith("@")
        or "." not in normalized.rsplit("@", 1)[-1]
    ):
        raise ValueError("Enter a valid email address.")
    return normalized


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
    )
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_HASH_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        algorithm, rounds, salt_text, digest_text = encoded_hash.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
        expected = base64.urlsafe_b64decode(
            digest_text + "=" * (-len(digest_text) % 4)
        )
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(rounds)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_session(user: AuthUser, db: Session) -> tuple[str, str, AuthSession]:
    if not auth_is_configured():
        raise RuntimeError("Authentication is not configured.")
    csrf_token = secrets.token_urlsafe(32)
    session_id = secrets.token_hex(18)
    expires_at = datetime.now(timezone.utc).timestamp() + SESSION_TTL_SECONDS
    payload = _b64encode(
        json.dumps(
            {
                "sub": user.id,
                "sid": session_id,
                "exp": int(expires_at),
                "csrf": csrf_token,
            },
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signature = hmac.new(
        settings.auth_secret_key.encode("utf-8"), payload.encode("ascii"), hashlib.sha256
    ).digest()
    session = AuthSession(
        id=session_id,
        user_id=user.id,
        expires_at=datetime.fromtimestamp(expires_at, timezone.utc),
    )
    db.add(session)
    db.flush()
    return f"{payload}.{_b64encode(signature)}", csrf_token, session


def authenticate_session(
    token: str | None,
    session_factory: Callable[[], Session],
) -> AuthPrincipal | None:
    if not token or not auth_is_configured():
        return None
    try:
        payload, signature_text = token.split(".", 1)
        supplied_signature = _b64decode(signature_text)
        expected_signature = hmac.new(
            settings.auth_secret_key.encode("utf-8"),
            payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        data = json.loads(_b64decode(payload))
        user_id = data["sub"]
        session_id = data["sid"]
        csrf_token = data["csrf"]
        expires_at = int(data["exp"])
        if (
            not isinstance(user_id, str)
            or not isinstance(session_id, str)
            or not isinstance(csrf_token, str)
            or expires_at <= int(datetime.now(timezone.utc).timestamp())
        ):
            return None
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None

    with session_factory() as db:
        user = db.get(AuthUser, user_id)
        session = db.get(AuthSession, session_id)
        if (
            user is None
            or not user.is_active
            or session is None
            or session.user_id != user.id
            or session.revoked_at is not None
        ):
            return None
        session_expiry = session.expires_at
        if session_expiry.tzinfo is None:
            session_expiry = session_expiry.replace(tzinfo=timezone.utc)
        if session_expiry <= datetime.now(timezone.utc):
            return None
        return AuthPrincipal(
            user.id, user.email, user.role, session.id, csrf_token
        )


def ensure_initial_admin(session_factory: Callable[[], Session]) -> None:
    email = settings.auth_initial_admin_email
    password = settings.auth_initial_admin_password
    if not email and not password:
        return
    if not email or not password:
        raise RuntimeError(
            "Set both MEDIPREDICT_AUTH_INITIAL_ADMIN_EMAIL and "
            "MEDIPREDICT_AUTH_INITIAL_ADMIN_PASSWORD to bootstrap the first admin."
        )
    if len(password) < 12:
        raise RuntimeError("The initial admin password must be at least 12 characters.")
    normalized_email = normalize_email(email)
    with session_factory() as db:
        existing = db.query(AuthUser).filter_by(email=normalized_email).first()
        if existing is not None:
            if existing.role != "admin":
                raise RuntimeError(
                    "The configured initial admin email already belongs to a "
                    "non-admin account; refusing to promote it automatically."
                )
            return
        db.add(
            AuthUser(
                id=secrets.token_hex(18),
                email=normalized_email,
                password_hash=hash_password(password),
                role="admin",
            )
        )
        db.commit()


def ensure_demo_user(session_factory: Callable[[], Session]) -> None:
    email = settings.auth_demo_email
    password = settings.auth_demo_password
    if not email and not password:
        return
    if not email or not password:
        raise RuntimeError(
            "Set both MEDIPREDICT_AUTH_DEMO_EMAIL and "
            "MEDIPREDICT_AUTH_DEMO_PASSWORD to enable the demo account."
        )
    if len(password) < 12:
        raise RuntimeError("The demo password must be at least 12 characters.")
    normalized_email = normalize_email(email)
    with session_factory() as db:
        existing = db.query(AuthUser).filter_by(email=normalized_email).first()
        if existing is not None:
            if existing.role != "demo":
                raise RuntimeError(
                    "The configured demo email already belongs to a non-demo "
                    "account; refusing to change its role or password."
                )
            return
        db.add(
            AuthUser(
                id=secrets.token_hex(18),
                email=normalized_email,
                password_hash=hash_password(password),
                role="demo",
            )
        )
        db.commit()
