"""Entity resolution on mentions shaped like the real NER output of the smoke run: typos,
a NIF with a dash, an acta's score of 0, ENI codes, the authority's own committee."""
import json
from pathlib import Path

import pytest

from placsp_pilot import entities as E
from placsp_pilot.codelists import Codelists
from placsp_pilot.codice import Parser, iter_entries
from placsp_pilot.config import load_config
from placsp_pilot.stages import _insert_expediente, _save_blob
from placsp_pilot.store import Store

from fake_nlp import serve

REPO = Path(__file__).resolve().parents[2]


def test_locate_finds_trimmed_and_respaced_quotes():
    chunk = "[Página 3]\nLa  oferta económica   se valorará\ncon hasta 31 puntos según la fórmula."
    assert E.locate(chunk, "La oferta económica se valorará con hasta 31 puntos") is not None
    a, b = E.locate(chunk, "oferta economica se valorara")
    assert chunk[a:b].startswith("oferta")
    assert E.locate(chunk, "algo que no está en el texto en absoluto") is None
    assert E.page_at(chunk, 20, None) == 3


@pytest.mark.parametrize("a,b,same", [
    ("ESPUBLICO SESRVICIOS PARA LA ADMINISTRACIÓN S.A.", "ESPUBLICO, SERVICIOS PARA LA ADMINISTRACIÓN, SA", True),
    ("Garantía adicionales de disponibilidad", "Garantías adicionales de disponibilidad", True),
    ("Integración con FACE", "Integración con PCSP", False),
    ("Videos demostrativos ENI-14", "Videos demostrativos ENI-15", False),
    ("Sistema de firma electrónica avanzada", "Sistema de firma electrónica cualificada", False),
])
def test_typo_equal(a, b, same):
    assert E.typo_equal(a, b) is same


def test_attribute_values_compare_normalised():
    ms = [{"attributes": json.dumps({"nif": "A-50878842", "cpv": "72000000-1", "points": 0}), "confidence": 1},
          {"attributes": json.dumps({"nif": "A50878842", "cpv": "72000000", "points": 40}), "confidence": 1}]
    attrs, conflicts = E._merge_attrs(ms, None)
    assert attrs == {"nif": "A50878842", "cpv": "72000000", "points": 40.0} and not conflicts


PCAP = ("PLIEGO. Órgano de contratación: Universidad de Almería. Lote 1. "
        "Oferta Económica: hasta 31 puntos mediante fórmula. Memoria Técnica: hasta 49 puntos, juicio de valor. "
        "Solvencia económica: volumen anual de negocios de 30.000 euros en los tres últimos años. "
        "Requisitos ENI-03 y ENI-04 de interoperabilidad. Adjudicataria propuesta ACME SERVICIOS, S.L., NIF B-12345678.")
ACTA = ("ACTA. Reunida la Mesa de Contratación. Oferta de ACME SERVICIOS al lote 1. "
        "ACME SERVCIOS SL obtiene en Oferta Económica 0 puntos de penalización y en Memoria Tecnica 49 puntos. "
        "La adjudicataria deberá constituir la garantía definitiva.")


def ent(name, typ, ev, subtype=None, **attrs):
    return {"name": name, "mention_text": name, "type": typ, "subtype": subtype, "evidence_text": ev,
            "attributes": attrs, "confidence": 0.9}


@pytest.fixture()
def expediente(tmp_path, monkeypatch):
    srv = serve()
    monkeypatch.setenv("NLP_SERVICE_URL", f"http://127.0.0.1:{srv.server_port}")
    cfg = load_config(str(tmp_path))
    store = Store(cfg.db_path)
    entries, _ = iter_entries(str(REPO / "tests" / "fixtures" / "mayores.atom"))
    rec = Parser(Codelists(REPO / "codelists")).parse_entry(entries[0], "placsp_mayores")
    raw = tmp_path / "raw.xml"
    raw.write_text("<entry/>")
    _insert_expediente(store, rec, raw, 8)
    with store.tx() as c:
        c.execute("UPDATE docref SET status='skipped' WHERE exp_id=?", (rec["id"],))
    docs = {}
    for role, text, found in [
        ("PCAP", PCAP, {"entities": [
            ent("Lote 1", "LOT", "Lote 1", number="1"),
            ent("Oferta Económica", "AWARD_CRITERION", "Oferta Económica: hasta 31 puntos mediante fórmula", "FORMULA", points=31),
            ent("Memoria Técnica", "AWARD_CRITERION", "Memoria Técnica: hasta 49 puntos, juicio de valor", "JUDGEMENT", points=49),
            ent("Universidad de Almería", "CONTRACTING_AUTHORITY", "Órgano de contratación: Universidad de Almería"),
            ent("Volumen anual de negocios", "REQUIREMENT", "volumen anual de negocios de 30.000 euros en los tres últimos años",
                "TURNOVER", amount=30000, years=3),
            ent("ENI-03", "TECHNICAL_REQUIREMENT", "Requisitos ENI-03 y ENI-04"),
            ent("ENI-04", "TECHNICAL_REQUIREMENT", "Requisitos ENI-03 y ENI-04"),
            ent("ACME SERVICIOS, S.L.", "COMPANY", "ACME SERVICIOS, S.L., NIF B-12345678", nif="B-12345678")],
            "relations": [{"head": 0, "tail": 1, "type": "HAS_CRITERION", "evidence_text": "Lote 1", "attributes": {}, "confidence": 0.9}]}),
        ("BoardMinutes", ACTA, {"entities": [
            ent("Mesa de Contratación", "OTHER_ORGANIZATION", "Reunida la Mesa de Contratación"),
            ent("ACME SERVCIOS SL", "COMPANY", "ACME SERVCIOS SL obtiene"),
            ent("Oferta Económica", "AWARD_CRITERION", "Oferta Económica 0 puntos", "FORMULA", points=0),
            ent("Memoria Tecnica", "AWARD_CRITERION", "Memoria Tecnica 49 puntos", "JUDGEMENT", points=49),
            ent("Oferta de ACME SERVICIOS al lote 1", "BID", "Oferta de ACME SERVICIOS al lote 1", outcome="admitted")],
            "relations": [{"head": 4, "tail": 1, "type": "SUBMITTED_BY", "evidence_text": "Oferta de ACME", "attributes": {}, "confidence": 0.9}]}),
    ]:
        sha = _save_blob(cfg, store, text.encode(), f"{role}.txt", "text/plain")
        tp = cfg.text_dir / f"{sha}.txt"
        tp.write_text(text, encoding="utf-8")
        store.update("blob", {"sha": sha}, text_status="ok", text_path=str(tp), text_chars=len(text), ner_status="ok")
        with store.tx() as c:
            c.execute("INSERT INTO docref (exp_id, url, source, label, role, role_source, status, sha) VALUES (?,?,?,?,?,?,?,?)",
                      (rec["id"], f"http://x/{role}", "feed_legal", f"{role}.pdf", role, "feed_legal", "fetched", sha))
            c.execute("INSERT INTO chunk (sha, idx, words, chars, score, selected, status, result_json) VALUES (?,?,?,?,?,?,?,?)",
                      (sha, 0, len(text.split()), len(text), 1, 1, "ok", json.dumps(found, ensure_ascii=False)))
        docs[role] = sha
    yield cfg, store, rec, docs
    srv.shutdown()


def test_resolution_merges_across_documents_into_the_feed(expediente):
    cfg, store, rec, docs = expediente
    eid = rec["id"]
    E.mentions(cfg, store)
    assert store.one("SELECT SUM(located) n FROM mention WHERE kind='ner'")["n"] == 13
    E.resolve(cfg, store)
    ents = {r["id"]: r for r in store.q("SELECT * FROM entity WHERE exp_id=?", (eid,))}
    # The two documents' criteria are the feed's own lines of the baremo (an acta's 0 is a score, not a weight),
    # plus where locate.py found the feed's names without NER: the PCAP's two lines, the acta's "Memoria Tecnica 49 puntos".
    assert ents[f"crit:{eid}:feed0"]["mentions"] == 3 and ents[f"crit:{eid}:feed2"]["mentions"] == 4
    feed = {(m["target"], m["entity_id"]) for m in store.q(
        "SELECT m.target, em.entity_id FROM mention m JOIN entity_mention em ON em.mention_id=m.id WHERE m.kind='feed'")}
    # The authority too, by the name of its hierarchy (the feed's own name is the body that signs).
    assert feed == {(f"crit:{eid}:feed0",) * 2, (f"crit:{eid}:feed2",) * 2, (f"guarantee:{eid}:2:*",) * 2,
                    ("org:nif:Q5450008G",) * 2}
    assert not [i for i, r in ents.items() if r["type"] == "AWARD_CRITERION" and not r["anchor"]]
    # One company: NIF with a dash in the PCAP, a typo and no NIF in the acta.
    companies = [r for r in ents.values() if r["type"] == "COMPANY"]
    assert [c["id"] for c in companies] == ["org:nif:B12345678"] and companies[0]["mentions"] == 2
    # The committee is the authority acting; codes stay distinct.
    auth = ents["org:nif:Q5450008G"]
    assert auth["anchor"] == 1 and auth["mentions"] == 3
    assert {r["name"] for r in ents.values() if r["type"] == "TECHNICAL_REQUIREMENT"} == {"ENI-03", "ENI-04"}
    # The feed's "Según pliego" is spelt out by the PCAP's requirement.
    detail = store.q("SELECT src, dst FROM entity_relation WHERE exp_id=? AND type='DETAILED_BY'", (eid,))
    assert [r["dst"] for r in detail] == [f"requirement:{eid}:volumen anual de negocios"]
    # Every mention is placed but the "Lote 1" of a contract without lots, which is dropped and counted.
    assert store.one("SELECT COUNT(*) n FROM entity_mention WHERE exp_id=?", (eid,))["n"] == 12 + 5
    merges = json.loads(store.one("SELECT merges FROM resolution WHERE exp_id=?", (eid,))["merges"])
    assert merges["lot_mentions_dropped"] == 1
    names = [(r["type"], r["name"].lower()) for r in ents.values()]
    assert len(names) == len(set(names))


def test_describe_uses_domain_profiles_and_passages(expediente):
    cfg, store, rec, docs = expediente
    for stage in (E.mentions, E.resolve, E.refine, E.describe):
        stage(cfg, store)
    descs = {r["item_id"]: r for r in store.q("SELECT * FROM entity_description WHERE kind='entity'")}
    # Only in the documents: the model, with the domain profile.
    assert descs[f"requirement:{rec['id']}:volumen anual de negocios"]["profile"] == "requirement_desc"
    # The feed's criterion: from its fields, no call.
    crit = descs[f"crit:{rec['id']}:feed0"]
    assert crit["profile"] == "template" and crit["ms"] == 0 and "puntos" in crit["text"] and "criterio de adjudicación" in crit["text"]
    passages = E.passages(store, cfg, rec["id"], f"crit:{rec['id']}:feed0")
    assert any(p.startswith("[PCAP") and "31 puntos" in p for p in passages)


def test_describe_feed_entities_by_the_model_when_asked(expediente, monkeypatch):
    cfg, store, rec, docs = expediente
    monkeypatch.setenv("PILOT_DESCRIBE_FEED", "model")
    cfg = load_config(str(cfg.run_dir))
    for stage in (E.mentions, E.resolve, E.refine, E.describe):
        stage(cfg, store)
    prof = store.one("SELECT profile FROM entity_description WHERE item_id=?", (f"crit:{rec['id']}:feed0",))["profile"]
    assert prof == "criterion_desc"


def test_lots_are_mentioned_only_by_name():
    m = lambda name, ev="": {"name": name, "surface": name, "evidence": ev}
    assert not E.divided({"lots": [{"number": "1", "implicit": True}]})
    assert E.divided({"lots": [{"number": "1"}, {"number": "2"}]})
    # Without lots, nothing is a lot: not the object, not "no se divide en lotes".
    assert not E.lot_mention_ok(m("Lote 1", "se justifica la no división del objeto del contrato en lotes"), [], False)
    assert E.lot_mention_ok(m("Lote nº 2"), [], True)
    assert E.lot_mention_ok(m("Suministro de mobiliario escolar"), ["Suministro de mobiliario escolar"], True)
    assert E.lot_mention_ok(m("Lote 1", "la plataforma deberá permitir mantener un registro"), ["Limpieza"], True)
    assert not E.lot_mention_ok(m("Plataforma electrónica", "la plataforma deberá permitir mantener un registro"), ["Limpieza"], True)


def test_a_lot_is_described_by_what_the_documents_say_it_is():
    evs = ["El contrato se divide en dos lotes.", "LOTE 2: Suministro de mobiliario para las aulas de infantil. Presupuesto…"]
    assert E.lot_object("2", evs) == "Suministro de mobiliario para las aulas de infantil"
    assert E.lot_object("1", evs) is None


def test_formulas_for_criteria_scored_by_rule(expediente):
    cfg, store, rec, docs = expediente
    for stage in (E.mentions, E.resolve, E.refine, E.formulas):
        stage(cfg, store)
    rows = {r["entity_id"]: json.loads(r["result_json"]) for r in store.q("SELECT * FROM formula WHERE status='ok'")}
    price = rows[f"crit:{rec['id']}:feed0"]
    assert price["has_formula"] and price["expression"].startswith("P =")
    assert not [i for i in rows if "memoria" in i.lower()]            # judged by value: not asked
    from placsp_pilot import graph
    g = graph.build(cfg, store)
    assert g.nodes[f"crit:{rec['id']}:feed0"]["formula_model"]["variables"][0]["symbol"] == "P"


def test_coref_links_references_to_their_entity(expediente):
    cfg, store, rec, docs = expediente
    for stage in (E.mentions, E.resolve, E.coref):
        stage(cfg, store)
    refs = store.q("SELECT m.*, em.entity_id FROM mention m JOIN entity_mention em ON em.mention_id=m.id WHERE m.kind='coref'")
    assert [(r["name"], r["entity_id"], r["sha"]) for r in refs] == [("La adjudicataria", "org:nif:B12345678", docs["BoardMinutes"])]
    text = ACTA
    assert text[refs[0]["char_start"]:refs[0]["char_end"]] == "La adjudicataria"
    # A reference is evidence like any other: it is in the company's passages.
    assert any("La adjudicataria deberá constituir" in p for p in E.passages(store, cfg, rec["id"], "org:nif:B12345678"))
    # Re-resolving drops the references with the entities they pointed at.
    with store.tx() as c:
        c.execute("DELETE FROM resolution")
    E.resolve(cfg, store)
    assert store.one("SELECT COUNT(*) n FROM mention WHERE kind='coref'")["n"] == 0


VALUATION = ("INFORME DE VALORACIÓN. ACME SERVICIOS, S.L. (B12345678): 80 puntos en total. "
             "BETA OBRAS SL ofrece una memoria de 40 páginas y obtiene 30 puntos en Memoria técnica.")


def _add_valuation(cfg, store, rec):
    """A valuation report whose NER output names bidders and criteria by attribute only."""
    eid = rec["id"]
    found = {"entities": [
        ent("Oferta de ACME", "BID", "ACME SERVICIOS, S.L. (B12345678): 80 puntos en total",
            bidder="ACME SERVICIOS, S.L.", bidder_nif="B12345678", total_score=80),
        ent("Memoria técnica de BETA", "CRITERION_SCORE", "BETA OBRAS SL ofrece una memoria de 40 páginas y obtiene 30 puntos",
            bidder="BETA OBRAS SL", criterion="Memoria técnica", points=30, offered="memoria de 40 páginas")],
        "relations": []}
    sha = _save_blob(cfg, store, VALUATION.encode(), "valoracion.txt", "text/plain")
    tp = cfg.text_dir / f"{sha}.txt"
    tp.write_text(VALUATION, encoding="utf-8")
    store.update("blob", {"sha": sha}, text_status="ok", text_path=str(tp), text_chars=len(VALUATION), ner_status="ok")
    with store.tx() as c:
        c.execute("INSERT INTO docref (exp_id, url, source, label, role, role_source, status, sha) VALUES (?,?,?,?,?,?,?,?)",
                  (eid, "http://x/val", "detail_other", "valoracion.pdf", "ValuationReport", "rule", "fetched", sha))
        c.execute("INSERT INTO chunk (sha, idx, words, chars, score, selected, status, result_json) VALUES (?,?,?,?,?,?,?,?)",
                  (sha, 0, len(VALUATION.split()), len(VALUATION), 1, 1, "ok", json.dumps(found, ensure_ascii=False)))


def test_bids_and_scores_point_at_their_bidder_and_criterion(expediente):
    """A valuation table read by NER: the bidder and the criterion are attributes, not relations."""
    cfg, store, rec, docs = expediente
    eid = rec["id"]
    _add_valuation(cfg, store, rec)
    E.mentions(cfg, store)
    E.resolve(cfg, store)
    ents = {r["id"]: r for r in store.q("SELECT * FROM entity WHERE exp_id=?", (eid,))}
    rels = {(r["src"], r["type"], r["dst"]) for r in store.q("SELECT * FROM entity_relation WHERE exp_id=?", (eid,))}
    # The bidder named by NIF is the PCAP's company; the other bidder becomes a company of its own.
    beta = next(i for i, r in ents.items() if r["type"] == "COMPANY" and "beta" in i)
    assert ents["org:nif:B12345678"]["mentions"] == 3
    bids = {r["src"]: r["dst"] for r in store.q("SELECT * FROM entity_relation WHERE exp_id=? AND type='SUBMITTED_BY'", (eid,))}
    assert sorted(bids.values()) == sorted([beta, "org:nif:B12345678"])
    beta_bid = next(b for b, o in bids.items() if o == beta)
    score = next(i for i, r in ents.items() if r["type"] == "CRITERION_SCORE")
    assert (beta_bid, "HAS_SCORE", score) in rels
    # The acta's "Memoria técnica" is the feed's line of the baremo.
    assert (score, "FOR_CRITERION", f"crit:{eid}:feed2") in rels
    assert json.loads(ents[score]["attributes"])["points"] == 30


def test_a_bidder_without_nif_takes_the_one_stage_1_knows(expediente, tmp_path):
    """The valuation report names BETA OBRAS SL without a NIF; stage 1 has it as a winner elsewhere."""
    import duckdb
    from placsp_pilot import staging
    cfg, store, rec, docs = expediente
    cur = tmp_path / "staging" / "current"
    cur.mkdir(parents=True)
    duckdb.connect().execute(f"COPY (SELECT 'B99999999' AS nif_norm, ['BETA OBRAS, S.L.'] AS names) TO '{cur / 'company.parquet'}' (FORMAT parquet)")
    staging._COMPANIES.clear()
    cfg.staging_dir = str(tmp_path / "staging")
    _add_valuation(cfg, store, rec)
    E.mentions(cfg, store)
    E.resolve(cfg, store)
    ids = {r["id"] for r in store.q("SELECT id FROM entity WHERE exp_id=? AND type='COMPANY'", (rec["id"],))}
    assert "org:nif:B99999999" in ids
    merges = json.loads(store.one("SELECT merges FROM resolution WHERE exp_id=?", (rec["id"],))["merges"])
    assert merges["nif_from_staging"] >= 1
