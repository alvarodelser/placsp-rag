"""End-to-end over the NLP stages and the graph, against the fake nlp_service."""
import json
from pathlib import Path

import pytest

from placsp_pilot import entities, graph, nlpstages, ontology, report
from placsp_pilot.codelists import Codelists
from placsp_pilot.codice import Parser, iter_entries
from placsp_pilot.config import load_config
from placsp_pilot.stages import _insert_expediente, _save_blob
from placsp_pilot.store import Store

from fake_nlp import serve

REPO = Path(__file__).resolve().parents[2]

PCAP_TEXT = """PLIEGO DE CLÁUSULAS ADMINISTRATIVAS PARTICULARES

El contrato se divide en Lote 1 (limpieza) y Lote 2 (jardinería).

Criterios de adjudicación del Lote 1:
Oferta económica: hasta 60 puntos
Memoria técnica: hasta 40 puntos

Licitadores: LIMPIEZAS DEL NORTE, S.L. con NIF B12345678 y JARDINES SUR, S.A. A87654321.
"""


@pytest.fixture()
def run(tmp_path, monkeypatch):
    srv = serve()
    monkeypatch.setenv("NLP_SERVICE_URL", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setenv("PILOT_NER_MAX_CHUNKS", "1")
    monkeypatch.setenv("PILOT_CHUNK_WORDS", "30")
    cfg = load_config(str(tmp_path))
    store = Store(cfg.db_path)
    entries, _ = iter_entries(str(REPO / "tests" / "fixtures" / "mayores.atom"))
    rec = Parser(Codelists(REPO / "codelists")).parse_entry(entries[0], "placsp_mayores")
    raw = tmp_path / "raw.xml"
    raw.write_text("<entry/>")
    _insert_expediente(store, rec, raw, 8)
    sha = _save_blob(cfg, store, PCAP_TEXT.encode(), "PCAP.txt", "text/plain")
    tp = cfg.text_dir / f"{sha}.txt"
    tp.write_text(PCAP_TEXT, encoding="utf-8")
    store.update("blob", {"sha": sha}, text_status="ok", text_path=str(tp), text_chars=len(PCAP_TEXT))
    with store.tx() as c:
        c.execute("INSERT INTO docref (exp_id, url, source, label, role, role_source, status, sha) VALUES (?,?,?,?,?,?,?,?)",
                  (rec["id"], "http://x/pcap", "feed_legal", "PCAP.pdf", "PCAP", "feed_legal", "fetched", sha))
        # The fixture's other references are not downloaded in this test.
        c.execute("UPDATE docref SET status='skipped', error='not in test' WHERE exp_id=? AND url!='http://x/pcap'", (rec["id"],))
    yield cfg, store, rec, sha
    srv.shutdown()


def test_ontology_projects_a_valid_schema():
    cfg = load_config("/tmp/placsp-pilot-ontology-test")
    schema = ontology.extraction_schema(ontology.load(cfg.ontology_path))
    names = {e["name"] for e in schema["entity_types"]}
    assert {"LOT", "AWARD_CRITERION", "REQUIREMENT", "BID", "COMPANY", "CONTRACT"} <= names
    for r in schema["relation_types"]:
        assert set(r["head_types"]) <= names and set(r["tail_types"]) <= names
    for e in schema["entity_types"]:
        assert all(a["datatype"] in ("string", "number", "boolean") for a in e["attributes"])


def test_nlp_stages_build_the_graph(run):
    cfg, store, rec, sha = run
    nlpstages.summarize(cfg, store, 10_000)
    nlpstages.ner(cfg, store)
    blob = store.one("SELECT * FROM blob WHERE sha=?", (sha,))
    assert blob["summary_status"] == "ok"
    # The cap keeps one chunk: the one with the most procurement vocabulary.
    assert blob["ner_chunks_selected"] == 1 and blob["ner_chunks_total"] > 1 and blob["ner_status"] == "ok"
    entities.mentions(cfg, store)
    entities.resolve(cfg, store)
    entities.refine(cfg, store)
    entities.formulas(cfg, store)
    entities.describe(cfg, store)
    nlpstages.summary(cfg, store)
    assert store.one("SELECT status FROM resolution WHERE exp_id=?", (rec["id"],))["status"] == "ok"
    n_ent = store.one("SELECT COUNT(*) n FROM entity WHERE exp_id=?", (rec["id"],))["n"]
    assert n_ent and store.one("SELECT COUNT(*) n FROM entity_description WHERE status='ok' AND kind='entity'")["n"] >= n_ent - 5
    g = graph.build(cfg, store)
    labels = {n["label"] for n in g.nodes.values()}
    assert {"Tender", "Lot", "Document", "Organization"} <= labels
    doc = g.nodes[f"doc:{sha}"]
    assert doc["summary"] and doc["ner_chunks"] > doc["ner_chunks_processed"]
    tender = g.nodes[f"tender:{rec['id']}"]
    assert tender["description"].endswith("descripción de prueba.")
    assert tender["short_title"] and len(tender["short_title"].split()) <= nlpstages.TITLE_WORDS + 1
    out = json.loads((cfg.out_dir / "expedientes" / f"{rec['id']}.json").read_text())
    assert out["documents"][0]["role"] == "PCAP"
    path = report.write(cfg, store)
    text = path.read_text()
    assert "## nlp_service and other services" in text and "summarize:article" in text


def _stores_up() -> bool:
    import os
    import socket
    if not (os.getenv("PILOT_TEST_QDRANT_URL") and os.getenv("PILOT_TEST_NEO4J_PASSWORD")):
        return False
    try:
        socket.create_connection(("localhost", 7687), timeout=1).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _stores_up(), reason="set PILOT_TEST_QDRANT_URL/_API_KEY and PILOT_TEST_NEO4J_PASSWORD to run against real stores")
def test_index_and_validate_against_real_stores(run, monkeypatch):
    import os
    from placsp_pilot import index, validate
    cfg, store, rec, sha = run
    monkeypatch.setenv("VECTORIZER_URL", os.environ["NLP_SERVICE_URL"])
    monkeypatch.setenv("QDRANT_URL", os.environ["PILOT_TEST_QDRANT_URL"])
    monkeypatch.setenv("QDRANT_API_KEY", os.getenv("PILOT_TEST_QDRANT_API_KEY", ""))
    monkeypatch.setenv("NEO4J_PASSWORD", os.environ["PILOT_TEST_NEO4J_PASSWORD"])
    monkeypatch.setenv("PILOT_COLLECTION_PREFIX", "pilottest_")
    monkeypatch.setenv("PILOT_NEO4J_LABEL_PREFIX", "PilotTest")
    cfg = load_config(str(cfg.run_dir))
    nlpstages.summarize(cfg, store, 10_000)
    nlpstages.ner(cfg, store)
    for stage in (entities.mentions, entities.resolve, entities.refine, entities.describe, nlpstages.summary):
        stage(cfg, store)
    index.index(cfg, store)
    validate.validate(cfg, store)
    fails = store.q("SELECT check_id, expected, actual FROM validation WHERE status='fail'")
    assert not [dict(f) for f in fails]
    qd = index.QdrantIndex(cfg)
    assert qd.count("tenders") == 1 and qd.count("chunks", tender_id=rec["id"]) > 0
    for short in index.COLLECTIONS:
        qd.client.delete_collection(qd.name(short))
    index.Neo4jIndex(cfg).reset()


def test_ner_stops_when_calls_are_too_slow(run, monkeypatch):
    cfg, store, rec, sha = run
    monkeypatch.setenv("PILOT_NER_MAX_CHUNKS", "0")
    monkeypatch.setenv("PILOT_CHUNK_WORDS", "10")
    monkeypatch.setenv("PILOT_NER_PREFLIGHT_S", "-1")  # every call counts as too slow
    cfg = load_config(str(cfg.run_dir))
    with pytest.raises(SystemExit, match="PILOT_NER_PREFLIGHT_S"):
        nlpstages.ner(cfg, store)
    counts = {r["status"]: r["n"] for r in store.q("SELECT status, COUNT(*) n FROM chunk GROUP BY status")}
    assert counts["ok"] == 2 and counts["pending"] > 0  # two tries, the rest left for the next run


def test_text_stage_deletes_the_file_and_keeps_its_text(tmp_path, monkeypatch):
    import base64
    import hashlib
    from placsp_pilot import stages
    cfg = load_config(str(tmp_path))
    store = Store(cfg.db_path)
    data = PCAP_TEXT.encode()
    sha = _save_blob(cfg, store, data, "PCAP.txt", "text/plain")
    path = Path(store.one("SELECT path FROM blob WHERE sha=?", (sha,))["path"])
    assert path.exists()
    stages.text(cfg, store)
    b = store.one("SELECT * FROM blob WHERE sha=?", (sha,))
    assert b["text_status"] == "ok" and Path(b["text_path"]).read_text(encoding="utf-8").strip()
    assert not path.exists() and b["path"] is None
    assert b["sha1_b64"] == base64.b64encode(hashlib.sha1(data).digest()).decode()
    # Asked to extract again, it says the file must be fetched again instead of failing the stage.
    store.update("blob", {"sha": sha}, text_status="pending")
    stages.text(cfg, store)
    assert "refetch" in store.one("SELECT error FROM blob WHERE sha=?", (sha,))["error"]


def test_text_stage_keeps_the_file_when_asked(tmp_path, monkeypatch):
    from placsp_pilot import stages
    monkeypatch.setenv("PILOT_KEEP_FILES", "1")
    cfg = load_config(str(tmp_path))
    store = Store(cfg.db_path)
    sha = _save_blob(cfg, store, PCAP_TEXT.encode(), "PCAP.txt", "text/plain")
    stages.text(cfg, store)
    assert Path(store.one("SELECT path FROM blob WHERE sha=?", (sha,))["path"]).exists()
