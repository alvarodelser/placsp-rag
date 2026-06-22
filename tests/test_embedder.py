import json, httpx
from placsp.embedder import Embedder

def _handler(request):
    body = json.loads(request.content)
    texts = body["texts"]
    assert body["normalize"] is True
    return httpx.Response(200, json={"embeddings": [[float(len(t))] * 4 for t in texts]})

def test_embed_batches_and_preserves_order():
    tr = httpx.MockTransport(_handler)
    emb = Embedder("http://vec:8089", batch_size=2, transport=tr)
    out = emb.embed(["a", "bb", "ccc"])
    assert len(out) == 3
    assert out[0] == [1.0, 1.0, 1.0, 1.0]
    assert out[2] == [3.0, 3.0, 3.0, 3.0]

def test_embed_empty():
    emb = Embedder("http://vec:8089", transport=httpx.MockTransport(_handler))
    assert emb.embed([]) == []
