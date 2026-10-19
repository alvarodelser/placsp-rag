"""The pilot's question answering: what reaches the model, how citations are read, how the
stream is shaped, and that every missing piece is said rather than skipped silently."""
import json

import httpx
import pytest

import pilot_rag as R

PASSAGES = [{"tender_id": "1", "doc_sha256": "a" * 64, "doc_seq": 3, "doc_role": "PCAP", "doc_title": "Pliego",
             "chunk_idx": 4, "page_from": 12, "page_to": 12, "text": "La garantía definitiva será del 5 %\tdel importe."},
            {"tender_id": "1", "doc_sha256": "b" * 64, "doc_seq": 4, "doc_role": "PPT", "doc_title": "PPT",
             "chunk_idx": 0, "page_from": None, "page_to": None, "text": "Prescripciones técnicas."}]


def test_cited_keeps_order_and_drops_unknown_numbers():
    assert R.cited("Es del 5 % [1]. Ver también [F] y [1], [9].", 2) == [1, "F"]


def test_prompt_numbers_passages_with_role_and_page():
    p = R.prompt("¿Garantía definitiva?", "Objeto: X", PASSAGES)
    assert "[F] Datos del expediente" in p and "[1] (PCAP, pág. 12) La garantía definitiva será del 5 % del importe." in p
    assert "[2] (PPT) Prescripciones" in p


def test_facts_name_guarantees_and_feed_criteria():
    t = {"name": "Obra", "authority": {"name": "Ayto"}, "value": 1000, "guarantees": [{"name": "Final", "pct": 5}],
         "lots": [{"number": "1", "award_criteria": [{"name": "Precio", "points": 60, "source": "feed"},
                                                       {"name": "Ruido", "points": 1, "source": "documents"}]}]}
    f = R.facts_of(t)
    assert "Garantía definitiva: 5%" in f and "Precio (60 puntos)" in f and "Ruido" not in f


def _read(gen):
    return [json.loads(line) for line in gen]


def test_events_stream_passages_tokens_and_citations(monkeypatch):
    monkeypatch.setattr(R, "ANSWER_OLLAMA_URL", "http://ollama")
    monkeypatch.setattr(R, "answer", lambda q, f, p: iter(["Es del 5 % ", "[1]."]))
    evs = _read(R.events("q", "", PASSAGES, {"hybrid": True}))
    assert [e["type"] for e in evs] == ["passages", "token", "token", "done"]
    assert evs[-1]["text"] == "Es del 5 % [1]." and evs[-1]["cited"] == [1]


def test_events_say_why_there_is_no_answer(monkeypatch):
    monkeypatch.setattr(R, "ANSWER_OLLAMA_URL", "")
    evs = _read(R.events("q", "", PASSAGES, {}))
    assert evs[-1]["type"] == "done" and "ANSWER_OLLAMA_URL" in evs[-1]["note"]

    def down(q, f, p):
        raise httpx.ConnectError("refused")
        yield  # noqa: unreachable — a generator
    monkeypatch.setattr(R, "ANSWER_OLLAMA_URL", "http://ollama")
    monkeypatch.setattr(R, "answer", down)
    assert _read(R.events("q", "", PASSAGES, {}))[-1]["type"] == "error"


class _Point:
    def __init__(self, payload, score):
        self.payload, self.score = payload, score


class _Qdrant:
    def __init__(self, fail_hybrid=False):
        self.fail_hybrid, self.calls = fail_hybrid, []

    def query_points(self, coll, **kw):
        self.calls.append(kw)
        if self.fail_hybrid and "prefetch" in kw:
            raise ValueError("no bm25")
        return type("R", (), {"points": [_Point(p, 0.5 - i / 10) for i, p in enumerate(PASSAGES)]})()


def test_retrieve_is_hybrid_and_reranked(monkeypatch):
    monkeypatch.setattr(R, "RERANKER_URL", "http://rr")

    def post(url, json, timeout):
        assert url == "http://rr/rerank" and len(json["texts"]) == 2
        return httpx.Response(200, json=[{"index": 1, "score": 0.9}, {"index": 0, "score": 0.2}], request=httpx.Request("POST", url))
    monkeypatch.setattr(R.httpx, "post", post)
    q = _Qdrant()
    got, info = R.retrieve(q, "c", "garantía definitiva", [0.0] * 4, "1")
    assert info["hybrid"] and info["reranked"] and [p["doc_role"] for p in got] == ["PPT", "PCAP"]
    assert {pf.using for pf in q.calls[0]["prefetch"]} == {"text", "bm25"}


def test_retrieve_falls_back_and_says_so(monkeypatch):
    monkeypatch.setattr(R, "RERANKER_URL", "")
    got, info = R.retrieve(_Qdrant(fail_hybrid=True), "c", "garantía", [0.0] * 4)
    assert len(got) == 2 and not info["hybrid"] and not info["reranked"]
    assert any("palabras clave" in n for n in info["notes"]) and any("RERANKER_URL" in n for n in info["notes"])


@pytest.mark.parametrize("q", ["de la", ""])
def test_a_question_of_stop_words_searches_by_meaning_only(monkeypatch, q):
    monkeypatch.setattr(R, "RERANKER_URL", "")
    qd = _Qdrant()
    R.retrieve(qd, "c", q, [0.0] * 4)
    assert [pf.using for pf in qd.calls[0]["prefetch"]] == ["text"]
