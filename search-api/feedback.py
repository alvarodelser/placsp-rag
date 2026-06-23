"""Relevance-feedback persistence (SQLite).

Stores explicit "relevant" judgments on search results for offline retrieval
evaluation. A ``searches`` row snapshots the query + result set as shown (written
lazily on the first like); ``feedback`` rows attach individual likes to it.

See docs/superpowers/specs/2026-06-23-relevance-feedback-capture-design.md.
"""
import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (
  search_id    TEXT PRIMARY KEY,
  session_id   TEXT,
  ts           TEXT,
  query        TEXT,
  mode         TEXT,
  filters_json TEXT,
  results_json TEXT,
  app_version  TEXT
);
CREATE TABLE IF NOT EXISTS feedback (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  search_id    TEXT REFERENCES searches(search_id),
  session_id   TEXT,
  ts           TEXT,
  result_id    TEXT,
  result_rank  INTEGER,
  result_score REAL,
  UNIQUE(search_id, result_id)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def upsert_search(conn, *, search_id, session_id, query, mode, filters,
                  results, app_version, ts=None) -> None:
    """Insert the search snapshot if absent. Idempotent on ``search_id`` —
    the first write wins and is never overwritten."""
    conn.execute(
        "INSERT OR IGNORE INTO searches "
        "(search_id, session_id, ts, query, mode, filters_json, results_json, app_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (search_id, session_id, ts or _now(), query, mode,
         json.dumps(filters), json.dumps(results), app_version),
    )
    conn.commit()


def add_like(conn, *, search_id, session_id, result_id, result_rank,
             result_score, ts=None) -> None:
    """Record a like. Idempotent via UNIQUE(search_id, result_id)."""
    conn.execute(
        "INSERT OR IGNORE INTO feedback "
        "(search_id, session_id, ts, result_id, result_rank, result_score) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (search_id, session_id, ts or _now(), result_id, result_rank, result_score),
    )
    conn.commit()


def remove_like(conn, *, search_id, result_id) -> None:
    conn.execute(
        "DELETE FROM feedback WHERE search_id=? AND result_id=?",
        (search_id, result_id),
    )
    conn.commit()
