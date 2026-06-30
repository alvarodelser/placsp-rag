"""Unit tests for users.py — SQLite persistence for users, saved items, events."""

import sqlite3

import pytest

import users


@pytest.fixture
def conn():
    """In-memory SQLite database for isolated tests."""
    c = users.connect(":memory:")
    yield c
    c.close()


# ── Users ──────────────────────────────────────────────────────────────────

def test_create_user(conn):
    u = users.create_user(conn, email="a@b.com", display_name="Álvaro",
                          hashed_password="$hash$")
    assert u["email"] == "a@b.com"
    assert u["display_name"] == "Álvaro"
    assert u["user_id"]  # UUID string


def test_duplicate_email(conn):
    users.create_user(conn, email="dup@b.com", display_name="A",
                      hashed_password="h")
    with pytest.raises(sqlite3.IntegrityError):
        users.create_user(conn, email="dup@b.com", display_name="B",
                          hashed_password="h")


def test_email_case_insensitive(conn):
    users.create_user(conn, email="Test@B.COM", display_name="A",
                      hashed_password="h")
    found = users.get_user_by_email(conn, "test@b.com")
    assert found is not None
    assert found["email"] == "test@b.com"


def test_get_user_by_email(conn):
    users.create_user(conn, email="find@me.com", display_name="F",
                      hashed_password="h")
    assert users.get_user_by_email(conn, "find@me.com") is not None
    assert users.get_user_by_email(conn, "nope@me.com") is None


def test_get_user_by_id(conn):
    u = users.create_user(conn, email="id@b.com", display_name="I",
                          hashed_password="h")
    found = users.get_user_by_id(conn, u["user_id"])
    assert found is not None
    assert found["email"] == "id@b.com"


def test_update_last_seen(conn):
    u = users.create_user(conn, email="ls@b.com", display_name="L",
                          hashed_password="h")
    old = users.get_user_by_id(conn, u["user_id"])["last_seen_at"]
    users.update_last_seen(conn, u["user_id"])
    new = users.get_user_by_id(conn, u["user_id"])["last_seen_at"]
    assert new >= old


# ── Saved items ────────────────────────────────────────────────────────────

def test_save_and_list(conn):
    u = users.create_user(conn, email="s@b.com", display_name="S",
                          hashed_password="h")
    users.save_item(conn, user_id=u["user_id"], item_id="it1",
                    syndication_id="SYN-1", title="Contract A")
    users.save_item(conn, user_id=u["user_id"], item_id="it2",
                    title="Contract B")
    items = users.list_saved(conn, u["user_id"])
    assert len(items) == 2
    assert users.count_saved(conn, u["user_id"]) == 2


def test_unsave_soft_delete(conn):
    u = users.create_user(conn, email="sd@b.com", display_name="S",
                          hashed_password="h")
    users.save_item(conn, user_id=u["user_id"], item_id="rm1", title="Gone")
    users.unsave_item(conn, user_id=u["user_id"], item_id="rm1")
    items = users.list_saved(conn, u["user_id"])
    assert len(items) == 0
    assert users.count_saved(conn, u["user_id"]) == 0
    # But the row still exists in DB (soft-delete)
    row = conn.execute(
        "SELECT removed_at FROM saved_items WHERE item_id='rm1'"
    ).fetchone()
    assert row is not None
    assert row["removed_at"] is not None


def test_resave_after_unsave(conn):
    u = users.create_user(conn, email="rs@b.com", display_name="R",
                          hashed_password="h")
    users.save_item(conn, user_id=u["user_id"], item_id="re1", title="A")
    users.unsave_item(conn, user_id=u["user_id"], item_id="re1")
    assert users.count_saved(conn, u["user_id"]) == 0
    # Re-save reactivates the row
    users.save_item(conn, user_id=u["user_id"], item_id="re1", title="A v2")
    assert users.count_saved(conn, u["user_id"]) == 1


def test_get_saved_ids(conn):
    u = users.create_user(conn, email="ids@b.com", display_name="I",
                          hashed_password="h")
    users.save_item(conn, user_id=u["user_id"], item_id="a")
    users.save_item(conn, user_id=u["user_id"], item_id="b")
    users.save_item(conn, user_id=u["user_id"], item_id="c")
    users.unsave_item(conn, user_id=u["user_id"], item_id="b")
    ids = users.get_saved_ids(conn, u["user_id"])
    assert set(ids) == {"a", "c"}


# ── Events ─────────────────────────────────────────────────────────────────

def test_log_event(conn):
    u = users.create_user(conn, email="ev@b.com", display_name="E",
                          hashed_password="h")
    users.log_event(conn, user_id=u["user_id"], event_type="save",
                    item_id="x1")
    users.log_event(conn, user_id=u["user_id"], event_type="search",
                    context={"query": "limpieza"})
    rows = conn.execute(
        "SELECT * FROM user_events WHERE user_id=?", (u["user_id"],)
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["event_type"] == "save"
    assert rows[1]["event_type"] == "search"


# ── Refresh tokens ─────────────────────────────────────────────────────────

def test_refresh_token_lifecycle(conn):
    from datetime import datetime, timedelta, timezone
    u = users.create_user(conn, email="rt@b.com", display_name="R",
                          hashed_password="h")
    future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    users.store_refresh_token(conn, user_id=u["user_id"],
                              token_hash="hash123", expires_at=future)
    assert users.validate_refresh_token(conn, user_id=u["user_id"],
                                        token_hash="hash123")
    assert not users.validate_refresh_token(conn, user_id=u["user_id"],
                                            token_hash="wrong")
    users.delete_user_refresh_tokens(conn, u["user_id"])
    assert not users.validate_refresh_token(conn, user_id=u["user_id"],
                                            token_hash="hash123")


def test_refresh_token_expired(conn):
    u = users.create_user(conn, email="re@b.com", display_name="E",
                          hashed_password="h")
    past = "2020-01-01T00:00:00+00:00"
    users.store_refresh_token(conn, user_id=u["user_id"],
                              token_hash="old", expires_at=past)
    assert not users.validate_refresh_token(conn, user_id=u["user_id"],
                                            token_hash="old")
