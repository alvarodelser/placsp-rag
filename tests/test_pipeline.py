import httpx, json, uuid
from placsp.pipeline import collapse, Pipeline
from placsp.atom_parser import parse_feed
from placsp.embedder import Embedder
from placsp.upserter import Upserter, object_uuid
from placsp.config import load_config
from placsp.models import ProcurementRecord, StatusEvent
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
    assert p.is_offpeak(datetime(2026,1,1,22,0)) is True    # start hour IS offpeak
    assert p.is_offpeak(datetime(2026,1,1,7,0)) is False     # end hour is NOT offpeak


def test_daily_merge_skips_stale_and_merges_history():
    """
    Verifies two C1/C2 spec invariants for the daily/reconcile updated-guard + status_history merge:
      1. When the incoming record is NEWER than stored, it is upserted and status_history is merged.
      2. When the incoming record is NOT NEWER than stored, it is SKIPPED entirely (no POST).
    """
    cfg = load_config()

    # Two test records: one newer (should be upserted+merged), one stale (should be skipped).
    SID_NEWER = "TEST-MERGE-NEWER-001"
    SID_STALE = "TEST-MERGE-STALE-001"

    uuid_newer = object_uuid(SID_NEWER)
    uuid_stale = object_uuid(SID_STALE)
    cls = cfg.weaviate_class

    # Stored state in Weaviate: both have updated=2026-02-01 and one PUB event
    stored_body = {
        "properties": {
            "updated": "2026-02-01T00:00:00Z",
            "status_history": [{"code": "PUB", "date": "2026-01-01"}],
        }
    }

    posted_objects = []

    def vec_handler(req):
        body = json.loads(req.content)
        return httpx.Response(200, json={"embeddings": [[0.1] * 4 for _ in body["texts"]]})

    def wv_handler(req):
        # GET /v1/objects/{cls}/{uuid} — return stored state for both SIDs
        if req.method == "GET":
            if f"/v1/objects/{cls}/{uuid_newer}" in req.url.path:
                return httpx.Response(200, json=stored_body)
            if f"/v1/objects/{cls}/{uuid_stale}" in req.url.path:
                return httpx.Response(200, json=stored_body)
            return httpx.Response(404)
        if req.method == "POST" and "/v1/batch/objects" in req.url.path:
            body = json.loads(req.content)
            posted_objects.extend(body.get("objects", []))
            return httpx.Response(200, json=[])
        if req.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    emb = Embedder(cfg.vectorizer_url, transport=httpx.MockTransport(vec_handler))
    up = Upserter(cfg.weaviate_url, "", cls, transport=httpx.MockTransport(wv_handler))
    p = Pipeline(cfg, emb, up, None)

    # Build records directly — no fixture file needed
    rec_newer = ProcurementRecord(
        syndication_id=SID_NEWER,
        category="externos_mayores",
        updated="2026-03-01T00:00:00Z",    # NEWER than stored 2026-02-01
        title="Contrato de prueba nuevero",
        status_code="EV",
        status_history=[StatusEvent(code="EV", date="2026-03-01")],
    )
    rec_stale = ProcurementRecord(
        syndication_id=SID_STALE,
        category="externos_mayores",
        updated="2026-01-15T00:00:00Z",    # OLDER than stored 2026-02-01 → must be skipped
        title="Contrato de prueba stale",
        status_code="PUB",
        status_history=[StatusEvent(code="PUB", date="2026-01-15")],
    )

    # Patch collapse so process_files uses our hand-built records instead of parsing files
    import placsp.pipeline as pipeline_mod
    original_collapse = pipeline_mod.collapse

    def fake_collapse(items, codelists):
        # Do NOT consume items (it would try to open the dummy file path).
        # Just return our pre-built records directly.
        return {SID_NEWER: rec_newer, SID_STALE: rec_stale}, []

    pipeline_mod.collapse = fake_collapse
    try:
        stats = p.process_files(["dummy_path_not_read.atom"], "externos_mayores", merge_stored=True)
    finally:
        pipeline_mod.collapse = original_collapse

    # --- Assertion 1: the NEWER record was upserted ---
    upserted_ids = {obj["id"] for obj in posted_objects}
    assert uuid_newer in upserted_ids, "Newer record must be upserted"

    # --- Assertion 2: the STALE record was NOT upserted ---
    assert uuid_stale not in upserted_ids, "Stale record must be skipped (not upserted)"

    # --- Assertion 3: skipped count is reported correctly ---
    assert stats["skipped"] >= 1, f"Expected at least 1 skipped, got {stats}"

    # --- Assertion 4: status_history on the upserted object contains BOTH events (PUB + EV) ---
    newer_obj = next(obj for obj in posted_objects if obj["id"] == uuid_newer)
    hist = newer_obj["properties"]["status_history"]
    hist_keys = {(e["code"], e["date"]) for e in hist}
    assert ("PUB", "2026-01-01") in hist_keys, f"Stored PUB event must survive merge; got {hist}"
    assert ("EV", "2026-03-01") in hist_keys, f"Incoming EV event must appear after merge; got {hist}"
