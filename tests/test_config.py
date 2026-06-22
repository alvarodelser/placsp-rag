from placsp.config import load_config

def test_defaults(monkeypatch):
    monkeypatch.delenv("VECTORIZER_URL", raising=False)
    cfg = load_config()
    assert cfg.vectorizer_url == "http://vectorizer:8089"
    assert cfg.weaviate_class == "Placsp_licitaciones"
    assert cfg.embed_batch_size == 48
    assert cfg.max_in_flight == 1

def test_env_override(monkeypatch):
    monkeypatch.setenv("VECTORIZER_URL", "http://x:1")
    monkeypatch.setenv("PLACSP_EMBED_BATCH", "10")
    cfg = load_config()
    assert cfg.vectorizer_url == "http://x:1"
    assert cfg.embed_batch_size == 10
