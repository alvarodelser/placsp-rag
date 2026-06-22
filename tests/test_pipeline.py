import httpx, json
from placsp.pipeline import collapse, Pipeline
from placsp.atom_parser import parse_feed
from placsp.embedder import Embedder
from placsp.upserter import Upserter
from placsp.config import load_config
from datetime import datetime

def test_collapse_keeps_latest_and_merges_history():
    from placsp.models import RawEntry, StatusEvent
    # two versions of same id, different status + updated
    class E: pass
    items = list(parse_feed("tests/fixtures/externos.atom", "externos_mayores"))
    recs, tombs = collapse(items, None)
    # one syndication_id per record
    assert all(sid == r.syndication_id for sid, r in recs.items())
    assert len(tombs) == 1

def test_process_files_end_to_end_mocked():
    def vec_handler(req):
        body = json.loads(req.content)
        return httpx.Response(200, json={"embeddings": [[0.0]*4 for _ in body["texts"]]})
    posted = {"n": 0, "deleted": 0}
    def wv_handler(req):
        if req.method == "POST":
            posted["n"] += len(json.loads(req.content)["objects"]); return httpx.Response(200, json=[])
        if req.method == "DELETE":
            posted["deleted"] += 1; return httpx.Response(204)
        return httpx.Response(404)
    cfg = load_config()
    emb = Embedder(cfg.vectorizer_url, transport=httpx.MockTransport(vec_handler))
    up = Upserter(cfg.weaviate_url, "", cfg.weaviate_class, transport=httpx.MockTransport(wv_handler))
    p = Pipeline(cfg, emb, up, None)
    stats = p.process_files(["tests/fixtures/externos.atom"], "externos_mayores")
    assert stats["upserted"] == posted["n"] > 0
    assert stats["deleted"] == 1

def test_is_offpeak():
    cfg = load_config()
    p = Pipeline(cfg, None, None, None)
    # default window 22..7
    assert p.is_offpeak(datetime(2026,1,1,23,0)) is True
    assert p.is_offpeak(datetime(2026,1,1,12,0)) is False
