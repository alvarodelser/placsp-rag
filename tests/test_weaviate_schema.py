import httpx
from placsp.weaviate_schema import ensure_class, CLASS_DEF

def test_class_def_shape():
    assert CLASS_DEF["class"] == "Placsp_licitaciones"
    assert CLASS_DEF["vectorizer"] == "none"
    names = {p["name"] for p in CLASS_DEF["properties"]}
    assert {"syndication_id", "content", "status_history", "budget_amount", "lots"} <= names

def test_ensure_class_creates_when_missing():
    calls = {"post": 0}
    def handler(req):
        if req.method == "GET":
            return httpx.Response(404, json={})
        calls["post"] += 1
        return httpx.Response(200, json={})
    created = ensure_class("http://wv:8086", "k", "Placsp_licitaciones",
                           transport=httpx.MockTransport(handler))
    assert created is True and calls["post"] == 1

def test_ensure_class_noop_when_present():
    def handler(req):
        return httpx.Response(200, json={"class": "Placsp_licitaciones"})
    created = ensure_class("http://wv:8086", "k", "Placsp_licitaciones",
                           transport=httpx.MockTransport(handler))
    assert created is False
