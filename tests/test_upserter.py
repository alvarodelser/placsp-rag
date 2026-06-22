import uuid, json, httpx
from placsp.upserter import object_uuid, Upserter
from placsp.models import ProcurementRecord, Tombstone

def test_object_uuid_deterministic():
    a = object_uuid("19862167"); b = object_uuid("19862167")
    assert a == b == str(uuid.uuid5(uuid.NAMESPACE_URL, "https://placsp.id/19862167"))

def test_upsert_posts_batch_with_vector_and_id():
    sent = {}
    def handler(req):
        if req.method == "POST" and req.url.path.endswith("/batch/objects"):
            sent["body"] = json.loads(req.content)
            return httpx.Response(200, json=[{"result": {"status": "SUCCESS"}}])
        return httpx.Response(404)
    up = Upserter("http://wv:8086", "k", "Placsp_licitaciones", transport=httpx.MockTransport(handler))
    rec = ProcurementRecord(syndication_id="19862167", category="placsp_mayores", updated="2026-06-19T21:50:27+02:00", title="X")
    n = up.upsert([rec], [[0.1, 0.2]])
    assert n == 1
    obj = sent["body"]["objects"][0]
    assert obj["id"] == object_uuid("19862167")
    assert obj["class"] == "Placsp_licitaciones"
    assert obj["vector"] == [0.1, 0.2]
    assert obj["properties"]["syndication_id"] == "19862167"

def test_apply_tombstones_deletes_by_id():
    deleted = []
    def handler(req):
        if req.method == "DELETE":
            deleted.append(req.url.path)
            return httpx.Response(204)
        return httpx.Response(404)
    up = Upserter("http://wv:8086", "k", "Placsp_licitaciones", transport=httpx.MockTransport(handler))
    n = up.apply_tombstones([Tombstone("4482937", "2026-06-21T00:00:39+02:00", "CERRADA", "externos_mayores")])
    assert n == 1
    assert object_uuid("4482937") in deleted[0]
