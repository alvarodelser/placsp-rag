import importlib

import pytest
from fastapi.testclient import TestClient

import users


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = str(tmp_path / "users.db")
    monkeypatch.setenv("USERS_DB", db)
    monkeypatch.setenv("FEEDBACK_DB", str(tmp_path / "fb.db"))
    monkeypatch.delenv("AUTH_REQUIRED", raising=False)
    import search_api
    importlib.reload(search_api)
    return TestClient(search_api.app), db


NEW = {"email": "Ana@Ejemplo.es", "password": "contraseña-larga", "display_name": "Ana"}


def test_only_allowed_emails_register(env):
    client, db = env
    assert client.post("/api/auth/register", json=NEW).status_code == 403
    users.allow_email(users.connect(db), "ana@ejemplo.es")
    r = client.post("/api/auth/register", json=NEW)
    assert r.status_code == 200 and r.json()["email"] == "ana@ejemplo.es"


def test_the_whole_api_needs_a_signed_in_user(env):
    client, db = env
    assert client.get("/api/health").status_code != 401
    for path in ("/api/search?q=obras", "/api/facets", "/api/pilot/overview", "/api/graph/neighbors?id=x", "/api/users/me/saved/ids"):
        assert client.get(path).status_code == 401, path
    users.allow_email(users.connect(db), "ana@ejemplo.es")
    client.post("/api/auth/register", json=NEW)                    # sets the cookies
    assert client.get("/api/users/me/saved/ids").status_code == 200


def test_an_email_taken_off_the_list_cannot_sign_in(env):
    client, db = env
    conn = users.connect(db)
    users.allow_email(conn, "ana@ejemplo.es")
    client.post("/api/auth/register", json=NEW)
    client.cookies.clear()
    login = {"username": "ana@ejemplo.es", "password": NEW["password"]}
    assert client.post("/api/auth/login", data=login).status_code == 200
    assert users.disallow_email(conn, "ana@ejemplo.es")
    client.cookies.clear()
    assert client.post("/api/auth/login", data=login).status_code == 403
