import json

import pytest

import feedback as fb


@pytest.fixture
def conn():
    c = fb.connect(":memory:")
    yield c
    c.close()


SEARCH = dict(
    search_id="s1",
    session_id="sess1",
    query="obras",
    mode="hybrid",
    filters={"cpv": ["45"]},
    results=[{"id": "a", "rank": 0, "score": 0.9}, {"id": "b", "rank": 1, "score": 0.8}],
    app_version="abc123",
)


def test_connect_creates_tables(conn):
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"searches", "feedback"} <= names


def test_upsert_search_inserts_row(conn):
    fb.upsert_search(conn, **SEARCH)
    row = conn.execute("SELECT * FROM searches WHERE search_id='s1'").fetchone()
    assert row["query"] == "obras"
    assert row["mode"] == "hybrid"
    assert row["app_version"] == "abc123"
    assert json.loads(row["filters_json"]) == {"cpv": ["45"]}
    assert json.loads(row["results_json"])[1]["id"] == "b"
    assert row["ts"]


def test_upsert_search_is_idempotent_and_does_not_overwrite(conn):
    fb.upsert_search(conn, **SEARCH)
    changed = {**SEARCH, "query": "DIFFERENT", "app_version": "zzz"}
    fb.upsert_search(conn, **changed)
    rows = conn.execute("SELECT * FROM searches WHERE search_id='s1'").fetchall()
    assert len(rows) == 1
    assert rows[0]["query"] == "obras"  # first write wins
    assert rows[0]["app_version"] == "abc123"


def test_add_like_inserts_feedback_row(conn):
    fb.upsert_search(conn, **SEARCH)
    fb.add_like(conn, search_id="s1", session_id="sess1",
                result_id="a", result_rank=0, result_score=0.9)
    row = conn.execute("SELECT * FROM feedback WHERE result_id='a'").fetchone()
    assert row["search_id"] == "s1"
    assert row["result_rank"] == 0
    assert row["result_score"] == pytest.approx(0.9)
    assert row["ts"]


def test_add_like_is_idempotent_on_search_and_result(conn):
    fb.upsert_search(conn, **SEARCH)
    for _ in range(2):
        fb.add_like(conn, search_id="s1", session_id="sess1",
                    result_id="a", result_rank=0, result_score=0.9)
    rows = conn.execute("SELECT * FROM feedback WHERE search_id='s1'").fetchall()
    assert len(rows) == 1


def test_remove_like_deletes_row(conn):
    fb.upsert_search(conn, **SEARCH)
    fb.add_like(conn, search_id="s1", session_id="sess1",
                result_id="a", result_rank=0, result_score=0.9)
    fb.remove_like(conn, search_id="s1", result_id="a")
    rows = conn.execute("SELECT * FROM feedback WHERE search_id='s1'").fetchall()
    assert rows == []
