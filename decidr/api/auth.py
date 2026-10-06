"""Local accounts for the claim checker: sign up, sign in, sessions and password reset.

Users live in a SQLite file outside git (``data/app/users.db``; override with
``DECIDR_AUTH_DB``).  Passwords are stored as salted scrypt hashes, and session and reset
tokens are stored only as SHA-256 digests.  There is no email service in the prototype, so
a password-reset link is written to the API log instead of being sent.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import logging
import os
from pathlib import Path
import secrets
import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "app" / "users.db"
SESSION_COOKIE = "decidr_session"
SESSION_LIFETIME = timedelta(days=7)
RESET_LIFETIME = timedelta(hours=1)
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
SCRYPT = {"n": 2**14, "r": 8, "p": 1}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reset_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
"""

logger = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/api/auth", tags=["auth"])


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(pattern=EMAIL_PATTERN, max_length=254)
    password: str = Field(min_length=8, max_length=200)


class LoginRequest(BaseModel):
    email: str
    password: str


class ForgotRequest(BaseModel):
    email: str


class ResetRequest(BaseModel):
    token: str
    password: str = Field(min_length=8, max_length=200)


class ProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class PasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


def _db_path() -> Path:
    return Path(os.environ.get("DECIDR_AUTH_DB", DEFAULT_DB_PATH))


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA)
        yield connection
        connection.commit()
    finally:
        connection.close()


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _normalise(email: str) -> str:
    return email.strip().lower()


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode(), salt=salt, **SCRYPT)
    return f"scrypt${salt.hex()}${derived.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, hash_hex = stored.split("$")
        derived = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **SCRYPT)
    except ValueError:
        return False
    return hmac.compare_digest(derived.hex(), hash_hex)


def _public(user: sqlite3.Row) -> dict[str, Any]:
    return {"id": user["id"], "email": user["email"], "name": user["name"]}


def _start_session(connection: sqlite3.Connection, user_id: int, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    connection.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
        (_digest(token), user_id, (_now() + SESSION_LIFETIME).isoformat()),
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        samesite="lax",
    )


def current_user(decidr_session: str | None = Cookie(default=None)) -> dict[str, Any]:
    """Resolve the session cookie to a user, or reject the request."""
    if decidr_session:
        with _connect() as connection:
            user = connection.execute(
                "SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id "
                "WHERE sessions.token_hash = ? AND sessions.expires_at > ?",
                (_digest(decidr_session), _now().isoformat()),
            ).fetchone()
        if user is not None:
            return _public(user)
    raise HTTPException(status_code=401, detail="Not signed in")


CurrentUser = Annotated[dict[str, Any], Depends(current_user)]


@router.post("/signup", status_code=201)
def signup(request: SignupRequest, response: Response) -> dict[str, Any]:
    email = _normalise(request.email)
    with _connect() as connection:
        try:
            cursor = connection.execute(
                "INSERT INTO users (email, name, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (
                    email,
                    request.name.strip(),
                    _hash_password(request.password),
                    _now().isoformat(),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise HTTPException(
                status_code=409, detail="An account with this email already exists"
            ) from error
        _start_session(connection, cursor.lastrowid, response)
        return {"id": cursor.lastrowid, "email": email, "name": request.name.strip()}


@router.post("/login")
def login(request: LoginRequest, response: Response) -> dict[str, Any]:
    with _connect() as connection:
        user = connection.execute(
            "SELECT * FROM users WHERE email = ?", (_normalise(request.email),)
        ).fetchone()
        if user is None or not _verify_password(request.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Incorrect email or password")
        _start_session(connection, user["id"], response)
        return _public(user)


@router.post("/logout", status_code=204)
def logout(response: Response, decidr_session: str | None = Cookie(default=None)) -> None:
    if decidr_session:
        with _connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (_digest(decidr_session),)
            )
    response.delete_cookie(SESSION_COOKIE)


@router.get("/me")
def me(user: CurrentUser) -> dict[str, Any]:
    return user


@router.patch("/me")
def update_profile(request: ProfileRequest, user: CurrentUser) -> dict[str, Any]:
    with _connect() as connection:
        connection.execute(
            "UPDATE users SET name = ? WHERE id = ?", (request.name.strip(), user["id"])
        )
    return {**user, "name": request.name.strip()}


@router.post("/password", status_code=204)
def change_password(request: PasswordRequest, user: CurrentUser) -> None:
    with _connect() as connection:
        stored = connection.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user["id"],)
        ).fetchone()
        if not _verify_password(request.current_password, stored["password_hash"]):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (_hash_password(request.new_password), user["id"]),
        )


@router.post("/forgot")
def forgot_password(request: ForgotRequest, http_request: Request) -> dict[str, str]:
    """Issue a reset link.  The reply is identical whether or not the account exists."""
    email = _normalise(request.email)
    with _connect() as connection:
        user = connection.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if user is not None:
            token = secrets.token_urlsafe(32)
            connection.execute("DELETE FROM reset_tokens WHERE user_id = ?", (user["id"],))
            connection.execute(
                "INSERT INTO reset_tokens (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (_digest(token), user["id"], (_now() + RESET_LIFETIME).isoformat()),
            )
            base = os.environ.get("DECIDR_APP_URL") or http_request.headers.get(
                "origin", "http://localhost:5173"
            )
            # No email service in the prototype: the link goes to the API log instead.
            logger.warning("Password reset link for %s: %s/?reset=%s", email, base, token)
    return {"detail": "If an account exists for that email, a reset link has been issued."}


@router.post("/reset", status_code=204)
def reset_password(request: ResetRequest) -> None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT user_id FROM reset_tokens WHERE token_hash = ? AND expires_at > ?",
            (_digest(request.token), _now().isoformat()),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=400, detail="This reset link is invalid or expired")
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (_hash_password(request.password), row["user_id"]),
        )
        # A reset signs the account out everywhere and the link cannot be reused.
        connection.execute("DELETE FROM reset_tokens WHERE user_id = ?", (row["user_id"],))
        connection.execute("DELETE FROM sessions WHERE user_id = ?", (row["user_id"],))
