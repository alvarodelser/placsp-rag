from placsp.pipeline import Pipeline

class _StubUpserter:
    def upsert(self, recs, vectors): return len(recs)
    def apply_tombstones(self, tombs): return len(tombs)
    def get_stored(self, sid): return None

class _StubEmbedder:
    def embed(self, texts): return [[0.0] for _ in texts]

class _StubGraphSink:
    def __init__(self): self.upserted = None; self.tombs = None
    def upsert(self, recs): self.upserted = recs; return len(recs)
    def apply_tombstones(self, tombs): self.tombs = tombs; return len(tombs)

class _Cfg:
    weaviate_class = "X"; weaviate_url = ""; weaviate_api_key = ""
    offpeak_start = 22; offpeak_end = 7

def test_process_files_calls_graph_sink():
    gs = _StubGraphSink()
    p = Pipeline(_Cfg(), _StubEmbedder(), _StubUpserter(), codelists=None, graph_sink=gs)
    out = p.process_files(["tests/fixtures/menores.atom"], "placsp_menores")
    assert gs.upserted is not None  # graph_sink.upsert was called
    assert out["upserted"] >= 0

def test_graph_sink_optional_defaults_none():
    p = Pipeline(_Cfg(), _StubEmbedder(), _StubUpserter(), codelists=None)
    assert p.graph_sink is None
