"""Unit tests for auth.py — password hashing, JWT tokens, refresh tokens."""

import time

import pytest

import auth


def test_hash_and_verify_password():
    hashed = auth.hash_password("my-secret-pass")
    assert hashed != "my-secret-pass"
    assert auth.verify_password("my-secret-pass", hashed)


def test_verify_wrong_password():
    hashed = auth.hash_password("correct-pass")
    assert not auth.verify_password("wrong-pass", hashed)


def test_create_and_decode_access_token():
    token = auth.create_access_token("user-123", "test@example.com")
    payload = auth.decode_access_token(token)
    assert payload["sub"] == "user-123"
    assert payload["email"] == "test@example.com"
    assert "exp" in payload


def test_decode_expired_token():
    import jwt as _jwt
    payload = {
        "sub": "user-123",
        "email": "test@example.com",
        "exp": 0,  # epoch = long expired
    }
    token = _jwt.encode(payload, auth.SECRET_KEY, algorithm=auth.ALGORITHM)
    with pytest.raises(_jwt.ExpiredSignatureError):
        auth.decode_access_token(token)


def test_refresh_token_hash_consistency():
    raw, hashed = auth.create_refresh_token()
    assert raw != hashed
    assert auth.hash_refresh_token(raw) == hashed
    # Different tokens produce different hashes
    raw2, hashed2 = auth.create_refresh_token()
    assert hashed != hashed2


def test_refresh_token_expiry_is_future():
    from datetime import datetime, timezone
    exp = auth.refresh_token_expiry()
    exp_dt = datetime.fromisoformat(exp)
    assert exp_dt > datetime.now(timezone.utc)
