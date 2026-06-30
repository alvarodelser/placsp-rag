"""Authentication utilities — JWT + Argon2 password hashing.

Provides helpers for:
- Password hashing/verification (Argon2 via pwdlib)
- JWT access-token creation/decoding (PyJWT, HS256)
- Refresh-token generation (random + SHA-256 hash for DB storage)
- FastAPI dependency ``get_current_user`` that reads the JWT from an
  ``access_token`` HttpOnly cookie
- Cookie set/clear helpers

Config (env):
  SECRET_KEY              JWT signing key (default for dev only — MUST override)
  ACCESS_TOKEN_MINUTES    access-token lifetime, default 30
  REFRESH_TOKEN_DAYS      refresh-token lifetime, default 30
"""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

# ── Config ──────────────────────────────────────────────────────────────────

SECRET_KEY = os.getenv("SECRET_KEY", "dev-insecure-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "30"))

# ── Password hashing ───────────────────────────────────────────────────────

_hasher = PasswordHash((Argon2Hasher(),))


def hash_password(plain: str) -> str:
    """Return an Argon2id hash of *plain*."""
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return ``True`` if *plain* matches the stored *hashed* value."""
    return _hasher.verify(plain, hashed)


# ── JWT access tokens ──────────────────────────────────────────────────────

def create_access_token(user_id: str, email: str) -> str:
    """Create a short-lived JWT carrying ``sub`` (user_id) and ``email``."""
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT.  Raises ``jwt.ExpiredSignatureError`` or
    ``jwt.InvalidTokenError`` on failure."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


# ── Refresh tokens ─────────────────────────────────────────────────────────

def create_refresh_token() -> tuple[str, str]:
    """Return ``(raw_token, sha256_hex)`` — raw goes to the cookie,
    the hash goes to the database."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    """SHA-256 hex digest of a raw refresh token."""
    return hashlib.sha256(raw.encode()).hexdigest()


def refresh_token_expiry() -> str:
    """ISO-8601 expiry timestamp for a new refresh token."""
    return (datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)).isoformat()


# ── FastAPI dependency ─────────────────────────────────────────────────────

async def get_current_user(request: Request) -> dict:
    """Extract and verify the JWT from the ``access_token`` cookie.

    Returns ``{"user_id": ..., "email": ...}`` on success.
    Raises HTTP 401 if the cookie is missing, expired, or invalid.
    """
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    return {"user_id": payload["sub"], "email": payload.get("email", "")}


# ── Cookie helpers ─────────────────────────────────────────────────────────

# In production behind HTTPS, set secure=True.
_SECURE = os.getenv("AUTH_COOKIE_SECURE", "").lower() in ("1", "true", "yes")


def set_auth_cookies(response, access_token: str, refresh_token: str) -> None:
    """Set ``access_token`` and ``refresh_token`` as HttpOnly cookies."""
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=_SECURE,
        samesite="lax",
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=_SECURE,
        samesite="lax",
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/",
    )


def clear_auth_cookies(response) -> None:
    """Delete both auth cookies."""
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")
