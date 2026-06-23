import importlib

import pytest
from fastapi.testclient import TestClient

import feedback as fb


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = str(tmp_path / "fb.db")
    monkeypatch.setenv("FEEDBACK_DB", db)
    monkeypatch.setenv("APP_VERSION", "testver")
    import search_api
    importlib.reload(search_api)
    return TestClient(search_api.app), db


PAYLOAD = {
    "search_id": "s1",
    "session_id": "sess1",
    "query": "obras",
    "mode": "hybrid",
    "filters": {"cpv": ["45"]},
    "results": [
        {"id": "a", "rank": 0, "score": 0.9},
        {"id": "b", "rank": 1, "score": 0.8},
    ],
    "result_id": "b",
}


def test_post_feedback_creates_search_and_like(env):
    client, db = env
    r = client.post("/api/feedback", json=PAYLOAD)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "app_version": "testver"}

    conn = fb.connect(db)
    s = conn.execute("SELECT * FROM searches WHERE search_id='s1'").fetchone()
    assert s["query"] == "obras"
    assert s["app_version"] == "testver"
    f = conn.execute("SELECT * FROM feedback WHERE search_id='s1'").fetchone()
    assert f["result_id"] == "b"
    assert f["result_rank"] == 1          # derived from the results snapshot
    assert f["result_score"] == pytest.approx(0.8)
    conn.close()


def test_post_feedback_is_idempotent(env):
    client, db = env
    client.post("/api/feedback", json=PAYLOAD)
    client.post("/api/feedback", json=PAYLOAD)
    conn = fb.connect(db)
    assert conn.execute("SELECT COUNT(*) c FROM searches").fetchone()["c"] == 1
    assert conn.execute("SELECT COUNT(*) c FROM feedback").fetchone()["c"] == 1
    conn.close()


def test_delete_feedback_removes_like(env):
    client, db = env
    client.post("/api/feedback", json=PAYLOAD)
    r = client.request("DELETE", "/api/feedback",
                       json={"search_id": "s1", "result_id": "b"})
    assert r.status_code == 200
    conn = fb.connect(db)
    assert conn.execute("SELECT COUNT(*) c FROM feedback").fetchone()["c"] == 0
    conn.close()
