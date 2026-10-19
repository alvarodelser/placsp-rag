"""Keyword vectors: the indexer and the API must tokenise alike, and the stemmer must fold what it should."""
from pathlib import Path

from placsp_pilot import lexical as L

REPO = Path(__file__).resolve().parents[2]


def test_indexer_and_api_share_one_module():
    assert (REPO / "pilot" / "placsp_pilot" / "lexical.py").read_bytes() == (REPO / "search-api" / "pilot_lexical.py").read_bytes()


def test_terms_fold_accents_plural_and_gender_and_keep_numbers():
    assert L.terms("Los contratos de la cláusula 8ª") == L.terms("contrato clausula 8a")
    assert L.stem("obligadas") == L.stem("obligado")
    assert "2024" in L.terms("en el año 2024")
    assert L.terms("de la y en") == []


def test_bm25_weights_saturate_and_queries_match_documents():
    idx, w = L.doc_vector("garantía garantía garantía definitiva", avg_len=4)
    weights = dict(zip(idx, w))
    g, d = L.index_of(L.stem("garantia")), L.index_of(L.stem("definitiva"))
    assert weights[g] > weights[d] and weights[g] < 3 * weights[d]
    q_idx, _ = L.query_vector("¿Qué garantía definitiva?")
    assert set(q_idx) == {g, d}
