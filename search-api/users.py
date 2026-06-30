"""User persistence — SQLite.

Stores user accounts, refresh tokens, saved licitaciones, and behavioural
events.  Follows the same raw ``sqlite3`` pattern as ``feedback.py``:
Row factory, busy_timeout, schema-init on connect.

See docs/auth_explainer.md for the plain-language description.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id         TEXT PRIMARY KEY,
    email           TEXT UNIQUE NOT NULL,
    display_name    TEXT NOT NULL,
    hashed_password TEXT NOT NULL,
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refresh_tokens (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    token_hash      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE(user_id, token_hash)
);

CREATE TABLE IF NOT EXISTS saved_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    item_id         TEXT NOT NULL,
    syndication_id  TEXT,
    title           TEXT,
    saved_at        TEXT NOT NULL,
    removed_at      TEXT,
    UNIQUE(user_id, item_id)
);

CREATE TABLE IF NOT EXISTS user_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    event_type      TEXT NOT NULL,
    item_id         TEXT,
    context_json    TEXT,
    ts              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id         TEXT PRIMARY KEY REFERENCES users(user_id),
    profile_json    TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_items_analysis (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    item_id         TEXT NOT NULL,
    pcap_json       TEXT,
    ppt_json        TEXT,
    match_score     INTEGER,
    blockers_json   TEXT,
    analyzed_at     TEXT NOT NULL,
    UNIQUE(user_id, item_id)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None


# ── Connection ─────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def connect(path: str) -> sqlite3.Connection:
    """Open (or create) the users database at *path*."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=3000")
    init_db(conn)
    return conn


# ── Users ──────────────────────────────────────────────────────────────────

def create_user(conn: sqlite3.Connection, *, email: str, display_name: str,
                hashed_password: str) -> dict:
    """Insert a new user and return its dict.  Raises ``sqlite3.IntegrityError``
    if the email already exists."""
    user_id = str(uuid.uuid4())
    now = _now()
    conn.execute(
        "INSERT INTO users "
        "(user_id, email, display_name, hashed_password, is_active, created_at, last_seen_at) "
        "VALUES (?, ?, ?, ?, 1, ?, ?)",
        (user_id, email.lower().strip(), display_name.strip(), hashed_password, now, now),
    )
    conn.commit()
    return {"user_id": user_id, "email": email.lower().strip(),
            "display_name": display_name.strip(), "created_at": now}


def get_user_by_email(conn: sqlite3.Connection, email: str) -> dict | None:
    """Return user dict or ``None``."""
    row = conn.execute("SELECT * FROM users WHERE email = ?",
                       (email.lower().strip(),)).fetchone()
    return _row_to_dict(row)


def get_user_by_id(conn: sqlite3.Connection, user_id: str) -> dict | None:
    """Return user dict or ``None``."""
    row = conn.execute("SELECT * FROM users WHERE user_id = ?",
                       (user_id,)).fetchone()
    return _row_to_dict(row)


def update_last_seen(conn: sqlite3.Connection, user_id: str) -> None:
    conn.execute("UPDATE users SET last_seen_at = ? WHERE user_id = ?",
                 (_now(), user_id))
    conn.commit()


# ── Refresh tokens ─────────────────────────────────────────────────────────

def store_refresh_token(conn: sqlite3.Connection, *, user_id: str,
                        token_hash: str, expires_at: str) -> None:
    """Persist a hashed refresh token."""
    conn.execute(
        "INSERT OR REPLACE INTO refresh_tokens "
        "(user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
        (user_id, token_hash, expires_at, _now()),
    )
    conn.commit()


def validate_refresh_token(conn: sqlite3.Connection, *, user_id: str,
                           token_hash: str) -> bool:
    """Return ``True`` if the token exists and has not expired."""
    row = conn.execute(
        "SELECT expires_at FROM refresh_tokens "
        "WHERE user_id = ? AND token_hash = ?",
        (user_id, token_hash),
    ).fetchone()
    if not row:
        return False
    return row["expires_at"] > _now()


def delete_user_refresh_tokens(conn: sqlite3.Connection, user_id: str) -> None:
    """Remove all refresh tokens for a user (logout-all)."""
    conn.execute("DELETE FROM refresh_tokens WHERE user_id = ?", (user_id,))
    conn.commit()


# ── Saved items ────────────────────────────────────────────────────────────

def save_item(conn: sqlite3.Connection, *, user_id: str, item_id: str,
              syndication_id: str | None = None,
              title: str | None = None) -> dict:
    """Save (or re-save) a licitación.  If previously soft-deleted, reactivate
    it.  Returns the saved-item dict."""
    now = _now()
    # Try to reactivate a soft-deleted row first.
    cur = conn.execute(
        "UPDATE saved_items SET removed_at = NULL, saved_at = ?, "
        "syndication_id = COALESCE(?, syndication_id), "
        "title = COALESCE(?, title) "
        "WHERE user_id = ? AND item_id = ?",
        (now, syndication_id, title, user_id, item_id),
    )
    if cur.rowcount == 0:
        conn.execute(
            "INSERT OR IGNORE INTO saved_items "
            "(user_id, item_id, syndication_id, title, saved_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, item_id, syndication_id, title, now),
        )
    conn.commit()
    return {"user_id": user_id, "item_id": item_id,
            "syndication_id": syndication_id, "title": title, "saved_at": now}


def unsave_item(conn: sqlite3.Connection, *, user_id: str,
                item_id: str) -> None:
    """Soft-delete a saved item (sets ``removed_at``)."""
    conn.execute(
        "UPDATE saved_items SET removed_at = ? "
        "WHERE user_id = ? AND item_id = ? AND removed_at IS NULL",
        (_now(), user_id, item_id),
    )
    conn.commit()


def list_saved(conn: sqlite3.Connection, user_id: str, *,
               offset: int = 0, limit: int = 50) -> list[dict]:
    """Return active (non-removed) saved items, newest first."""
    rows = conn.execute(
        "SELECT item_id, syndication_id, title, saved_at "
        "FROM saved_items WHERE user_id = ? AND removed_at IS NULL "
        "ORDER BY saved_at DESC LIMIT ? OFFSET ?",
        (user_id, limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def count_saved(conn: sqlite3.Connection, user_id: str) -> int:
    """Count active saved items."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM saved_items "
        "WHERE user_id = ? AND removed_at IS NULL",
        (user_id,),
    ).fetchone()
    return row["n"] if row else 0


def get_saved_ids(conn: sqlite3.Connection, user_id: str) -> list[str]:
    """Return just the ``item_id`` values of active saves (for fast UI state)."""
    rows = conn.execute(
        "SELECT item_id FROM saved_items "
        "WHERE user_id = ? AND removed_at IS NULL",
        (user_id,),
    ).fetchall()
    return [r["item_id"] for r in rows]


# ── Event logging ──────────────────────────────────────────────────────────

def log_event(conn: sqlite3.Connection, *, user_id: str, event_type: str,
              item_id: str | None = None, context: dict | None = None) -> None:
    """Append an immutable behavioural event."""
    conn.execute(
        "INSERT INTO user_events (user_id, event_type, item_id, context_json, ts) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, event_type, item_id,
         json.dumps(context) if context else None, _now()),
    )
    conn.commit()

# ── User Profiles ──────────────────────────────────────────────────────────

def get_user_profile(conn: sqlite3.Connection, user_id: str) -> dict:
    row = conn.execute("SELECT profile_json FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
    if row and row["profile_json"]:
        return json.loads(row["profile_json"])
    return {}

def update_user_profile(conn: sqlite3.Connection, user_id: str, profile: dict) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO user_profiles (user_id, profile_json, updated_at) VALUES (?, ?, ?)",
        (user_id, json.dumps(profile), _now())
    )
    conn.commit()

# ── Saved Items Analysis ───────────────────────────────────────────────────

def save_item_analysis(conn: sqlite3.Connection, *, user_id: str, item_id: str,
                       pcap_json: dict, ppt_json: dict, match_score: int, blockers: list) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO saved_items_analysis "
        "(user_id, item_id, pcap_json, ppt_json, match_score, blockers_json, analyzed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user_id, item_id, json.dumps(pcap_json), json.dumps(ppt_json),
         match_score, json.dumps(blockers), _now())
    )
    conn.commit()

def get_item_analysis(conn: sqlite3.Connection, user_id: str, item_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM saved_items_analysis WHERE user_id = ? AND item_id = ?",
        (user_id, item_id)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["pcap_json"] = json.loads(d["pcap_json"]) if d["pcap_json"] else {}
    d["ppt_json"] = json.loads(d["ppt_json"]) if d["ppt_json"] else {}
    d["blockers_json"] = json.loads(d["blockers_json"]) if d["blockers_json"] else []
    return d
