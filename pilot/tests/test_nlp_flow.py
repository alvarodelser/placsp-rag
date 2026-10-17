"""End-to-end over the NLP stages and the graph, against the fake nlp_service."""
import json
from pathlib import Path

import pytest

from placsp_pilot import graph, nlpstages, ontology, report
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
    nlpstages.resolve(cfg, store)
    nlpstages.describe(cfg, store)
    nlpstages.consolidate(cfg, store)
    assert store.one("SELECT resolve_status s FROM blob WHERE sha=?", (sha,))["s"] in ("ok", "skipped")
    g = graph.build(cfg, store)
    labels = {n["label"] for n in g.nodes.values()}
    assert {"Tender", "Lot", "Document", "Organization"} <= labels
    doc = g.nodes[f"doc:{sha}"]
    assert doc["summary"] and doc["ner_chunks"] > doc["ner_chunks_processed"]
    tender = g.nodes[f"tender:{rec['id']}"]
    assert tender["description"].endswith("descripción de prueba.")
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
    for stage in ("summarize", "ner", "resolve", "describe", "consolidate"):
        getattr(nlpstages, stage)(cfg, store, 10_000) if stage == "summarize" else getattr(nlpstages, stage)(cfg, store)
    index.index(cfg, store)
    validate.validate(cfg, store)
    fails = store.q("SELECT check_id, expected, actual FROM validation WHERE status='fail'")
    assert not [dict(f) for f in fails]
    qd = index.QdrantIndex(cfg)
    assert qd.count("tenders") == 1 and qd.count("chunks", tender_id=rec["id"]) > 0
    for short in index.COLLECTIONS:
        qd.client.delete_collection(qd.name(short))
    index.Neo4jIndex(cfg).reset()
