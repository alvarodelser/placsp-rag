import io
import zipfile
from pathlib import Path

import pytest

from placsp_pilot import classify as C
from placsp_pilot.codelists import Codelists
from placsp_pilot.codice import Parser, iter_entries
from placsp_pilot.detail import parse_detail, parse_external, preferred_formats
from placsp_pilot.graph import norm_name, org_id
from placsp_pilot.nlpstages import _score, split_words
from placsp_pilot.textract import extract, sniff

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures"


@pytest.fixture(scope="module")
def parser():
    return Parser(Codelists(REPO / "codelists"))


def _parse_all(parser, name, channel):
    entries, _ = iter_entries(str(FIX / name))
    return [parser.parse_entry(e, channel) for e in entries]


def test_mayores_keeps_typed_documents_and_notices(parser):
    recs = _parse_all(parser, "mayores.atom", "placsp_mayores")
    sources = {d["source"] for r in recs for d in r["documents"]}
    assert {"feed_legal", "feed_technical", "feed_general"} <= sources
    assert any(r["notices"] for r in recs)
    assert all(r["lots"] for r in recs)
    general = [d for r in recs for d in r["documents"] if d["source"] == "feed_general"]
    assert all(d["type_code"] for d in general)


def test_mayores_criteria_and_modifications(parser):
    recs = _parse_all(parser, "mayores.atom", "placsp_mayores")
    crit = [c for r in recs for c in r["award_criteria"]]
    assert crit and all(c["kind"] in ("judgement", "formula", None) for c in crit)
    assert any(r["modifications"] for r in recs)


def test_menores_have_one_implicit_lot_and_no_documents(parser):
    recs = _parse_all(parser, "menores.atom", "placsp_menores")
    for r in recs:
        assert len(r["lots"]) == 1 and r["lots"][0].get("implicit")
        assert not [d for d in r["documents"] if d["source"] in ("feed_legal", "feed_technical")]


def test_classify_rules():
    assert C.classify({"source": "feed_legal"}, "placsp_mayores")[0] == C.PCAP
    assert C.classify({"source": "feed_legal", "also_technical": True}, "placsp_mayores")[0] == C.PCAP_PPT
    assert C.classify({"source": "feed_general", "type_code": "12"}, "placsp_mayores")[0] == C.BOARD_MINUTES
    assert C.classify({"source": "feed_general", "type_code": "1"}, "propios")[0] == C.CONTRACT_DOCUMENT
    assert C.classify({"source": "feed_notice", "type_code": "ACTA_ADJ"}, "placsp_mayores")[0] == C.AWARD_RESOLUTION
    assert C.classify({"source": "detail_notice", "label": "Rectificación de Pliego"}, "placsp_mayores")[0] == C.CLARIFICATION
    assert C.classify({"source": "detail_notice", "label": "Adjudicación"}, "placsp_mayores")[0] == C.AWARD_NOTICE
    assert C.classify({"source": "feed_additional", "label": "DEUC contrato.pdf"}, "placsp_mayores")[0] == C.ANNEX
    assert C.classify({"source": "detail_external", "label": "PLIEGO CLAUSULAS ADVAS Y TECNICAS"}, "externos_mayores")[0] == C.PCAP_PPT
    assert C.classify({"source": "detail_other", "label": "Propuesta de adjudicación"}, "placsp_mayores")[0] == C.AWARD_PROPOSAL


DETAIL = """<table id="myTablaDetalleVISUOE"><tr><td>16/07/2026 09:59:21</td><td class="tipoDocumento">Anuncio de Licitación</td>
<td><a href="https://contrataciondelestado.es/FileSystem/servlet/GetDocumentByIdServlet?x=1"><img alt="Documento html"/></a>
<a href="https://contrataciondelestado.es/FileSystem/servlet/GetDocumentByIdServlet?x=2"><img alt="Documento xml"/></a>
<a href="https://contrataciondelestado.es/FileSystem/servlet/GetDocumentByIdServlet?x=3"><img alt="Documento pdf"/></a></td></tr></table>
<table id="other"><tr><td>20/07/2026 10:40:23</td><td><span>Memoria justificativa</span></td>
<td><a href="https://contrataciondelestado.es/FileSystem/servlet/GetDocumentByIdServlet?x=4"><img src="lupa.png"/></a></td></tr></table>"""


def test_detail_page_notice_formats_and_other_docs():
    refs = parse_detail(DETAIL)
    assert [r["source"] for r in refs] == ["detail_notice"] * 3 + ["detail_other"]
    assert refs[0]["label"] == "Anuncio de Licitación" and refs[0]["published"] == "2026-07-16"
    assert refs[3]["label"] == "Memoria justificativa"
    assert preferred_formats(refs) == {refs[0]["url"]}


def test_external_page_links():
    html = ('<ul><li>PLIEGO <a href="mtoGeneraDocumento.aspx?DOA=1">PLIEGO CLAUSULAS</a></li>'
            '<li><a href="/medias/memoria-44/download">Descargar</a> Memoria justificativa</li>'
            '<li><a href="javascript:void(0)">x</a></li></ul>')
    refs = parse_external(html, "https://example.org/a/b.aspx")
    assert [r["url"] for r in refs] == ["https://example.org/a/mtoGeneraDocumento.aspx?DOA=1",
                                        "https://example.org/medias/memoria-44/download"]
    assert "Memoria" in refs[1]["label"]


def test_split_words_matches_relation_chunker():
    text = "\n\n".join(f"párrafo {i} " + ("relleno " * 40) for i in range(50))
    pieces = split_words(text, 120)
    assert all(len(p.split()) <= 120 for p in pieces)
    assert sum(len(p.split()) for p in pieces) == len(text.split())
    assert split_words("una " * 300, 100) == [" ".join(["una"] * 100)] * 3
    assert _score("Criterios de adjudicación: 60 puntos al precio") > _score("Texto sin interés")


def test_textract_office_and_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="x"><w:body><w:p><w:t>Hola pliego</w:t></w:p></w:body></w:document>')
    docx = buf.getvalue()
    assert sniff(docx, "a.bin", None) == "docx"
    assert "Hola pliego" in extract(docx, "docx").text
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("PCAP.pdf", b"%PDF-1.4")
    res = extract(buf.getvalue(), sniff(buf.getvalue(), "docs.zip", None))
    assert res.status == "archive" and res.members[0][0] == "PCAP.pdf"
    assert extract(b"\x00" * 10, "dwg").status == "unsupported"


def test_org_identity():
    assert norm_name("CONSTRUCCIONES PÉREZ, S.L.") == norm_name("Construcciones Perez SL")
    assert org_id("X", "b-12.345.678") == "org:nif:B12345678"


def test_documents_ordered_by_effective_date_then_lifecycle():
    from placsp_pilot.order import order_documents
    tender = {"notices": [{"type": {"code": "DOC_CN"}, "published": "2026-03-01"},
                          {"type": {"code": "DOC_CAN_ADJ"}, "published": "2026-05-10"},
                          {"type": {"code": "DOC_FORM"}, "published": "2026-06-01"}]}
    docs = [
        {"sha": "a", "role": C.CONTRACT_DOCUMENT, "label": "Contrato", "published": None, "notice_type": "DOC_FORM"},
        {"sha": "b", "role": C.ANNEX, "label": "Anexo I", "published": None, "notice_type": None},
        {"sha": "c", "role": C.PCAP, "label": "PCAP", "published": None, "notice_type": None},
        {"sha": "d", "role": C.BOARD_MINUTES, "label": "Acta", "published": "2026-04-02", "notice_type": None},
        {"sha": "e", "role": C.TENDER_NOTICE, "label": "Anuncio", "published": "2026-03-01", "notice_type": None},
    ]
    out = order_documents(docs, tender)
    assert [d["sha"] for d in out] == ["e", "c", "b", "d", "a"]
    assert [d["seq"] for d in out] == [1, 2, 3, 4, 5]
    assert out[1]["effective_date"] == "2026-03-01" and out[1]["date_source"] == "stage"
    assert out[4]["date_source"] == "notice"


def test_chunk_page_ranges():
    from placsp_pilot.index import page_ranges
    pieces = ["[Página 1]\nuno", "sigue uno", "[Página 2]\ndos\n[Página 3]\ntres", "más tres"]
    assert page_ranges(pieces) == [(1, 1), (1, 1), (2, 3), (3, 3)]


def test_neo4j_props_are_primitive():
    from placsp_pilot.index import neo_props
    p = neo_props({"id": "x", "label": "L", "a": 1, "b": ["x", "y"], "c": {"k": 1}, "d": [{"k": 1}], "e": None, "f": []})
    assert p == {"a": 1, "b": ["x", "y"], "c": '{"k": 1}', "d": '[{"k": 1}]'}
