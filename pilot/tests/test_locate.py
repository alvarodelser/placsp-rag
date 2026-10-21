"""Per-role NER schemas and the feed locator (locate.py), without any service."""
import pytest

from placsp_pilot import ontology
from placsp_pilot import locate as L
from placsp_pilot.config import load_config
from placsp_pilot.nlpstages import feed_lacks


@pytest.fixture(scope="module")
def data():
    return ontology.load(load_config("/tmp/placsp-pilot-ontology-test").ontology_path)


def test_each_role_gets_only_what_the_feed_does_not_give(data):
    assert ontology.ner_types(data, "PCAP") == {"PENALTY", "QUALIFICATION"}
    assert ontology.ner_types(data, "BoardMinutes") == {"COMPANY", "JOINT_VENTURE", "BID", "CRITERION_SCORE"}
    assert ontology.ner_types(data, "PCAP+PPT") >= {"PENALTY", "DELIVERABLE", "TEAM_PROFILE"}
    assert ontology.ner_types(data, "Annex") == set() and ontology.ner_types(data, "TenderNotice") == set()
    # A feed without criteria (an external platform's): the pliego is asked for them, the PPT is not.
    assert "AWARD_CRITERION" in ontology.ner_types(data, "PCAP", {"AWARD_CRITERION"})
    assert "AWARD_CRITERION" not in ontology.ner_types(data, "PPT", {"AWARD_CRITERION"})
    feed_types = {e["name"] for e in data["entity_types"] if e.get("source") == "feed"}
    for p in data["profiles"].values():
        assert not set(p["entity_types"]) & feed_types


def test_a_schema_keeps_the_relations_between_its_types(data):
    s = ontology.extraction_schema_for(data, ontology.ner_types(data, "PPT"))
    assert {e["name"] for e in s["entity_types"]} == {"DELIVERABLE", "TEAM_PROFILE", "TECHNICAL_REQUIREMENT", "QUALIFICATION"}
    (accepts,) = s["relation_types"]
    assert accepts["name"] == "ACCEPTS" and accepts["head_types"] == ["TEAM_PROFILE"]
    award = ontology.extraction_schema_for(data, ontology.ner_types(data, "BoardMinutes"))
    assert [r["name"] for r in award["relation_types"]] == ["MEMBER_OF", "SUBCONTRACTS"]
    bid = next(e for e in award["entity_types"] if e["name"] == "BID")
    assert {"lot", "bidder", "bidder_nif", "price", "total_score"} <= {a["name"] for a in bid["attributes"]}


def test_feed_lacks():
    full = {"award_criteria": [{"name": "Precio"}], "guarantees": [{}],
            "requirements": [{"group": "financial", "text": "Volumen anual de negocios de 300.000 euros", "threshold": 300000}]}
    assert feed_lacks(full) == set()
    pointer = dict(full, requirements=[{"group": "financial", "text": "Según cláusula 8ª PCAP", "threshold": None},
                                       {"group": "declaration", "text": "Capacidad de obrar"}])
    assert feed_lacks(pointer) == {"REQUIREMENT"}
    assert feed_lacks({}) == {"AWARD_CRITERION", "REQUIREMENT", "GUARANTEE"}


@pytest.mark.parametrize("word,n", [("octava", 8), ("NOVENA", 9), ("décima", 10), ("undécima", 11),
                                    ("decimotercera", 13), ("Décima tercera", 13), ("vigésimo primera", 21)])
def test_ordinals(word, n):
    assert L.ordinal(word) == n


def test_references_outermost_first():
    assert L.references("De conformidad con el apartado 9.1 del anexo I al PCAP") == [("annex", "I"), ("section", "9.1")]
    assert L.references("Según cláusula X. B) 1 del PCAP") == [("clause", "10"), ("letter", "B")]
    assert L.references("Conforme a la cláusula novena del PCAP") == [("clause", "9")]
    assert L.references("Según pliegos") == []


PCAP = """PLIEGO DE CLÁUSULAS ADMINISTRATIVAS PARTICULARES
ÍNDICE
CLÁUSULA 8. SOLVENCIA ........................................ 12
ANEXO I. CUADRO DE CARACTERÍSTICAS .......................... 30

CLÁUSULA 7. Garantías
La garantía definitiva será del 5 % del precio de adjudicación.

CLÁUSULA OCTAVA. Solvencia
Los licitadores acreditarán la solvencia que se indica en el Anexo I.

ANEXO I. CUADRO DE CARACTERÍSTICAS
9. CRITERIOS DE ADJUDICACIÓN
Precio: hasta 60 puntos.
Calidad de la memoria técnica: hasta 40 puntos.
El precio de los materiales se justificará.
9.1 SOLVENCIA ECONÓMICA Y FINANCIERA
Volumen anual de negocios igual o superior a 300.000 euros.
El contrato se divide en Lote 1 y lote nº 2.
"""


def test_headings_skip_the_table_of_contents():
    doc = L.Doc(PCAP, 512)
    clause8 = [h for h in doc.headings if h["num"] == "8"]
    assert [h["title"] for h in clause8] == ["Solvencia"]          # "CLÁUSULA OCTAVA", not the index line
    assert {"annex", "clause", "number"} <= {h["kind"] for h in doc.headings}


def test_a_pointer_is_found_at_its_clause():
    doc = L.Doc(PCAP, 512)
    hit = lambda text, group="financial": [doc.text[a:b] for a, b in L.find_clause(doc, {"text": text, "group": group})]
    assert hit("Según cláusula 8ª PCAP") == ["CLÁUSULA OCTAVA. Solvencia"]
    # Nested: the 9.1 inside Anexo I, not the 9 before it.
    assert hit("De conformidad con el apartado 9.1 del anexo I al PCAP") == ["9.1 SOLVENCIA ECONÓMICA Y FINANCIERA"]
    # No pointer: the solvency heading of the requirement's group.
    assert hit("Según pliegos") == ["9.1 SOLVENCIA ECONÓMICA Y FINANCIERA"]


def test_criteria_lots_and_guarantees_by_their_words():
    doc = L.Doc(PCAP, 512)
    names = lambda spans: [doc.text[a:b] for a, b in spans]
    # A one-word name only beside its points: not "El precio de los materiales".
    assert names(L.find_criterion(doc, "Precio", 60)) == ["Precio"]
    assert names(L.find_criterion(doc, "Memoria técnica (calidad)", 40)) == ["Calidad de la memoria técnica"]
    assert names(L.find_regex(doc, L._LOT, lambda m: m.group(1) == "2")) == ["lote nº 2"]
    assert names(L.find_regex(doc, L._GUARANTEE["2"])) == ["garantía definitiva"]


def test_spans_map_onto_their_chunks():
    text = ("palabra " * 40 + "\n\n") * 3 + "Precio: hasta 60 puntos.\n"
    doc = L.Doc(text, 50)
    (span,) = L.find_criterion(doc, "Precio", 60)
    idx, a, b = doc.to_chunk(*span)
    assert doc.chunks[idx][a:b] == "Precio" and idx == len(doc.chunks) - 1


def test_a_pcap_is_read_in_its_sections_and_where_its_words_say_so():
    filler = "\n\n".join(f"CLÁUSULA {i}. ASUNTO {i}\n" + "texto general del contrato " * 30 for i in range(1, 9))
    text = (filler + "\n\nCLÁUSULA 9. RÉGIMEN DE PENALIDADES\n" + "por cada día de demora se impondrá " * 30 +
            "\n\nCLÁUSULA 10. OTRAS OBLIGACIONES\nEl jefe de obra tendrá la titulación de ingeniero de caminos.")
    doc = L.Doc(text, 60)
    keep = L.relevant_chunks(text, 60, {"PENALTY", "QUALIFICATION"})
    kept = [doc.chunks[i] for i in sorted(keep)]
    assert any("PENALIDADES" in c for c in kept) and any("ingeniero de caminos" in c for c in kept)
    assert not any("ASUNTO 3" in c for c in kept) and len(keep) < len(doc.chunks)
    # Without headings to go by, every chunk is read.
    assert L.relevant_chunks("texto sin estructura " * 200, 60, {"PENALTY"}) is None


def test_actas_are_not_read_for_bids_when_every_lot_had_one(data):
    one = {"results": [{"bids_received": 1.0}, {"bids_received": 0.0}]}
    assert "single_bid" in feed_lacks(one) and ontology.ner_types(data, "BoardMinutes", feed_lacks(one)) == set()
    several = {"results": [{"bids_received": 1.0}, {"bids_received": 4.0}]}
    assert ontology.ner_types(data, "BoardMinutes", feed_lacks(several)) >= {"BID", "CRITERION_SCORE"}
    unknown = {"results": [{"bids_received": None}]}
    assert "single_bid" not in feed_lacks(unknown)


def test_notices_are_summarised_from_the_feed():
    from placsp_pilot.codelists import Codelists
    from placsp_pilot.config import load_config
    from placsp_pilot.nlpstages import notice_summary
    cl = Codelists(load_config("/tmp/placsp-pilot-ontology-test").codelist_dir)
    t = {"tender": {"name": "Limpieza de colegios", "contract_type": {"code": "2"}, "procedure": {"code": "1"},
                    "budget_tax_excl": 120000.0, "deadline": {"date": "2026-05-04"}},
         "authority": {"name": "Ayuntamiento de Villaverde"}, "award_criteria": [{}, {}],
         "results": [{"result": {"code": "8"}, "winners": [{"name": "ACME SL"}], "amount_tax_excl": 99500.5, "bids_received": 3.0}]}
    cn = notice_summary("TenderNotice", t, cl)
    assert cn["headline"] == "Licitación: Limpieza de colegios" and cn["source"] == "feed"
    assert "Servicios por procedimiento abierto" in cn["summary"] and "120.000,00 €" in cn["summary"] and "2 criterios" in cn["summary"]
    can = notice_summary("AwardNotice", t, cl)
    assert "Adjudicado a ACME SL por 99.500,50 € sin IVA (3 ofertas)" in can["summary"]
